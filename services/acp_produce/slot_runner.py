"""
services.acp_produce.slot_runner — N7 real slot-runner (AA-375), glue-only.

Every module this chains through (research.py C1-C3, generation.py E1/E2,
adapt.py E3, faq.py E4, pipeline.py F1-F9) already says the same thing in its
own docstring: no real slot-runner exists yet to chain them against a real
`Slot` (adapt.py: "no real slot-runner exists yet to enforce this, so it's a
call-order contract, not a code guard"; generation.py: "caller (the
not-yet-built slot runner) is expected to log this to unknown_ledger and skip
the slot"). This module is that caller. `tests/verify_scripts/
aa367_real_piece_chain.py` (AA-367) hand-inlined this exact same chain as
one-off test-only glue because this module didn't exist yet — that script is
NOT touched here and stays as-is (still test-only, still not importing this
module), but its call order is the reference this module follows.

Scope boundary (AA-375, Nghiep, 07/08/2026): glue function only. Explicitly
NOT built here, both deferred until AA-377 (Slot persistence) + AA-378
(acp_runs table decision) land:
- No router (HTTP entry point).
- No cron/EventBridge trigger. Wiring one now — before Slot persistence is
  decided (AA-377) — would re-run `allocate_month()` fresh on every trigger,
  handing this function a NEW non-stable `slot_id` each time and producing
  duplicate content instead of resuming/retrying the same slot.

`market` (STEP 2 finding): the issue text assumed `Trip.market` exists to
resolve from. It does not — `services/acp_planning/models.py::Trip` (the
Pydantic model backing `acp_contract.v_trip_registry`, migration 078) has no
`market` field, and grepping `services/acp_planning/*.py` confirms `market`/
`primary_market` is ALWAYS a caller-supplied parameter throughout N4-N6
(`runway_map(markets=...)`, `plan_quarter(markets=...)`,
`allocate_month(primary_market=...)`) — `runway.py` says so directly ("no
tenant market-config table in this schema yet"). Not invented here: this
function takes `market: str` as a required caller-supplied parameter, same
convention as `run_slot_research()` (research.py) and `allocate_month()`
(allocator.py) already use. Whoever calls this (the future AA-377/378
trigger) resolves it the same way `allocate_month()`'s caller already has to.

Error handling for E2/E4 failures: `generate_draft()` and `apply_faq()` each
raise (`DraftGenerationFailed`/`FAQAnswerFailed`) rather than ever emitting a
partial/fabricated result — generation.py's own docstring names this
module ("the not-yet-built slot runner") as the intended catcher, instructing
it to log to `unknown_ledger` and skip the slot (L6: hold visible, never
silent, same spirit as gates.py's F1-F9). Done here via `research.log_unknown
(..., kind="other")` — "other" because neither failure fits the four
demand/atom/CTA/PAA kinds `research.py` already defines.

`pool` parameter: present in this function's signature because the issue
asked for it (glue task spec, 07/08/2026), but nothing in the real chain
below (`run_slot_research` / `build_outline` / `generate_draft` /
`adapt_channels` / `apply_faq` / `run_piece_through_produce_gates`) takes a
`pool` — every one of them takes only `db: asyncpg.Connection`. Kept,
unused, rather than silently dropped (the caller may still want the same
`(db, pool, ...)` shape `packets.deliver_packet()` already uses) — flagged
here rather than inventing a fake use for it. Worth confirming with whoever
wires AA-377/378 whether this function should eventually call packet
assembly itself (it currently does not — packet assembly is AA-367's own
`packets.py`, untouched, a separate call the caller still makes on its own).
"""
from __future__ import annotations

import json
from typing import Optional

import asyncpg
import structlog

from services.acp_planning.models import Slot
from services.acp_produce.adapt import adapt_channels
from services.acp_produce.faq import FAQAnswerFailed, apply_faq
from services.acp_produce.generation import DraftGenerationFailed, build_outline, generate_draft
from services.acp_produce.models import Piece
from services.acp_produce.pipeline import run_piece_through_produce_gates
from services.acp_produce.research import fetch_slot_atoms, log_unknown, run_slot_research
from services.content_generation.brand_standards import AA_BRAND_IDENTITY_PROMPT
from services.seo_intelligence.dataforseo_client import DataForSEOClient

logger = structlog.get_logger()


async def fetch_brand_rubric_text(db: asyncpg.Connection, tenant_id: str) -> str:
    """AA-404 F9 fix #1 — real per-tenant brand voice from `shared.tenant_brand_rules`,
    replacing the hardcoded `AA_BRAND_IDENTITY_PROMPT` constant every F9 call used until now
    (see `gate_brand_seo_audit()`'s docstring, `gates.py`, for the full history of why that was
    the case up to this point).

    Same default-brand resolution shape as `api/routers/admin_pipeline.py::_resolve_brand_rule()`'s
    no-`brand_identity_id`/no-`brand_name` branch (`tenant_id` + `brand_name = 'default'` +
    `is_active = true`) — reused, not reinvented; this codebase's multi-brand resolver (AA-198)
    already established this exact convention. A standalone query rather than importing that
    router-private function directly: `api.routers.*` is a higher layer than `services.
    acp_produce.*` (importing downward would invert the dependency direction every other module
    in this package already follows, and risks the same api/__init__.py import-cycle trap
    `admin_produce.py`'s own module docstring already documents for `slot_runner`).

    Falls back to `AA_BRAND_IDENTITY_PROMPT` (unchanged) if no active 'default' row exists for
    `tenant_id`, or its `system_prompt` is empty — e.g. a tenant onboarded before its brand
    content was populated. Logged as a warning, not silent (L6 convention, same as every other
    "hold visible" gap in this pipeline) — a tenant silently running on the generic fallback is
    a real thing a human should notice, not an assumed-fine default."""
    row = await db.fetchrow(
        """
        SELECT system_prompt, style_guide, forbidden_words, good_examples
        FROM shared.tenant_brand_rules
        WHERE tenant_id = $1::uuid AND brand_name = 'default' AND is_active = true
        LIMIT 1
        """,
        tenant_id,
    )
    system_prompt = (row["system_prompt"] if row else None) or ""
    if not system_prompt.strip():
        logger.warning(
            "brand_rubric_fallback_generic", tenant_id=tenant_id,
            reason="no active 'default' shared.tenant_brand_rules row, or system_prompt empty",
        )
        return AA_BRAND_IDENTITY_PROMPT

    forbidden_words = row["forbidden_words"]
    if isinstance(forbidden_words, str):
        # asyncpg jsonb gap (no codec registered, AA-300/AA-314) — comes back as JSON text.
        forbidden_words = json.loads(forbidden_words) if forbidden_words else []
    forbidden_words = forbidden_words or []

    parts = [system_prompt.strip()]
    if row["style_guide"]:
        parts.append(f"STYLE GUIDE:\n{row['style_guide'].strip()}")
    if forbidden_words:
        parts.append("FORBIDDEN WORDS/PHRASES: " + ", ".join(forbidden_words))
    if row["good_examples"]:
        parts.append(
            "GOOD EXAMPLES (real, on-brand — do not flag writing like this as generic):\n"
            f"{row['good_examples'].strip()}"
        )
    return "\n\n".join(parts)


async def run_slot_production(
    db: asyncpg.Connection,
    pool,  # asyncpg.Pool — accepted per issue spec, currently unused (see module docstring)
    tenant_id: str,
    slot: Slot,
    run_id: str,
    market: str,
    dfs_client: Optional[DataForSEOClient] = None,
) -> list[Piece]:
    """C1-C3 -> E1 -> E2 -> E3 -> E4 -> F1-F9 for ONE `slot`, real functions,
    zero mocking. Does NOT create `run_id` (caller-supplied — AA-378's own
    `acp_runs` table decision is not this issue's scope) and does NOT call
    `allocate_month()` itself (`slot` is caller-supplied — keeps this
    function pure/testable, same separation-of-concerns `research.py`'s own
    module docstring already draws for C1/C2's `market` parameter).

    Returns every `Piece` this slot produced (blog + up to 2 adapted channel
    pieces), each already gate-run and persisted via
    `run_piece_through_produce_gates()` — status is "passed" or "held" on
    each, never "in_progress". Returns `[]` when the slot never reaches a
    Piece at all: TOPIC REJECTED by `compile_brief()` (already logged to
    `unknown_ledger` by that function) or a caught E2/E4 generation failure
    (logged to `unknown_ledger` here, `kind="other"`, before returning).

    `run_piece_through_produce_gates()` is still called with the
    `max_repairs=0` no-repair path (pipeline.py's own current limitation,
    AA-367.md gap #4, not fixed by this issue) — a real piece failing any
    gate holds outright, it does not retry here.
    """
    brief = await run_slot_research(db, tenant_id, slot, market, dfs_client)
    if brief is None:
        return []  # TOPIC REJECTED — compile_brief() already logged the reason

    atoms = await fetch_slot_atoms(slot.atom_ids, db)
    atom_text_by_id = {a["atom_id"]: a["text"] for a in atoms}

    outline = build_outline(brief)
    try:
        blog_body = generate_draft(brief, outline, atom_text_by_id)
    except DraftGenerationFailed as e:
        await log_unknown(
            db, tenant_id, "other", f"Slot {slot.slot_id}: E2 draft generation failed: {e}",
            slot_id=slot.slot_id, keyword=brief.keyword,
        )
        return []

    blog_piece = Piece(
        piece_id=f"{run_id}:{slot.slot_id}:blog", body_tagged=blog_body, channel="blog", status="in_progress",
    )

    # E3 before E4 — adapt.py's own call-order contract (cite blog's own
    # atoms before FAQ appends more citations to body_tagged).
    channel_pieces = adapt_channels(blog_piece, atom_text_by_id)

    try:
        blog_piece = apply_faq(blog_piece, brief, atom_text_by_id)
    except FAQAnswerFailed as e:
        await log_unknown(
            db, tenant_id, "other", f"Slot {slot.slot_id}: E4 FAQ answer failed: {e}",
            slot_id=slot.slot_id, keyword=brief.keyword,
        )
        return []

    tour_id = str(slot.trip_id) if slot.trip_id else None
    # Fetched once per slot (not per-piece) — same tenant, same rubric for every piece this
    # slot produces; 3 identical queries would be redundant.
    brand_rubric_text = await fetch_brand_rubric_text(db, tenant_id)
    results: list[Piece] = []
    for piece in [blog_piece] + channel_pieces:
        result = await run_piece_through_produce_gates(
            piece, run_id=run_id, tenant_id=tenant_id, channel=piece.channel,
            valid_ids=set(atom_text_by_id), text_by_id=atom_text_by_id,
            framework=brief.framework, brand_rubric_text=brand_rubric_text,
            stage=None, slot_id=slot.slot_id, brief=brief, tour_id=tour_id, db=db,
        )
        logger.info(
            "slot_production_piece_done", slot_id=slot.slot_id, piece_id=result.piece_id,
            channel=result.channel, status=result.status, held_reason=result.held_reason,
        )
        results.append(result)
    return results


__all__ = ["run_slot_production", "fetch_brand_rubric_text"]
