"""
services.acp_shared.content_metrics — AA-448 round 6: manual engagement entry + atom-weight
rollup ("the feedback loop").

Explicitly a NEW extension beyond aa-marketing-v2's own Module H (`aamc/learning.py`) — not a
restoration of the original design (same framing this repo already uses for T8 §0.5's "formula
fit", per Nghiep's own instruction). What IS ported verbatim from the reference: the confidence
gate itself (`CONFIDENCE_ATOM_MIN_POSTS = 3`, constants.py) and the `[0.25, 2.0]` magnitude cap
on `tour_atoms.weight` — that part of `rollup_atoms()`'s shape genuinely is the original design.
Everything else here is new:

- The per-post SCORING FORMULA. `aamc`'s `rollup_atoms()` averaged a `capture_rate`/
  `engaged_time` value that has no equivalent field anywhere in this app (travel content, not
  the reference's own domain fields) — this module uses a plain engagement RATE
  (`engagement / reach`) instead, centered on a self-chosen, uncalibrated baseline
  (`ENGAGEMENT_RATE_BASELINE`, constants.py).
- The manual-entry endpoint/table itself. `aamc`'s own H1 (`ingest_metrics`) was always a stub
  — "connector surface... metric snapshots can also be entered manually for now," never a real
  Search Console/Meta integration in the reference build either. This module builds exactly
  that "manual entry" starting point (matching the reference's own precedent), since neither
  this repo nor the reference ever had a live connector, and T11 (Publish) still doesn't exist
  to auto-publish anything a connector could even read back from.
- `rollup_atoms()` in `aamc` never fed back into `QuarterPlan`/trip selection at all — only
  future month allocation (N6). This module's weight write IS still consumed the same way by
  N6's existing `_eligible_atoms()` (unchanged), but ALSO now by N5's `compute_quarter_plan()`
  5th scoring term (`engagement_adjustment`, quarter.py) — a genuinely new consumer the
  reference never had.

Piece -> atom join: `acp_deliver.pieces.slot_id` -> `acp_shared.acp_v2_slots.payload->'atom_ids'`
— the same live join `services/acp_produce/trust_ramp.py::packet_has_bofu_piece()` already uses
for a different field (`funnel_stage`) off the same `payload` jsonb, not a new join pattern.
"""
from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

from services.acp_planning.constants import (ATOM_WEIGHT_MAX, ATOM_WEIGHT_MIN,
                                             CONFIDENCE_ATOM_MIN_POSTS, ENGAGEMENT_RATE_BASELINE)


class PieceNotOwnedError(Exception):
    """Raised by record_metric_snapshot() when piece_id exists but belongs to a different
    tenant — never silently accept a metric against content that isn't this tenant's own."""


class PieceNotFoundError(Exception):
    """Raised by record_metric_snapshot() when piece_id does not exist at all."""


async def record_metric_snapshot(
    tenant_id: UUID, piece_id: str, reach: Optional[int], engagement: Optional[int],
    clicks: Optional[int], entered_by: str, pool,
) -> UUID:
    """Manual entry — the human who posted this piece somewhere themselves (T11/auto-publish
    doesn't exist yet) types back what they observed. Ownership-checked: piece_id must belong
    to `tenant_id`'s own `acp_deliver.pieces` row, same "never trust a client-supplied id
    without an ownership check" convention `admin_atoms.py`'s owner_scope filtering already
    established (AA-431)."""
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "SELECT tenant_id FROM acp_deliver.pieces WHERE piece_id = $1", piece_id,
        )
        if owner is None:
            raise PieceNotFoundError(f"No piece {piece_id!r}")
        if owner != str(tenant_id):
            raise PieceNotOwnedError(f"Piece {piece_id!r} does not belong to tenant {tenant_id}")

        snapshot_id = await conn.fetchval(
            """
            INSERT INTO acp_shared.content_metric_snapshot
                (tenant_id, piece_id, reach, engagement, clicks, entered_by)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING snapshot_id
            """,
            tenant_id, piece_id, reach, engagement, clicks, entered_by,
        )
    return snapshot_id


def _piece_score(reach: Optional[int], engagement: Optional[int]) -> Optional[float]:
    """Pure. None when reach is missing/zero — "unknown" stays unknown, never guessed as 0 or
    inflated by dividing engagement by a fake reach of 1 (same "never fabricate" law
    aa-marketing-v2's own README states as a system-wide commitment)."""
    if not reach:
        return None
    return (engagement or 0) / reach


def _weight_from_scores(scores: list[float]) -> float:
    """Pure. Magnitude-capped exactly like aamc's own rollup_atoms() bound
    (ATOM_WEIGHT_MIN/MAX = 0.25/2.0). Centers on ENGAGEMENT_RATE_BASELINE — a post scoring
    exactly at baseline leaves the atom's weight at 1.0 (neutral); above/below nudges it up/down."""
    avg = sum(scores) / len(scores)
    return max(ATOM_WEIGHT_MIN, min(ATOM_WEIGHT_MAX, 1.0 + (avg - ENGAGEMENT_RATE_BASELINE)))


_METRICS_JOIN_QUERY = """
    WITH latest_snapshot AS (
        SELECT DISTINCT ON (piece_id) piece_id, reach, engagement
        FROM acp_shared.content_metric_snapshot
        WHERE tenant_id = $1::uuid
        ORDER BY piece_id, entered_at DESC
    )
    SELECT p.piece_id, s.payload->'atom_ids' AS atom_ids_json, ls.reach, ls.engagement
    FROM acp_deliver.pieces p
    JOIN acp_shared.acp_v2_slots s ON s.slot_id = p.slot_id
    JOIN latest_snapshot ls ON ls.piece_id = p.piece_id
    WHERE p.tenant_id = $2
"""


def _parse_atom_ids(value) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value) if value else []
    return list(value or [])


async def rollup_atom_weights(
    tenant_id: UUID, pool, min_posts: int = CONFIDENCE_ATOM_MIN_POSTS,
) -> dict[str, float]:
    """DB-wiring: reads every piece this tenant has a manually-entered metric for (latest
    snapshot per piece, confidence-gated at `min_posts` DISTINCT PIECES per atom — matching
    aamc's own "posts", not snapshots, since a single piece can be re-measured over time and
    should only count once per atom it used), recomputes `tour_atoms.weight` for atoms that
    clear the gate, writes it, and returns {atom_id: new_weight} for whichever atoms actually
    moved. Atoms below the gate are left untouched (aamc's own "below threshold: log the
    observation, don't act")."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(_METRICS_JOIN_QUERY, str(tenant_id), str(tenant_id))

    scores_by_atom: dict[str, list[float]] = {}
    for r in rows:
        score = _piece_score(r["reach"], r["engagement"])
        if score is None:
            continue
        for atom_id in _parse_atom_ids(r["atom_ids_json"]):
            scores_by_atom.setdefault(atom_id, []).append(score)

    moved: dict[str, float] = {}
    async with pool.acquire() as conn:
        for atom_id, scores in scores_by_atom.items():
            if len(scores) < min_posts:
                continue
            new_weight = round(_weight_from_scores(scores), 3)
            await conn.execute(
                "UPDATE acp_contract.tour_atoms SET weight = $1 WHERE atom_id = $2 AND owner_scope = $3",
                new_weight, atom_id, str(tenant_id),
            )
            moved[atom_id] = new_weight
    return moved


__all__ = [
    "PieceNotFoundError", "PieceNotOwnedError",
    "record_metric_snapshot", "rollup_atom_weights",
]
