"""
services.acp_produce.packets — AA-364: create an empty Weekly Packet shell +
the F6 revenue-safety guard on `publish_mode`.

Scope boundary (Nghiep, AA-364, 05/08/2026): `create_packet()` below only
creates the `acp_deliver.packets` row itself. Assigning real pieces to a
packet (the actual "assemble" in `assemble_packet`) needs multiple real
`Piece` rows produced across a run — that requires C3/E1-E5 generation to
exist, which it does not yet (see pipeline.py's module docstring and
docs/implementation-notes/AA-364.md STEP 0). Piece-to-packet assignment is
explicitly a later issue's scope, not invented here ahead of it.

F6 guard: Nghiep's AA-364 decision (05/08/2026) blocks `publish_mode` from
ever advancing past `'propose_only'` in code until F6 (route-to-sellable —
dead/missing CTA-URL check, services/acp_produce/gates.py) exists. A piece
can pass every gate that exists today (output_rules, F1, F8, F9) while
pointing at a dead `trip_url` — a concrete revenue defect nothing currently
catches (see docs/implementation-notes/AA-364.md "Should know"). This is a
deliberate hold, not an oversight — `set_publish_mode()` is the ONLY
function in this module (and, by convention, should stay the only call site
anywhere) that writes `acp_deliver.packets.publish_mode`, so the guard has a
single choke point.
"""
from __future__ import annotations

import asyncpg

# Nghiep AA-364 decision, 05/08/2026: do not add 'approve_to_publish' or
# 'veto_window_auto' here until F6 (route-to-sellable) exists. Do not relax
# without a new decision recorded in docs/implementation-notes/AA-364.md.
ALLOWED_PUBLISH_MODES_UNTIL_F6 = frozenset({"propose_only"})


class PublishModeBlockedError(Exception):
    """Raised when code attempts to advance publish_mode past what F6's
    absence allows. Never catch-and-ignore this — it exists to make the
    AA-364 revenue-safety hold impossible to bypass silently."""


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
    """BLOCKED until F6 (route-to-sellable) exists — AA-364 Nghiep decision
    05/08/2026. Raises PublishModeBlockedError for any `mode` outside
    ALLOWED_PUBLISH_MODES_UNTIL_F6 — today that's every mode except
    'propose_only'. Do not add a bypass parameter, an env var override, or a
    tenant-specific exception to this check; the block is revenue-safety,
    not a default that individual callers should be able to opt out of."""
    if mode not in ALLOWED_PUBLISH_MODES_UNTIL_F6:
        raise PublishModeBlockedError(
            f"publish_mode={mode!r} blocked until F6 (route-to-sellable) exists — "
            f"AA-364 Nghiep decision 05/08/2026. Only "
            f"{sorted(ALLOWED_PUBLISH_MODES_UNTIL_F6)} allowed today."
        )
    await db.execute(
        "UPDATE acp_deliver.packets SET publish_mode = $1 WHERE packet_id = $2",
        mode, packet_id,
    )


__all__ = ["ALLOWED_PUBLISH_MODES_UNTIL_F6", "PublishModeBlockedError", "create_packet", "set_publish_mode"]
