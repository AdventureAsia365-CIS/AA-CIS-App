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
        raise HTTPException(status_code=422 if "No curated atoms" in str(e) else 502, detail=str(e))

    return {"tour_id": tour_id, **result}
