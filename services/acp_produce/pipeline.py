"""
services.acp_produce.pipeline — AA-364 first orchestrator: runs ONE already-
generated Piece through the real gate stack, persists it to
`acp_deliver.pieces`, and emits its gate-pass metrics.

Hard scope boundary (Nghiep, AA-364, 05/08/2026): this module does NOT
generate content. C3 (brief compile) and E1-E5 (the writer call that
produces `piece.body_tagged`) still do not exist anywhere in this repo
(confirmed again by re-reading services/acp_produce/ in full before writing
this file — see docs/implementation-notes/AA-364.md STEP 0). Every function
here takes a `Piece` that ALREADY has `body_tagged` set, exactly like the 4
existing test files (test_aa298_gates.py, test_aa361/362/363_*.py) already
hand-construct. Nothing in this module fabricates a substitute for C3/E1-E5.

Gate order and the reason for it: `apply_output_rules_to_piece()` (AA-363,
deterministic, cheap) runs FIRST and short-circuits every other gate on
failure — this is not a new choice, it is AA-363's own docstring's confirmed
real call-order rationale ("running them before the F8/F9 Nova Pro judge
calls avoids paying for a judge call on content that was always going to be
rejected for a banned word"). Only if output_rules passes does the rest of
the stack run, DET-cheapest-first: F1 (grounding) → F2 (banned patterns) →
F3 (structural variance) → F4 (brief compliance) → F6 (route-to-sellable) →
F7 (FAQ dedup) → F8 (framework, LLM) → F9 (brand_seo_audit / brand_seo_audit
_social, LLM) — AA-372 wires F2/F3/F4/F6/F7 in; F5 does not exist by design
(AA-372's own numbering skips it, see gates.py module docstring).

Channel routing (AA-372): each new DET gate takes `channel` and no-ops/
branches internally (F3/F4 are blog-only by design; F6/F7 apply to every
channel) — same "gate self-checks, orchestrator untouched" pattern the
ported aamc/ prototype already used for its own F4/F5. F8's rubric is
resolved from `services.acp_planning.constants.FRAMEWORK_TABLE` for
facebook/tiktok (`hook_story_cta`/`hook_beats_payoff`) rather than trusting
the caller's `framework` argument for those channels — an adapted-channel
`Piece` (AA-371's `adapt_channels()`) has no `Brief` of its own, so the blog
`Brief.framework` a caller might pass would be the wrong rubric key. F9
routes to `gate_brand_seo_audit()` (blog) or `gate_brand_seo_audit_social()`
(facebook/tiktok, AA-372) by the same `channel`.

Repair loop (AA-376, wired real): `run_gates()` (gates.py) is called with
`repair_fn=repair_piece` (`services.acp_produce.repair`, E5 — Sonnet rewrite
call, ported from the aamc/ prototype's own E5) and
`max_repairs=REPAIR_TOTAL_MAX` (models.py, ADR-2026-029's already-decided
budget of 3 repair ROUNDS, imported rather than re-hardcoded). A piece
failing any gate now gets up to `REPAIR_TOTAL_MAX` repair rounds — each round
re-runs the ENTIRE gate stack (P0-3, gates.py's own docstring) — before
holding. `is_repairable=_is_f6_content_fixable` (below) filters OUT F6
violations that are external caller/DB state ("no cta_target", "url_alive
not True" — `acp_deliver.tenant_tour_pages` row/`Brief.cta_target`, neither
of which `body_tagged` text can ever fix) so `run_gates()` holds those
immediately instead of burning a repair round + a Sonnet call on a violation
`repair_piece()` cannot possibly resolve. The `output_rules` pre-check above
stays OUTSIDE this repair loop entirely — it runs before `run_gates()` is
even called and short-circuits straight to `held` on failure; that gap is
tracked separately (AA-381), not touched here.

`gate_fns` normalization (the gap AA-364.md D5 flagged): none of the real
gate functions match `run_gates()`'s `Callable[[str], GateResult]` signature
as-is — each needs extra brief/tenant-specific context bound first. Done
here via closures, not a naive `gate_fns.append(gate_brand_seo_audit)`
(gate_brand_seo_audit/gate_brand_seo_audit_social also return a tuple, not a
bare GateResult — the closure captures the audit dict into `_audit_holder`
for its own `brand_seo_audit` column, see D4). F6's `url_alive` is fetched
from `acp_deliver.tenant_tour_pages` ONCE, before `run_gates()` runs (not
inside the closure) — DET gates stay side-effect-free/synchronous, same
convention F9's pre-fetched `brand_rubric_text` already established.

STEP 5 boundary (docs/implementation-notes/AA-364.md) enforced here: this
module calls `emit_piece_metrics()` (AA-362) at the gate-pass moment.
It NEVER calls `write_usage_log()` (AA-361) — that only fires once a
`Piece`'s packet actually reaches `status='delivered'`, which is packet
assembly's job (not built here — see services/acp_produce/packets.py's own
scope note).
"""
from __future__ import annotations

import json
from typing import Optional

import asyncpg

from services.acp_planning.constants import FRAMEWORK_TABLE
from services.acp_produce.gates import (gate_banned_patterns, gate_brand_seo_audit,
                                          gate_brand_seo_audit_social, gate_brief_compliance,
                                          gate_faq_dedup, gate_framework, gate_grounding,
                                          gate_route_to_sellable, gate_structural_variance,
                                          run_gates)
from services.acp_produce.metrics import emit_piece_metrics
from services.acp_produce.models import REPAIR_TOTAL_MAX, Brief, GateResult, Piece
from services.acp_produce.repair import repair_piece
from services.acp_produce.rule_adapter import apply_output_rules_to_piece

# F6's two external-state violations (Brief.cta_target missing / no confirming
# acp_deliver.tenant_tour_pages row — see gate_route_to_sellable(), gates.py)
# can never be fixed by rewriting body_tagged. The third F6 sub-check ("CTA
# {target} not present in body") stays repairable (a literal-string content
# fix) — matched separately below, never lumped in with these two.
_F6_NON_CONTENT_FIXABLE_MARKERS = ("no cta target", "url_alive is not true")


def _is_f6_content_fixable(result: GateResult) -> bool:
    """AA-376 `is_repairable` filter passed to `run_gates()`: True for every
    gate except F6, and for F6 only when none of its violations are the
    external-state kind above — inspecting individual violation strings
    (not just `result.gate`) because a real F6 failure can carry the
    repairable "CTA not present in body" violation alongside an unrelated
    non-repairable one on the same round."""
    if result.gate != "F6_route_to_sellable":
        return True
    return not any(
        marker in v.lower() for v in result.violations for marker in _F6_NON_CONTENT_FIXABLE_MARKERS
    )


async def run_piece_through_produce_gates(
    piece: Piece,
    *,
    run_id: str,
    tenant_id: str,
    channel: str,
    valid_ids: set[str],
    text_by_id: dict[str, str],
    framework: str,
    brand_rubric_text: str,
    stage: Optional[int],
    slot_id: Optional[str] = None,
    brief: Optional[Brief] = None,
    tour_id: Optional[str] = None,
    db: asyncpg.Connection,
) -> Piece:
    """Runs `piece` (already has `body_tagged`) through output_rules → F1 →
    F2 → F3 → F4 → F6 → F7 → F8 → F9, persists the terminal result to
    `acp_deliver.pieces`, and emits CloudWatch metrics at the gate-pass
    moment. Returns the mutated `piece` (status is "passed" or "held" on
    return, never "in_progress").

    Repair (AA-376): a gate failure now gets up to `REPAIR_TOTAL_MAX` (3,
    ADR-2026-029) repair rounds via `repair_piece()` (E5, real Sonnet
    rewrite call) before holding — `run_gates()`'s own P0-3 fix re-runs the
    ENTIRE stack after each round, so a repair that fixes one gate but
    regresses an earlier one gets caught, not shipped. F6 violations that
    are external caller/DB state ("no cta_target", "url_alive not True") are
    filtered out by `_is_f6_content_fixable` and hold immediately instead —
    no amount of rewriting `body_tagged` fixes a missing `tenant_tour_pages`
    row, so attempting repair there would only waste a round + a Sonnet
    call. `output_rules` above stays outside this repair loop entirely
    (short-circuits to `held` before `run_gates()` is even called) — that
    gap is AA-381, not this issue's scope.

    `channel`/`slot_id`/`tenant_id` are NOT fields on `Piece` — same
    observation atom_usage.py's own docstring already made ("Piece has no
    channel field yet") for the exact same reason: they are supplied by the
    caller, not invented on the model ahead of a real consumer. (`Piece` did
    gain its own `channel` field since, AA-371 — this `channel` kwarg stays
    the single source of truth for gate routing here anyway, so the two can
    never silently diverge for THIS call.)

    `brief` (AA-372) feeds F4 (blog brief compliance) and F6 (`cta_target`)
    — `None` is a legitimate value for an adapted facebook/tiktok `Piece`
    that shares its parent blog piece's Brief for `cta_target` only (F4
    itself no-ops for non-blog channels regardless). `tour_id` (AA-372) is
    the `acp_deliver.tenant_tour_pages` lookup key for F6's `url_alive` —
    `None` means "unknown route", which F6 fails closed on, same as no row.
    """
    rule_result = await apply_output_rules_to_piece(piece, stage, tenant_id, db)

    if not rule_result.passed:
        piece.gate_ledger = [rule_result]
        piece.status = "held"
        piece.held_reason = f"{rule_result.gate}: {'; '.join(rule_result.violations[:3])}"
        audit: Optional[dict] = None
    else:
        audit_holder: dict[str, Optional[dict]] = {"audit": None}
        cta_target = brief.cta_target if brief else None
        url_alive = await _fetch_url_alive(db, tenant_id, tour_id) if tour_id else None
        effective_framework = _resolve_framework(channel, framework)

        def _f1(body: str) -> GateResult:
            return gate_grounding(body, valid_ids, text_by_id)

        def _f2(body: str) -> GateResult:
            return gate_banned_patterns(body, text_by_id)

        def _f3(body: str) -> GateResult:
            return gate_structural_variance(body, channel)

        def _f4(body: str) -> GateResult:
            return gate_brief_compliance(body, channel, brief)

        def _f6(body: str) -> GateResult:
            return gate_route_to_sellable(body, channel, cta_target, url_alive)

        def _f7(body: str) -> GateResult:
            return gate_faq_dedup(body)

        def _f8(body: str) -> GateResult:
            return gate_framework(body, effective_framework)

        def _f9(body: str) -> GateResult:
            if channel == "blog":
                result, audit_dict = gate_brand_seo_audit(body, brand_rubric_text)
            else:
                result, audit_dict = gate_brand_seo_audit_social(body, channel, brand_rubric_text)
            audit_holder["audit"] = audit_dict
            return result

        run_gates(piece, [_f1, _f2, _f3, _f4, _f6, _f7, _f8, _f9],
                  repair_piece, max_repairs=REPAIR_TOTAL_MAX, is_repairable=_is_f6_content_fixable)
        piece.gate_ledger = [rule_result] + piece.gate_ledger
        audit = audit_holder["audit"]

    await _persist_piece(
        db, piece, run_id=run_id, tenant_id=tenant_id, channel=channel,
        slot_id=slot_id, brand_seo_audit=audit,
    )
    emit_piece_metrics(piece)
    return piece


def _resolve_framework(channel: str, framework: str) -> str:
    """F8 routing (AA-372): for facebook/tiktok, the rubric key is resolved
    from `FRAMEWORK_TABLE[("ANY", channel)]` — NOT the caller's `framework`
    argument, which (for an AA-371-adapted Piece) would still be the blog
    Brief's framework ("hub"/"PAS"/"AIDA") and score the wrong rubric
    entirely. Falls back to the caller's `framework` if the channel isn't in
    the table (defensive — every real channel here already is)."""
    if channel == "blog":
        return framework
    fw_cfg = FRAMEWORK_TABLE.get(("ANY", channel))
    return fw_cfg["framework"] if fw_cfg else framework


async def _fetch_url_alive(db: asyncpg.Connection, tenant_id: str, tour_id: str) -> Optional[bool]:
    """F6's pre-fetch (AA-372). `tour_id` is passed as text and cast in SQL
    (`$2::uuid`) so callers can pass either a `str` or a `uuid.UUID` without
    this function caring which. Returns `None` when there is no row —
    `gate_route_to_sellable()` treats `None` the same as `False` (fail
    closed on an untracked page, confirmed against a live `SELECT`:
    `acp_deliver.tenant_tour_pages` has 0 rows in dev today, 06/08/2026)."""
    return await db.fetchval(
        "SELECT url_alive FROM acp_deliver.tenant_tour_pages WHERE tenant_id = $1 AND tour_id = $2::uuid",
        tenant_id, str(tour_id),
    )


async def _persist_piece(
    db: asyncpg.Connection,
    piece: Piece,
    *,
    run_id: str,
    tenant_id: str,
    channel: str,
    slot_id: Optional[str],
    brand_seo_audit: Optional[dict],
) -> None:
    """INSERT ... ON CONFLICT DO UPDATE on piece_id — safe to call again for
    the same piece_id if the caller retries (same convention as
    stage_checkpoint.py::checkpoint_start()'s ON CONFLICT DO UPDATE).
    `packet_id` is always NULL here — a piece is packet-less at the
    gate-pass moment (STEP 5 boundary); packet assembly sets it later."""
    gate_ledger_json = json.dumps([g.model_dump() for g in piece.gate_ledger])
    audit_json = json.dumps(brand_seo_audit) if brand_seo_audit is not None else None

    await db.execute(
        """
        INSERT INTO acp_deliver.pieces
            (piece_id, run_id, tenant_id, slot_id, channel, body_tagged,
             status, gate_ledger, brand_seo_audit, repair_count, held_reason)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11)
        ON CONFLICT (piece_id) DO UPDATE SET
            body_tagged     = EXCLUDED.body_tagged,
            status          = EXCLUDED.status,
            gate_ledger     = EXCLUDED.gate_ledger,
            brand_seo_audit = EXCLUDED.brand_seo_audit,
            repair_count    = EXCLUDED.repair_count,
            held_reason     = EXCLUDED.held_reason,
            updated_at      = now()
        """,
        piece.piece_id, run_id, tenant_id, slot_id, channel, piece.body_tagged,
        piece.status, gate_ledger_json, audit_json, piece.repair_count, piece.held_reason,
    )


__all__ = ["run_piece_through_produce_gates"]
