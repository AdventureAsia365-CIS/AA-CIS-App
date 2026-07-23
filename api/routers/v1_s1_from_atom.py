"""
/v1/s1-from-atom — AA-306 S1-from-atom endpoint.

Separate route from /acp/s1 (v1_s1.py, old S1) on purpose — this is a new,
parallel writer, not a replacement, and keeping it off the production S1 path
means it can't be hit accidentally by anything already wired to /acp/s1.

Auth: same single-header pattern as v1_s1.py (verify_tenant_api_key) for
consistency across the S1 surface.
"""
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from uuid import UUID

from api.routers.auth import verify_tenant_api_key as _get_tenant
from services.content_generation.s1_from_atom import (
    DEFAULT_MODEL_TIER, GroundingError, fetch_curated_atoms, generate_s1_from_atom,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/s1-from-atom", tags=["S1-from-atom"])


def _safe_uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail=f"Invalid UUID for tour_id: {value!r}")


async def _log_run(pool, *, tour_id, prompt_version, model_tier, status, **fields) -> None:
    """AA-289: one row per generate_s1_from_atom() attempt that actually reached the LLM
    (i.e. prompt_version is not None — the "no curated atoms" 422 short-circuits before a
    system prompt is even built, so there's nothing meaningful to log against a
    prompt_version there). A gate_failed/error row is exactly the kind of regression this
    table needs visible, not just the ones that happened to pass — never skip logging a
    failure just because it's not a success.
    """
    if prompt_version is None:
        return
    gate = fields.get("gate") or {}
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO acp_contract.s1_from_atom_runs (
                    tour_id, prompt_version, model_tier, model_used, status, retries,
                    atoms_available, atoms_used_count, citation_count, word_count,
                    words_per_citation, density_pass, closed_world_pass,
                    input_tokens, output_tokens, error_message
                ) VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """,
                tour_id, prompt_version, model_tier, fields.get("model_used"), status,
                fields.get("retries"), fields.get("atoms_available"), fields.get("atoms_used_count"),
                gate.get("citation_count"), gate.get("word_count"), gate.get("words_per_citation"),
                gate.get("density_pass"), gate.get("closed_world_pass"),
                fields.get("input_tokens"), fields.get("output_tokens"), fields.get("error_message"),
            )
    except Exception as e:
        # Observability write must never fail the actual generation request/response.
        logger.warning("s1_from_atom_run_log_failed", tour_id=tour_id, error=str(e))


@router.get("/tours/{tour_id}/atoms")
async def preview_curated_atoms(
    tour_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Preview the curated atom pack a tour would generate from, without
    calling the writer model — lets a caller check atom availability/count
    before spending a generation call."""
    tour_id = _safe_uuid(tour_id)
    pool = request.app.state.pool
    atoms = await fetch_curated_atoms(tour_id, pool)
    return {"tour_id": tour_id, "atom_count": len(atoms), "atoms": atoms}


@router.post("/tours/{tour_id}/generate")
async def generate(
    tour_id: str,
    request: Request,
    model_tier: str = DEFAULT_MODEL_TIER,
    tenant=Depends(_get_tenant),
):
    """Assemble a tour page from this tour's curated atoms. 422 if the tour has
    no curated atoms yet (nothing to assemble from — run AA-299 decompose +
    AA-300 curation first). 502 if the writer's output never clears the
    grounding/density gate within retries."""
    tour_id = _safe_uuid(tour_id)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        tour_row = await conn.fetchrow(
            "SELECT tour_id, src_name, country FROM silver_aa_internal.raw_tours WHERE tour_id = $1::uuid",
            tour_id,
        )
    if not tour_row:
        raise HTTPException(status_code=404, detail=f"Tour {tour_id} not found")

    tour = {"name": tour_row["src_name"], "country": tour_row["country"]}

    try:
        result = await generate_s1_from_atom(tour_id, tour, pool, model_tier=model_tier)
    except GroundingError as e:
        logger.error("s1_from_atom_generation_failed", tour_id=tour_id, error=str(e))
        await _log_run(
            pool, tour_id=tour_id, prompt_version=e.prompt_version, model_tier=model_tier,
            status="gate_failed", retries=e.retries, gate=e.gate, error_message=str(e),
        )
        raise HTTPException(status_code=422 if "No curated atoms" in str(e) else 502, detail=str(e))
    except Exception as e:
        logger.error("s1_from_atom_generation_error", tour_id=tour_id, error=str(e))
        await _log_run(
            pool, tour_id=tour_id, prompt_version=None, model_tier=model_tier,
            status="error", error_message=str(e),
        )
        raise

    await _log_run(
        pool, tour_id=tour_id, prompt_version=result["prompt_version"], model_tier=model_tier,
        status="passed", retries=result["retries"], gate=result["gate"],
        atoms_available=result["atoms_available"], atoms_used_count=len(result["atoms_used"]),
        model_used=result["model_used"], input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
    )
    return {"tour_id": tour_id, **result}
