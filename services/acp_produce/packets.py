"""
services.acp_produce.packets — AA-364: create an empty Weekly Packet shell +
the F6 revenue-safety guard on `publish_mode`. AA-367: real assemble/status
lifecycle + `write_usage_log()` wiring, now that C3/E1-E5 exist (AA-368,
PR #110) and produce real `Piece` rows with `status='passed'`.

RESOLVED — AA-365 (14/08/2026): Nghiep gave the explicit decision AA-364/
AA-367 were both waiting on. F6 (`gates.py::gate_route_to_sellable`) is
confirmed real and wired into `pipeline.py::run_piece_through_produce_gates()`
(AA-372, 5th of 9 gates in the real DET chain). `ALLOWED_PUBLISH_MODES_UNTIL_F6`
now allows all 3 ramp states — `publish_mode` can reach `'approve_to_publish'`
and `'veto_window_auto'` through `set_publish_mode()`. The constant name is
kept as-is (not renamed) for traceability across the AA-364/AA-367/AA-365
history below; it no longer restricts anything beyond "a real ramp state",
since F6's own condition is now satisfied. See docs/implementation-notes/
AA-365.md for the full record of this decision.

The BOFU/pricing hard block (`services/acp_produce/trust_ramp.py::
packet_has_bofu_piece()` / `BofuVetoBlockedError`) is INDEPENDENT of this
guard and unaffected by this widening — a packet with any BOFU-funnel-stage
piece still cannot reach `veto_window_auto`, checked before this module's
`set_publish_mode()` is ever called.

Historical context (why the guard existed, kept for the record):
Nghiep's original AA-364 decision (05/08/2026) blocked `publish_mode` from
ever advancing past `'propose_only'` in code until F6 existed. A piece could
pass every gate that existed then (output_rules, F1, F8, F9) while pointing
at a dead `trip_url` — a concrete revenue defect nothing then caught (see
docs/implementation-notes/AA-364.md "Should know"). `set_publish_mode()` is
the ONLY function in this module (and, by convention, should stay the only
call site anywhere) that writes `acp_deliver.packets.publish_mode`, so the
guard has a single choke point. AA-367 STEP 0 (06/08/2026) re-confirmed the
guard should stay locked at that time — F6 was wired into `pipeline.py` by
then, but no fresh Nghiep decision yet existed to widen it, and separately
`acp_deliver.tenant_tour_pages` had 0 rows in dev for every real tour, so F6
failed closed on every real piece regardless of this module's own guard.
Both points are now superseded by the AA-365 decision above; F6's own
fail-closed behavior on a still-missing `tenant_tour_pages` row is unchanged
and continues to apply per-piece, independent of this module.
"""
from __future__ import annotations

from datetime import date

import asyncpg

from services.acp_produce.atom_usage import write_usage_log
from services.acp_produce.models import Piece

# Nghiep AA-365 decision (14/08/2026, supersedes AA-364's 05/08/2026 lock):
# F6 confirmed real and wired into run_gates() — all 3 ramp states now
# allowed. See module docstring for the full history/record.
ALLOWED_PUBLISH_MODES_UNTIL_F6 = frozenset({"propose_only", "approve_to_publish", "veto_window_auto"})


class PublishModeBlockedError(Exception):
    """Raised when code attempts to set publish_mode to something outside
    ALLOWED_PUBLISH_MODES_UNTIL_F6 — today that means any string that isn't
    a real ramp state, since F6's condition is satisfied and all 3 states are
    allowed (AA-365, 14/08/2026). Never catch-and-ignore this."""


async def create_packet(db: asyncpg.Connection, tenant_id: str, year: int, week: int) -> str:
    """Creates a new, empty `acp_deliver.packets` row for one ISO week —
    `status='assembling'`, `publish_mode='propose_only'` (both DB defaults,
    not overridden here). Returns the new `packet_id`. Raises on a
    duplicate (tenant_id, year, week) — the UNIQUE constraint (migration
    094) is the actual guarantee; this function doesn't pre-check."""
    row = await db.fetchrow(
        """
        INSERT INTO acp_deliver.packets (tenant_id, year, week)
        VALUES ($1, $2, $3)
        RETURNING packet_id
        """,
        tenant_id, year, week,
    )
    return str(row["packet_id"])


async def set_publish_mode(db: asyncpg.Connection, packet_id: str, mode: str) -> None:
    """Sets `acp_deliver.packets.publish_mode`. F6 (route-to-sellable) is
    confirmed real and wired into run_gates() — AA-365 Nghiep decision
    14/08/2026 widened ALLOWED_PUBLISH_MODES_UNTIL_F6 to all 3 ramp states,
    so this no longer blocks 'approve_to_publish'/'veto_window_auto'. The
    membership check stays as a general invalid-mode guard (raises for
    anything not a real ramp state). Do not add a bypass parameter, an env
    var override, or a tenant-specific exception to this check."""
    if mode not in ALLOWED_PUBLISH_MODES_UNTIL_F6:
        raise PublishModeBlockedError(
            f"publish_mode={mode!r} is not a valid mode. Only "
            f"{sorted(ALLOWED_PUBLISH_MODES_UNTIL_F6)} allowed."
        )
    await db.execute(
        "UPDATE acp_deliver.packets SET publish_mode = $1 WHERE packet_id = $2",
        mode, packet_id,
    )


async def assemble_packet(db: asyncpg.Connection, packet_id: str, piece_ids: list[str]) -> int:
    """AA-367: assigns `piece_ids` to `packet_id` — the actual "assemble"
    left undone by AA-364. Only ever assigns pieces already `status=
    'passed'` (L6 — hold visible, never silent): a missing piece_id or one
    that is `'held'`/`'in_progress'` raises `ValueError` naming exactly
    which ids were bad, rather than silently skipping them into a packet
    that looks smaller than the caller asked for. Returns the number of
    pieces assigned (== `len(piece_ids)` on success, since a partial
    assignment never happens — this function either assigns all of them or
    raises before touching any row)."""
    if not piece_ids:
        raise ValueError("assemble_packet: piece_ids must not be empty")

    rows = await db.fetch(
        "SELECT piece_id, status FROM acp_deliver.pieces WHERE piece_id = ANY($1::text[])",
        piece_ids,
    )
    found = {r["piece_id"]: r["status"] for r in rows}
    missing = [pid for pid in piece_ids if pid not in found]
    not_passed = [pid for pid in piece_ids if pid in found and found[pid] != "passed"]
    if missing or not_passed:
        raise ValueError(
            f"assemble_packet: cannot assign non-'passed' pieces to a packet — "
            f"missing={missing} not_passed={not_passed}"
        )

    await db.execute(
        "UPDATE acp_deliver.pieces SET packet_id = $1, updated_at = now() WHERE piece_id = ANY($2::text[])",
        packet_id, piece_ids,
    )
    return len(piece_ids)


async def maybe_mark_packet_ready(db: asyncpg.Connection, packet_id: str) -> bool:
    """AA-367: advances `packets.status` `assembling` -> `ready` once the
    packet has >=1 assigned piece with `status='passed'`. This threshold is
    a MINIMUM VIABLE THRESHOLD, not yet a confirmed business rule (Nghiep,
    AA-367, 06/08/2026) — Linear AA-367's own verify checklist ("packet có
    ≥1 piece 'passed'") is the only source for the ">=1"; revisit if a real
    minimum-pieces-per-packet policy is ever specified. No-ops (returns
    `False`, no UPDATE) if the packet isn't currently `'assembling'` or has
    0 passed pieces yet — safe to call repeatedly as pieces get assigned."""
    passed_count = await db.fetchval(
        "SELECT count(*) FROM acp_deliver.pieces WHERE packet_id = $1 AND status = 'passed'",
        packet_id,
    )
    if passed_count < 1:
        return False
    result = await db.execute(
        "UPDATE acp_deliver.packets SET status = 'ready' WHERE packet_id = $1 AND status = 'assembling'",
        packet_id,
    )
    return result == "UPDATE 1"


class PieceNotFoundError(Exception):
    """Raised by `set_piece_review_status()` for an unknown `piece_id`."""


async def set_piece_review_status(
    db: asyncpg.Connection, piece_id: str, decision: str, actor: str, note: str | None = None,
) -> None:
    """AA-412: records a human's per-piece Gate C decision. Independent of `pieces.status`
    (the GATE outcome, written only by `gates.py::run_gates()`) -- this is the new, separate
    `review_status` column (migration 105). `decision` must be 'approved' or 'rejected' (the
    caller maps a request body's 'approve'/'reject' verb to these before calling this). Raises
    `PieceNotFoundError` for an unknown `piece_id` rather than silently no-op'ing (result ==
    'UPDATE 0' check, same defensive style as `maybe_mark_packet_ready()`'s own guard)."""
    if decision not in ("approved", "rejected"):
        raise ValueError(f"set_piece_review_status: decision must be 'approved'/'rejected', got {decision!r}")
    result = await db.execute(
        """
        UPDATE acp_deliver.pieces
        SET review_status = $1, reviewed_by = $2, reviewed_at = now(), review_note = $3
        WHERE piece_id = $4
        """,
        decision, actor, note, piece_id,
    )
    if result == "UPDATE 0":
        raise PieceNotFoundError(f"set_piece_review_status: no piece {piece_id}")


async def packet_pieces_review_complete(db: asyncpg.Connection, packet_id: str) -> bool:
    """AA-412 (docs/implementation-notes/AA-412.md D2): True only if `packet_id` has >=1 piece
    AND every piece assigned to it has `review_status='approved'`. Used to gate
    `admin_produce.py::approve_gate_c()` before it calls `trust_ramp.confirm_ramp_transition()`
    for any mode past 'propose_only' -- the ramp mechanism itself is untouched, this is a
    pre-check one layer above it, same shape as the BOFU check `trust_ramp.py` already does
    before its own `set_publish_mode()` call."""
    row = await db.fetchrow(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE review_status = 'approved') AS approved
        FROM acp_deliver.pieces WHERE packet_id = $1
        """,
        packet_id,
    )
    return bool(row) and row["total"] > 0 and row["total"] == row["approved"]


class PacketNotReadyError(Exception):
    """Raised by `deliver_packet()` when the packet isn't `status='ready'`
    — delivery must go through the `assembling` -> `ready` gate
    (`maybe_mark_packet_ready()`), never skip straight from `assembling`."""


async def deliver_packet(db: asyncpg.Connection, pool: asyncpg.Pool, packet_id: str) -> dict[str, int]:
    """AA-367: the `ready` -> `delivered` transition. Today this is ONLY a
    `packets.status`/`delivered_at` marker — there is no real send-to-tenant
    action, because AA-365 (Gate C / trust ramp / veto window review UI)
    does not exist yet (confirmed Backlog, AA-367 STEP 0, 06/08/2026). A
    real caller (a future API route or AA-365's own approval action) decides
    WHEN to call this; this function only enforces the state machine.

    Calls `write_usage_log()` (AA-361) exactly once, for exactly this
    packet's `status='passed'` pieces, BEFORE flipping `packets.status` —
    this ordering matters: if `write_usage_log()` raises, the packet is
    still `'ready'` and the call can be retried; flipping to `'delivered'`
    first would leave the packet stuck delivered-but-unlogged with no way
    back in (this function's own `status != 'ready'` guard blocks a second
    entry once `'delivered'`). Matches the STEP 5 boundary AA-364.md
    designed (gate-pass persists the piece; only a delivered packet logs
    atom usage) and the AA-367 STEP 0 confirmation that C3/E1-E5 (AA-368)
    now produce the real `Piece` rows this reads."""
    status = await db.fetchval("SELECT status FROM acp_deliver.packets WHERE packet_id = $1", packet_id)
    if status != "ready":
        raise PacketNotReadyError(
            f"deliver_packet: packet {packet_id} is status={status!r}, must be 'ready' "
            "(call maybe_mark_packet_ready() first)"
        )

    rows = await db.fetch(
        "SELECT piece_id, body_tagged, channel FROM acp_deliver.pieces "
        "WHERE packet_id = $1 AND status = 'passed'",
        packet_id,
    )
    pieces = [
        Piece(piece_id=r["piece_id"], body_tagged=r["body_tagged"], channel=r["channel"], status="passed")
        for r in rows
    ]
    channel_by_piece_id = {p.piece_id: p.channel for p in pieces}

    usage_result = await write_usage_log(pieces, pool, today=date.today(), channel_by_piece_id=channel_by_piece_id)

    await db.execute(
        "UPDATE acp_deliver.packets SET status = 'delivered', delivered_at = now() WHERE packet_id = $1",
        packet_id,
    )
    return usage_result


__all__ = [
    "ALLOWED_PUBLISH_MODES_UNTIL_F6", "PublishModeBlockedError", "PacketNotReadyError",
    "PieceNotFoundError",
    "create_packet", "set_publish_mode", "assemble_packet", "maybe_mark_packet_ready", "deliver_packet",
    "set_piece_review_status", "packet_pieces_review_complete",
]
