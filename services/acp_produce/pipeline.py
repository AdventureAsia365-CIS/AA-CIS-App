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
deterministic, cheap) runs FIRST and short-circuits F1/F8/F9 on failure —
this is not a new choice, it is AA-363's own docstring's confirmed real
call-order rationale ("running them before the F8/F9 Nova Pro judge calls
avoids paying for a judge call on content that was always going to be
rejected for a banned word"). Only if output_rules passes do F1 (grounding,
DET) → F8 (framework, LLM) → F9 (brand_seo_audit, LLM) run.

No repair loop: `run_gates()` (gates.py) is reused for its tested F1/F8/F9
orchestration, but called with `max_repairs=0` — repair requires a real
`repair_fn` (an LLM rewrite call), which is E1-E5 generation infra that does
not exist yet (same "no C3/E1-E5" boundary above). `max_repairs=0` makes
`run_gates()` hold on the FIRST gate failure without ever invoking
`repair_fn` (`piece.repair_count(0) >= max_repairs(0)` is already true) —
`_repair_not_available()` below exists only so a violated invariant fails
loudly instead of silently.

`gate_fns` normalization (the gap AA-364.md D5 flagged): none of
gate_grounding/gate_framework/gate_brand_seo_audit match `run_gates()`'s
`Callable[[str], GateResult]` signature as-is — each needs extra
brief/tenant-specific context bound first. Done here via closures, not a
naive `gate_fns.append(gate_brand_seo_audit)` (gate_brand_seo_audit also
returns a tuple, not a bare GateResult — the closure captures the audit dict
into `_audit_holder` for its own `brand_seo_audit` column, see D4).

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

from services.acp_produce.gates import (gate_brand_seo_audit, gate_framework,
                                          gate_grounding, run_gates)
from services.acp_produce.metrics import emit_piece_metrics
from services.acp_produce.models import GateResult, Piece
from services.acp_produce.rule_adapter import apply_output_rules_to_piece


def _repair_not_available(body_tagged: str, violations: list[str]) -> str:  # pragma: no cover
    """Must never actually be called — see module docstring "No repair loop".
    `run_gates()` is invoked with max_repairs=0, so `piece.repair_count(0) >=
    max_repairs(0)` is already true on the first failure and `_hold()` runs
    before `repair_fn` is ever reached. This exists only so a future change
    that accidentally raises max_repairs above 0 fails loudly instead of
    silently calling a repair path that assumes E1-E5 generation exists."""
    raise NotImplementedError(
        "Repair requires E1-E5 generation infra, not yet built (AA-364 scope "
        "boundary, 05/08/2026) — run_piece_through_produce_gates() must only "
        "ever call run_gates() with max_repairs=0, which never reaches here."
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
    db: asyncpg.Connection,
) -> Piece:
    """Runs `piece` (already has `body_tagged`) through output_rules → F1 →
    F8 → F9, persists the terminal result to `acp_deliver.pieces`, and emits
    CloudWatch metrics at the gate-pass moment. Returns the mutated `piece`
    (status is "passed" or "held" on return, never "in_progress").

    `channel`/`slot_id`/`tenant_id` are NOT fields on `Piece` — same
    observation atom_usage.py's own docstring already made ("Piece has no
    channel field yet") for the exact same reason: they are supplied by the
    caller, not invented on the model ahead of a real consumer.
    """
    rule_result = await apply_output_rules_to_piece(piece, stage, tenant_id, db)

    if not rule_result.passed:
        piece.gate_ledger = [rule_result]
        piece.status = "held"
        piece.held_reason = f"{rule_result.gate}: {'; '.join(rule_result.violations[:3])}"
        audit: Optional[dict] = None
    else:
        audit_holder: dict[str, Optional[dict]] = {"audit": None}

        def _f1(body: str) -> GateResult:
            return gate_grounding(body, valid_ids, text_by_id)

        def _f8(body: str) -> GateResult:
            return gate_framework(body, framework)

        def _f9(body: str) -> GateResult:
            result, audit_dict = gate_brand_seo_audit(body, brand_rubric_text)
            audit_holder["audit"] = audit_dict
            return result

        run_gates(piece, [_f1, _f8, _f9], _repair_not_available, max_repairs=0)
        piece.gate_ledger = [rule_result] + piece.gate_ledger
        audit = audit_holder["audit"]

    await _persist_piece(
        db, piece, run_id=run_id, tenant_id=tenant_id, channel=channel,
        slot_id=slot_id, brand_seo_audit=audit,
    )
    emit_piece_metrics(piece)
    return piece


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
