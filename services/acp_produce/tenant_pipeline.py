"""
services/acp_produce/tenant_pipeline.py — AA-425 [A/T-T2-T5] T3 (QA gate) + T5 (atomize).

Extends the tenant-rewrite flow that already exists at api/routers/v1_tours.py's
trigger_rewrite() / _do_rewrite_and_save() closure — T2 (the rewrite itself, via
_rewrite_tour() / content_generation/graph.py) already runs correctly there, with
real tenant brand_config (AA-424). This module is what T2's caller runs AFTER a
successful rewrite: T3 QA gate, then (on pass) T5 atomize. T4 ("Tenant Tour Pool")
is not a separate step here — it's the existing gold_aa_internal.tenant_tour_versions
UPDATE the caller already does; this module only adds the qa_status verdict that
write now carries (see migration 107).

Per AA-425's updated plan (Linear comment, 21/08, after AA-426): no temp trigger
endpoint. PoolTab.tsx's existing "Rewrite" button (-> POST /pool/{id}/rewrite ->
_rewrite_tour()) IS the entry point T1 will eventually relabel, not replace.

Decisions (see docs/implementation-notes/AA-425.md for the full list):
- T3's "structural" check reuses validate_node's OWN verdict (result["failure_codes"],
  graph.py:448) rather than re-invoking validate_node a second time on identical
  content — T2's graph already ran it once as the "validate" node.
- T3's "grounding" check reuses find_novel_numeric_claims() (services/acp_shared/
  grounding.py) but, unlike s1_from_atom.py's citation-keyed check_grounding(),
  compares each rewritten sentence against the WHOLE T2-input corpus. graph.py's
  free-writing engine produces no [R:atom_id] citations to key a per-citation check
  off of the way s1_from_atom.py's atom-assembly engine does.
- T3's repair loop is NOT services/acp_produce/gates.py::run_gates() — that function
  is typed around N7's Piece object (piece.body_tagged/gate_ledger/repair_count),
  a much richer domain object than a tour dict; adapting it would mean faking a
  Piece rather than really reusing it. This module reimplements the same
  gate-then-repair SPIRIT (bounded rounds, re-check everything after each repair)
  at the smaller scale T3 actually needs.
- TENANT_QA_MAX_REPAIRS=2 is a NEW constant, deliberately not services/acp_produce/
  models.py::REPAIR_TOTAL_MAX (=3, N7's unrelated budget) — Nghiep's explicit
  naming guidance in the AA-425 decision comment, to keep the two systems' budgets
  from being confused with each other.
"""
from __future__ import annotations

import json
import re
import uuid

import structlog

from api.routers.v1_atoms import (
    _SYSTEM_PROMPT,
    _build_user_prompt,
    _source_hash,
    _strip_json_fence,
)
from services.acp_shared.grounding import find_novel_numeric_claims
from shared.llm_client.bedrock_satellite import invoke_claude

logger = structlog.get_logger()

TENANT_QA_MAX_REPAIRS = 2  # AA-425 — separate from acp_produce.models.REPAIR_TOTAL_MAX (N7, =3)

# Fields checked for both gates — same set graph.py's validate_node treats as the
# rewrite's real prose output (name/seo_title/seo_meta excluded: short/derived,
# not narrative claims — same exclusion s1_from_atom.py's _GATED_FIELDS makes).
_T3_GATED_FIELDS = ("subtitle", "summary", "highlights", "itineraries")

# Sentence-boundary heuristic — same value services/content_generation/s1_from_atom.py
# uses for its own entailment check (that module's _SENT_SPLIT_RE is private, so this
# is a copy, not an import; the two checks compare against different ground truth so
# they aren't the same function anyway — see module docstring).
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'‘’“”])")


def _t3_grounding_check(rewritten: dict, source_texts: list[str]) -> list[dict]:
    """T3 grounding gate — does the tenant-rewritten content assert a number/
    measurement absent from source_texts (T2's INPUT: the pre-rewrite
    published_tours fields)? Returns a list of {field, sentence, novel_numbers}."""
    violations: list[dict] = []
    for field in _T3_GATED_FIELDS:
        val = rewritten.get(field)
        texts = val if isinstance(val, list) else [val] if val else []
        for t in texts:
            for sent in _SENT_SPLIT_RE.split(str(t)):
                novel = find_novel_numeric_claims(sent, source_texts)
                if novel:
                    violations.append({
                        "field": field, "sentence": sent.strip(), "novel_numbers": novel,
                    })
    return violations


def _t3_structural_issues(result: dict) -> list[str]:
    """T3 structural gate — reuse validate_node's own verdict (already computed by
    T2's graph run as the 'validate' node; see module docstring)."""
    return list(result.get("failure_codes") or [])


async def run_t3_qa_gate(
    tour_dict: dict,
    source_texts: list[str],
    initial_result: dict,
    brand_rules: dict,
    max_repairs: int = TENANT_QA_MAX_REPAIRS,
) -> dict:
    """Self-repair loop, max `max_repairs` regenerate attempts (default 2). Attempt 0
    checks `initial_result` (T2's already-computed output — no extra LLM call for the
    first check). Each failing attempt regenerates via _rewrite_tour() (imported
    locally to avoid a v1_pipeline <-> tenant_pipeline import cycle at module load)
    and re-checks both gates on the fresh output.

    Returns {"passed": bool, "result": <latest rewrite result dict>, "attempts": int,
    "structural_issues": [...], "grounding_issues": [...]}."""
    from api.routers.v1_pipeline import _rewrite_tour

    result = initial_result
    attempt = 0
    while True:
        generated = result.get("generated") or {}
        structural = _t3_structural_issues(result)
        grounding = _t3_grounding_check(generated, source_texts)

        if not structural and not grounding:
            return {
                "passed": True, "result": result, "attempts": attempt,
                "structural_issues": [], "grounding_issues": [],
            }

        if attempt >= max_repairs:
            return {
                "passed": False, "result": result, "attempts": attempt,
                "structural_issues": structural, "grounding_issues": grounding,
            }

        attempt += 1
        logger.info("t3_qa_repair_attempt", attempt=attempt,
                    structural_count=len(structural), grounding_count=len(grounding))
        result = await _rewrite_tour(
            tour_dict, idx=0, total=1, brand_rules=brand_rules, is_tenant_rewrite=True,
        )


async def escalate_t3_failure(
    pool, tenant_id: str, tour_id: str, version_id: str,
    structural_issues: list[str], grounding_issues: list[dict],
) -> None:
    """T3 exhausted its repair budget — write a review_queue row a tenant-facing
    view can later filter by tenant_id (migration 107: generated_content_id is now
    nullable — it has no meaning for a tenant-rewrite escalate, and forcing an
    unrelated id in would violate its FK to silver_aa_internal.generated_content).
    escalate_detail carries the issue's mandated {check_id, field, description,
    source_span, suggested_fix} shape per entry — never an LLM self-score."""
    detail = []
    for code in structural_issues:
        detail.append({
            "check_id": f"structural:{code}", "field": None,
            "description": code, "source_span": None, "suggested_fix": None,
        })
    for v in grounding_issues:
        detail.append({
            "check_id": "grounding:novel_numeric_claim", "field": v["field"],
            "description": (
                f"Unsupported number(s) {v['novel_numbers']} in a {v['field']} sentence"
            ),
            "source_span": v["sentence"][:500], "suggested_fix": None,
        })
    summary = (
        f"T3 QA failed after {TENANT_QA_MAX_REPAIRS} repair attempt(s) — "
        f"{len(structural_issues)} structural, {len(grounding_issues)} grounding issue(s)"
    )
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO silver_aa_internal.review_queue
                (tour_id, tenant_id, tenant_tour_version_id, failure_summary, escalate_detail)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5::jsonb)
        """, tour_id, tenant_id, version_id, summary, json.dumps(detail))
    logger.info("t3_escalated", tenant_id=tenant_id, tour_id=tour_id, version_id=version_id,
                structural_count=len(structural_issues), grounding_count=len(grounding_issues))


async def run_t5_atomize(tenant_id: str, tour_id: str, rewritten: dict, pool) -> dict:
    """T5 — decompose atoms from T4 output (tenant-rewritten), owner_scope=tenant_id.
    Reuses AA-299's proven prompt/parse pipeline from api/routers/v1_atoms.py
    (_build_user_prompt, _SYSTEM_PROMPT, _strip_json_fence, invoke_claude) — the
    two changes AA-425 asks for: (1) `row` built from T4 output, not a
    v_trip_registry SELECT (raw source); (2) owner_scope=tenant_id, not 'platform'.

    Idempotency fix vs. v1_atoms.py::_decompose_inline() (invisible there because
    owner_scope was always 'platform' — never exercised with more than one owner
    per tour_id): the source_hash lookup is scoped to (tour_id, owner_scope)
    together, not tour_id alone, so two tenants rewriting the same underlying
    tour_id can't read each other's most-recent atom row when deciding whether to
    skip as unchanged.

    tour_id here MUST be silver_aa_internal.raw_tours.tour_id (acp_contract.
    tour_atoms.tour_id's FK target) — the caller passes published_tours.tour_id
    (same value, already selected alongside published_tours.id in
    trigger_rewrite()), not tenant_tour_versions.id or published_tours.id.
    """
    row = {
        "id": tour_id,
        "name": rewritten.get("name") or "",
        "aa_summary": rewritten.get("summary") or "",
        "aa_highlights": rewritten.get("highlights") or [],
        "itinerary_source": rewritten.get("itineraries") or "",
    }
    source_hash = _source_hash(row)

    async with pool.acquire() as conn:
        latest_hash = await conn.fetchval(
            """SELECT source_hash FROM acp_contract.tour_atoms
               WHERE tour_id = $1::uuid AND owner_scope = $2
               ORDER BY created_at DESC LIMIT 1""",
            tour_id, tenant_id,
        )
    if latest_hash is not None and latest_hash == source_hash:
        logger.info("t5_atomize_skipped", tour_id=tour_id, tenant_id=tenant_id,
                    reason="source unchanged (hash match)")
        return {"status": "skipped", "atom_count": 0}

    prompt = _build_user_prompt(row)
    try:
        import asyncio
        llm_result = await asyncio.to_thread(
            invoke_claude, prompt, model="sonnet", max_tokens=4096, system=_SYSTEM_PROMPT,
        )
    except Exception as e:
        logger.error("t5_atomize_llm_failed", tour_id=tour_id, tenant_id=tenant_id,
                     error_type=type(e).__name__, error=str(e))
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}

    try:
        atoms = json.loads(_strip_json_fence(llm_result.text))["atoms"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("t5_atomize_parse_failed", tour_id=tour_id, tenant_id=tenant_id, error=str(e))
        return {"status": "failed", "error": f"invalid atom JSON from model: {e}"}

    inserted = 0
    async with pool.acquire() as conn:
        if atoms:
            for atom in atoms:
                atom_id = f"atom_{uuid.uuid4().hex[:10]}"
                await conn.execute("""
                    INSERT INTO acp_contract.tour_atoms
                        (atom_id, tour_id, owner_scope, text, activity_type, emotional_hook,
                         visual_potential, persona_fit, season_note, starred, deleted, weight,
                         source_hash, itinerary_day, created_at, updated_at)
                    VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11, $12, $13,
                            $14, now(), now())
                """, atom_id, tour_id, tenant_id, atom.get("text"), atom.get("activity_type"),
                    atom.get("emotional_hook"), atom.get("visual_potential", 1),
                    json.dumps(atom.get("persona_fit") or []), atom.get("season_note"),
                    False, False, 1.0, source_hash, atom.get("itinerary_day"))
                inserted += 1
        else:
            marker_id = f"atom_marker_{uuid.uuid4().hex[:10]}"
            await conn.execute("""
                INSERT INTO acp_contract.tour_atoms
                    (atom_id, tour_id, owner_scope, text, starred, deleted,
                     is_empty_marker, weight, source_hash, created_at, updated_at)
                VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, now(), now())
            """, marker_id, tour_id, tenant_id,
                "(zero-atom marker — no content, see is_empty_marker)",
                False, False, True, 1.0, source_hash)

    logger.info("t5_atomize_done", tour_id=tour_id, tenant_id=tenant_id, atom_count=inserted)
    return {"status": "success", "atom_count": inserted}
