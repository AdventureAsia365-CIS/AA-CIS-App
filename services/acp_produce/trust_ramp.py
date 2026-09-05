"""
services.acp_produce.trust_ramp — AA-365 [N8-5]: Gate C / trust ramp / veto window.

Ports the 3-state trust ramp (aamc/delivery.py G3: RAMP, publish_gates(),
confirm_publish_mode() — docs/AI-gent-for automation works/aa-marketing-v2/
aamc/delivery.py) onto the real acp_deliver.packets.publish_mode column,
which already IS the ramp state (migration 094, AA-364/AA-367) — no new
column needed, no new migration in this issue.

F6 guard status (AA-365, 14/08/2026 — RESOLVED, see packets.py module
docstring for the full record): F6 (gate_route_to_sellable) is confirmed
real and wired into run_gates() via pipeline.py::
run_piece_through_produce_gates() (AA-372). Nghiep's follow-up AA-365
decision widened packets.py::ALLOWED_PUBLISH_MODES_UNTIL_F6 to all 3 ramp
states, so confirm_ramp_transition() below can now actually move a packet
through 'approve_to_publish' and 'veto_window_auto' via
packets.set_publish_mode() — not suggestion-only anymore.
suggest_ramp_transition() still only computes what the ramp WOULD suggest
next (mirrors the prototype's "agency-confirmed, never silently switched"
model); confirming remains a separate, explicit call.

BOFU/pricing hard block: enforced independently of the F6 guard above and
UNAFFECTED by the widening — a packet with any BOFU-funnel-stage piece still
cannot reach 'veto_window_auto', checked before packets.set_publish_mode()
is ever called (see confirm_ramp_transition() below). No 'pricing' flag
exists anywhere in the schema (AA-365 STEP 0 finding) — funnel_stage='BOFU'
(services/acp_planning/models.py::Slot, persisted into
acp_shared.acp_v2_slots.payload jsonb by
persist_slot_grid(), AA-377) is used as the concrete proxy, since BOFU is
the funnel stage this codebase already treats as the booking/pricing-intent
one (see services/acp_planning/constants.py FRAMEWORK_TABLE: BOFU blog =
AIDA, the sales-closing framework). packets/pieces carry no funnel_stage of
their own, so this is a live join through pieces.slot_id, not a cached flag.

AA-464 (06/09/2026) — nối dây: suggest_ramp_transition() had 0 real callers until this issue
(confirmed via STEP0, docs/implementation-notes/AA-464.md) because engagement_ok/weeks_active
were never computed anywhere. compute_tenant_weeks_active()/compute_tenant_engagement_ok()/
compute_tenant_ramp_signals()/compute_ramp_suggestion() below close that gap — on-demand only
(no scheduler/cron, per the issue's own recommendation), called from
api/routers/admin_a4.py's GET /trust-ramp (surfaces the suggestion) and its 2 new
approve/skip endpoints (approve is confirm_ramp_transition()'s first real caller; skip logs a
decision without mutating packets.publish_mode). suggest_ramp_transition()/
confirm_ramp_transition() themselves are UNCHANGED by this issue — still suggestion-only until
an admin explicitly approves, exactly as designed (ADR-2026-038 SS0.2).
"""
from __future__ import annotations

import json
from typing import Optional

import asyncpg

from services.acp_planning.constants import (CONFIDENCE_ATOM_MIN_POSTS,
                                              ENGAGEMENT_RATE_BASELINE)
from services.acp_produce.packets import PublishModeBlockedError, set_publish_mode

# Mirrors aamc/delivery.py::RAMP exactly.
RAMP = ["propose_only", "approve_to_publish", "veto_window_auto"]


class BofuVetoBlockedError(Exception):
    """Raised when a packet holding >=1 BOFU-funnel-stage piece attempts to
    enter 'veto_window_auto'. Hard constraint (Nghiep, AA-365) — never
    bypassable by ramp level, and checked before set_publish_mode() so it
    can't be short-circuited by some future widening of
    ALLOWED_PUBLISH_MODES_UNTIL_F6."""


async def packet_has_bofu_piece(db: asyncpg.Connection, packet_id: str) -> bool:
    """True if any piece assigned to `packet_id` came from a
    funnel_stage='BOFU' Slot. Live join, not a denormalized flag — see
    module docstring for why no such flag exists yet."""
    return await db.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
            FROM acp_deliver.pieces p
            JOIN acp_shared.acp_v2_slots s ON s.slot_id = p.slot_id
            WHERE p.packet_id = $1 AND s.payload->>'funnel_stage' = 'BOFU'
        )
        """,
        packet_id,
    )


def suggest_ramp_transition(current_mode: str, engagement_ok: bool, weeks_active: int) -> str:
    """Pure suggestion logic, ported verbatim from aamc/delivery.py::
    publish_gates() G3 (the metric-driven half — the "never silently
    switched" half is confirm_ramp_transition() below). Never mutates
    state or touches the DB."""
    ix = RAMP.index(current_mode) if current_mode in RAMP else 0
    if engagement_ok and weeks_active >= 2 and ix < len(RAMP) - 1:
        return RAMP[ix + 1]
    return current_mode


async def compute_tenant_weeks_active(db: asyncpg.Connection, tenant_id: str) -> int:
    """AA-464: number of real weekly packets this tenant has (acp_deliver.packets, migrations
    094+106). `UNIQUE (tenant_id, year, month, week)` already guarantees one row per distinct
    real calendar week for this tenant, so a plain COUNT(*) IS the weeks-active count -- no
    DISTINCT needed. Real production cadence, not calendar time since account creation."""
    count = await db.fetchval(
        "SELECT COUNT(*) FROM acp_deliver.packets WHERE tenant_id = $1", tenant_id,
    )
    return int(count or 0)


async def compute_tenant_engagement_ok(
    db: asyncpg.Connection, tenant_id: str, min_posts: int = CONFIDENCE_ATOM_MIN_POSTS,
) -> bool:
    """AA-464: tenant-wide engagement_ok signal for the ramp gate, derived from the SAME manual
    engagement data services/acp_shared/content_metrics.py already collects for atom-weight
    rollup (acp_shared.content_metric_snapshot, migration 112) -- no new metric invented. Latest
    snapshot per piece (same "DISTINCT ON piece_id ORDER BY entered_at DESC" shape
    rollup_atom_weights() already uses), reach-bearing rows only (content_metrics.py's own
    _piece_score() "unknown stays unknown" rule -- never divide by a fake reach of 1).

    Fail-closed: fewer than `min_posts` real reach-bearing snapshots means "not enough data to
    say", which returns False, never a fabricated True. `min_posts` reuses
    CONFIDENCE_ATOM_MIN_POSTS (3) -- the same confidence gate content_metrics.py already applies
    to this exact table for a different aggregation (per-atom, not tenant-wide)."""
    rows = await db.fetch(
        """
        WITH latest_snapshot AS (
            SELECT DISTINCT ON (piece_id) piece_id, reach, engagement
            FROM acp_shared.content_metric_snapshot
            WHERE tenant_id = $1::uuid
            ORDER BY piece_id, entered_at DESC
        )
        SELECT reach, engagement FROM latest_snapshot WHERE reach IS NOT NULL AND reach > 0
        """,
        tenant_id,
    )
    scores = [r["engagement"] / r["reach"] for r in rows if r["reach"]]
    if len(scores) < min_posts:
        return False
    return (sum(scores) / len(scores)) >= ENGAGEMENT_RATE_BASELINE


async def compute_tenant_ramp_signals(db: asyncpg.Connection, tenant_id: str) -> dict:
    """AA-464: bundles the 2 read-only signal computations above -- the inputs
    suggest_ramp_transition() needs but never computed anywhere before this issue (STEP0,
    docs/implementation-notes/AA-464.md). Never writes, never calls suggest_ramp_transition()
    itself (callers do that, same "compute signals, then decide" separation the rest of this
    module already keeps)."""
    weeks_active = await compute_tenant_weeks_active(db, tenant_id)
    engagement_ok = await compute_tenant_engagement_ok(db, tenant_id)
    return {"weeks_active": weeks_active, "engagement_ok": engagement_ok}


async def compute_ramp_suggestion(db: asyncpg.Connection, packet_id: str) -> dict:
    """AA-464: per-packet suggestion, computed fresh on every call (on-demand, per the issue's
    own recommendation -- no scheduler, no cache, no new table; see docs/implementation-notes/
    AA-464.md Decisions). Never writes, never calls confirm_ramp_transition() -- callers
    (api/routers/admin_a4.py) decide what to do with the suggestion; approving it is a separate,
    explicit call, per ADR-2026-038 SS0.2 (AA never auto-transitions a tenant's ramp state).

    Raises ValueError for an unknown packet_id, same convention confirm_ramp_transition() already
    uses."""
    row = await db.fetchrow(
        "SELECT tenant_id, publish_mode FROM acp_deliver.packets WHERE packet_id = $1", packet_id,
    )
    if row is None:
        raise ValueError(f"compute_ramp_suggestion: no packet {packet_id}")

    current_mode = row["publish_mode"]
    tenant_id = row["tenant_id"]
    signals = await compute_tenant_ramp_signals(db, tenant_id)
    suggested_mode = suggest_ramp_transition(
        current_mode, engagement_ok=signals["engagement_ok"], weeks_active=signals["weeks_active"],
    )
    return {
        "packet_id": packet_id,
        "tenant_id": tenant_id,
        "current_mode": current_mode,
        "suggested_mode": suggested_mode,
        "eligible": suggested_mode != current_mode,
        "engagement_ok": signals["engagement_ok"],
        "weeks_active": signals["weeks_active"],
    }


async def _log_transition(
    db: asyncpg.Connection, *, tenant_id: str, packet_id: str, actor: str,
    from_mode: str, to_mode: str, blocked: bool, block_reason: Optional[str],
) -> None:
    """Decision-log entry for a ramp transition attempt. Reuses
    acp_shared.audit_log (migration 030) — the same table every other real
    ACP gate/approval action in this repo already writes to (v1_acp_gate.py,
    v1_s3.py, v1_s4_blog.py) — rather than inventing a new logging shape, per
    the AA-365 issue's own instruction. Maps the aamc/ prototype's
    confirm_publish_mode() shape (kind/statement/payload) onto audit_log's
    real columns: action='publish_mode_transition', resource_type='packet',
    resource_id=packet_id, details carries from/to/blocked/block_reason."""
    await db.execute(
        """
        INSERT INTO acp_shared.audit_log
            (tenant_id, actor, action, resource_type, resource_id, details)
        VALUES ($1, $2, 'publish_mode_transition', 'packet', $3, $4::jsonb)
        """,
        tenant_id, actor, packet_id,
        json.dumps({
            "from": from_mode, "to": to_mode,
            "blocked": blocked, "block_reason": block_reason,
        }),
    )


async def confirm_ramp_transition(
    db: asyncpg.Connection, *, packet_id: str, tenant_id: str, mode: str, actor: str,
) -> None:
    """Attempts to move `packet_id` to ramp state `mode`. ALWAYS writes a
    Decision log entry first-class, whether the transition succeeds or is
    blocked — a blocked escalation attempt is exactly the kind of event the
    log exists to surface (same "never silently" framing packets.py's own
    PublishModeBlockedError docstring already uses, applied one layer up).

    Check order: BOFU hard-block, then packets.set_publish_mode(). BOFU is
    checked first and independently so it stays enforced regardless of
    ALLOWED_PUBLISH_MODES_UNTIL_F6's current width — since AA-365
    (14/08/2026) that guard allows all 3 ramp states, so
    set_publish_mode() now succeeds for every `mode` already validated
    against RAMP above; its own PublishModeBlockedError path is kept as a
    defensive guard (never expected to trigger here, since `mode` is
    pre-validated), not as an active block anymore.

    Raises BofuVetoBlockedError (or, defensively, PublishModeBlockedError)
    AFTER the log entry is written, so a blocked attempt is never lost.
    Raises ValueError for an unknown packet_id or an invalid `mode`."""
    if mode not in RAMP:
        raise ValueError(f"confirm_ramp_transition: {mode!r} is not a valid ramp state {RAMP}")

    current_mode = await db.fetchval(
        "SELECT publish_mode FROM acp_deliver.packets WHERE packet_id = $1", packet_id,
    )
    if current_mode is None:
        raise ValueError(f"confirm_ramp_transition: no packet {packet_id}")

    bofu_blocked = False
    block_reason: Optional[str] = None
    if mode == "veto_window_auto" and await packet_has_bofu_piece(db, packet_id):
        bofu_blocked = True
        block_reason = "BOFU/pricing content is approval-forever, never veto_window_auto"

    f6_blocked = False
    if not bofu_blocked:
        try:
            await set_publish_mode(db, packet_id, mode)
        except PublishModeBlockedError as exc:
            f6_blocked = True
            block_reason = str(exc)

    await _log_transition(
        db, tenant_id=tenant_id, packet_id=packet_id, actor=actor,
        from_mode=current_mode, to_mode=mode,
        blocked=bofu_blocked or f6_blocked, block_reason=block_reason,
    )

    if bofu_blocked:
        raise BofuVetoBlockedError(block_reason)
    if f6_blocked:
        raise PublishModeBlockedError(block_reason)


__all__ = [
    "RAMP", "BofuVetoBlockedError",
    "packet_has_bofu_piece", "suggest_ramp_transition", "confirm_ramp_transition",
    "compute_tenant_weeks_active", "compute_tenant_engagement_ok",
    "compute_tenant_ramp_signals", "compute_ramp_suggestion",
]
