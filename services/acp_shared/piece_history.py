"""
services.acp_shared.piece_history — AA-498 (AA-494 Decision 4).

When T8 generates fresh angles for an atom that already has real written history (this atom was
rewritten before — attempt 2+ across separate `angle_gate_request` rows, not the in-flow
attempt-1/attempt-2 retry `content_piece.attempt_number` already covers), the angle-gen prompt
should know what angle/channel/summary those prior pieces already used, so the LLM can pick a
genuinely different angle instead of converging on the same one again.

STEP0 (AA-520 audit, confirmed no new investigation needed — see this issue's own Linear
description): `content_piece.content_summary`/`content_embedding` (migration 124) and
`content_piece.angle_gate_option_id` (populated live since AA-497) already exist; this module is
the first code anywhere that reads `content_summary`.

Join path: `content_piece.angle_gate_request_id` (always present, unlike the nullable
`angle_gate_option_id`) -> `angle_gate_request.atom_id`/`tenant_id` scopes "same atom, same
tenant"; a LEFT JOIN to `angle_gate_option` via the piece's own `angle_gate_option_id` recovers
the angle name for pieces written after AA-497 (NULL for older rows — a piece with no
`content_summary` is filtered out anyway, see the query's own WHERE clause, so this only matters
for rows written after both AA-497 AND this issue, which is the only case that can have a
non-NULL summary in the first place).

Post-AA-475, `atom_id` already implies one tenant (`owner_scope=tenant_id`) — `tenant_id` is
still an explicit WHERE-clause parameter anyway, matching `_fetch_atom_for_tenant()`'s own
"never trust atom_id alone" convention elsewhere in this codebase, not because a cross-tenant
leak is otherwise reachable here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

_PIECE_HISTORY_QUERY = """
    SELECT cp.content_summary, COALESCE(cp.channel, agr.channel) AS channel,
           ago.name AS angle_name, cp.created_at
    FROM acp_shared.content_piece cp
    JOIN acp_shared.angle_gate_request agr ON cp.angle_gate_request_id = agr.request_id
    LEFT JOIN acp_shared.angle_gate_option ago ON cp.angle_gate_option_id = ago.option_id
    WHERE agr.tenant_id = $1 AND agr.atom_id = $2
      AND cp.content_summary IS NOT NULL AND cp.content_summary != ''
      AND ($3::uuid IS NULL OR agr.request_id != $3)
    ORDER BY cp.created_at DESC
    LIMIT 5
"""
# LIMIT 5 — a prompt-size guard, same rationale as generate.py::_MAX_TOKENS's own "sized
# generously with real margin, not tuned per channel" comment; an atom realistically gets
# rewritten a handful of times, not dozens, before this needs revisiting with real usage data.


@dataclass(frozen=True)
class PriorPiece:
    channel: Optional[str]
    angle_name: Optional[str]
    summary: str


async def fetch_piece_history(
    tenant_id: UUID, atom_id: str, pool, *, exclude_request_id: Optional[UUID] = None,
) -> list[PriorPiece]:
    """Real prior pieces for this exact atom (same tenant), most recent first, capped at 5.
    Empty list is the common case today (this is the first code that ever populates
    `content_summary` — see this module's own header) and is NOT an error; the caller
    (services.acp_angle_gate.service) omits the prompt block entirely when this is empty, same
    "no signal -> no prompt noise" precedent `search_demand` already set (AA-469 Việc 4)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _PIECE_HISTORY_QUERY, tenant_id, atom_id,
            str(exclude_request_id) if exclude_request_id else None,
        )
    return [
        PriorPiece(channel=r["channel"], angle_name=r["angle_name"], summary=r["content_summary"])
        for r in rows
    ]


__all__ = ["PriorPiece", "fetch_piece_history"]
