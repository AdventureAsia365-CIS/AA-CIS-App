"""
services.acp_planning.tenant_pool — AA-448, T7's tenant-scoped trip+atom source.

Per the task's explicit decision #3 (STOP-free — no approval needed, this is a direct
instruction): T7 must NOT read from the platform-wide catalog `fetch_trips()`
(`runway.py:205`, deliberately un-tenant-filtered, "every tenant shares the full catalog until
Marketplace/N1 licensing ships" — see AA-448-00 STEP0 §1) or the buggy
`fetch_atoms_by_trip()` (`quarter.py:262`, joins `raw_tours.tenant_id` instead of
`tour_atoms.owner_scope` — the bug AA-448 exists to route around). Instead T7 reads the SAME
source-of-truth as `GET /v1/marketplace` (AA-444, `api/routers/v1_marketplace.py`): a tenant's
own `gold_aa_internal.tenant_tour_versions` (latest version per tour) and their own
`acp_contract.tour_atoms` (`owner_scope = tenant_id`).

**Not a literal call to `GET /v1/marketplace`** — that endpoint returns an aggregate rollup
(atom_count/high_atom_count only) built for a browse UI; `compute_quarter_plan()`/
`compute_slot_grid()` need full `Trip`/`AtomRecord` rows (period, itinerary_source, per-atom
distinctiveness/weight/cooldown_until/usage_log, etc.) that an aggregate can't supply. This
module re-derives from the SAME two source tables/join key instead
(`tenant_tour_versions.tenant_id` for trips, `tour_atoms.owner_scope` for atoms) — if the two
queries' idea of "which tenant_tour_versions rows count as this tenant's current tours" ever
needs to change (e.g. adding a status filter), keep `v1_marketplace.py`'s `_MARKETPLACE_QUERY`
and this module's `_TENANT_TRIP_QUERY` in sync; they are intentionally NOT filtering
`ttv.status` today, matching Marketplace's own current behavior exactly (ADR-2026-038 §0.2 — no
AA-side content gate at any T0-T11 step, so an unreviewed/draft rewrite still counts as "this
tenant's tour" for planning purposes, same as Marketplace already treats it).

Atom scope is `owner_scope = tenant_id` only — NOT `owner_scope IN ('platform', tenant_id)`.
This matches `v1_marketplace.py`'s own atom aggregate exactly (its `ac` subquery: `WHERE
owner_scope = $2`), which is the precedent this task explicitly told T7 to follow. AA-440's
`fetch_atoms_by_trip()` bug writeup floated `IN ('platform', tenant_id)` as a *possible* fix
shape for the OLD function, but that was never actually decided/built anywhere (confirmed: AA-444
did not adopt it for Marketplace) — T7 follows the real, already-shipped precedent instead of
that unbuilt speculative alternative.

Reuses `_row_to_trip`/`_row_to_atom` (runway.py/quarter.py's own row-shape parsers, incl.
`_parse_jsonb`'s asyncpg-has-no-jsonb-codec workaround) unchanged — these two new queries return
the exact same column names/types those parsers already expect, so there is no reason to
duplicate that mapping logic.
"""
from __future__ import annotations

from datetime import date
from typing import NamedTuple
from uuid import UUID

from .models import AtomRecord, Trip
from .quarter import _row_to_atom
from .runway import _row_to_trip

_TENANT_TRIP_QUERY = """
    WITH latest_versions AS (
        SELECT DISTINCT ON (ttv.published_tour_id) ttv.published_tour_id
        FROM gold_aa_internal.tenant_tour_versions ttv
        WHERE ttv.tenant_id = $1::uuid
        ORDER BY ttv.published_tour_id, ttv.version_number DESC
    )
    SELECT
        rt.tour_id AS id, pt.aa_name AS name, rt.country AS destination,
        rt.period AS period, rt.duration AS duration_raw, rt.src_itineraries AS itinerary_source,
        rt.lifecycle_stage AS lifecycle_stage, ttp.url AS trip_url, ttp.url_alive AS url_alive
    FROM latest_versions lv
    JOIN gold_aa_internal.published_tours pt ON pt.id = lv.published_tour_id
    JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
    LEFT JOIN acp_deliver.tenant_tour_pages ttp ON ttp.tour_id = rt.tour_id
"""

_TENANT_ATOM_QUERY = """
    SELECT atom_id, tour_id, text, activity_type, distinctiveness, starred,
           deleted, weight, cooldown_until, usage_log
    FROM acp_contract.tour_atoms
    WHERE owner_scope = $1 AND NOT deleted AND NOT is_empty_marker
"""

# AA-494 Decision 6 — the atom-availability rule, worded exactly per
# docs/claude_tasks/AA-494-design-atom-angle-piece-reuse.md ("Atom-availability rule for the
# month"): an atom is "used" (locked) for calendar month X if it has at least one content_piece
# with status='approved' (the only status meaning "passed T10" — content_piece.status's real
# value set as of migration 118 is processing/approved/held/failed, confirmed live 29/08/2026;
# there is no ordinal "beyond approved" state to compare against, so the design doc's "at or
# beyond approved" collapses to exactly status='approved') whose created_at (actual write date,
# NOT the slot's pre-assigned plan month) falls within month X. A piece that never reaches
# approved (held/failed, or still processing) does NOT lock the atom.
#
# Joins through angle_gate_request for atom_id/tenant_id/channel — content_piece itself has no
# atom_id column (by design, migration 115's own header: a child table doesn't copy its parent's
# fields). Reads angle_gate_request.channel (not content_piece.channel, which migration 124 added
# but does not yet populate) since channel is still chosen at request-creation time as of this
# migration — see migration 124's header for why the write-time-channel move is deferred.
_USED_ATOMS_QUERY = """
    SELECT agr.atom_id, MIN(cp.created_at) AS used_at,
           (ARRAY_AGG(agr.channel ORDER BY cp.created_at))[1] AS channel,
           (ARRAY_AGG(cp.angle_gate_request_id::text ORDER BY cp.created_at DESC))[1] AS request_id
    FROM acp_shared.content_piece cp
    JOIN acp_shared.angle_gate_request agr ON agr.request_id = cp.angle_gate_request_id
    WHERE agr.tenant_id = $1 AND cp.status = 'approved'
      AND cp.created_at >= $2 AND cp.created_at < $3
    GROUP BY agr.atom_id
"""


class UsedAtom(NamedTuple):
    """One atom locked for a given month — `used_at` is the real write date (the atom's earliest
    approved content_piece in that month), `channel` is the channel of that earliest piece
    (best-effort provenance for the T7 slot-view's "already written" display, not itself part of
    the availability rule).

    AA-497 — `request_id` is the LATEST approved piece's angle_gate_request_id (not the earliest,
    unlike `used_at`/`channel` above), so the T7 slot-view's "Change angle" action reopens
    whichever request most recently produced a real, approved piece for this atom — the one a
    tenant editing this slot actually means. Edge case, not solved here: nothing in this codebase
    prevents create_request() from opening a genuinely SEPARATE request for the same (atom_id,
    channel) pair (no uniqueness check ever existed) — if that ever happens, this picks the most
    recently-written request among possibly-several, which is the best available default without
    a broader "which request owns this atom+channel" model change (out of AA-497's scope)."""
    used_at: str
    channel: str
    request_id: str


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


async def fetch_tenant_trips(tenant_id: UUID, pool) -> list[Trip]:
    """Replaces `runway.fetch_trips()` for T7 — one tenant's own rewritten tours only (via
    `tenant_tour_versions`), not the platform-wide 763-trip catalog."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(_TENANT_TRIP_QUERY, tenant_id)
    return [_row_to_trip(r) for r in rows]


async def fetch_tenant_atoms_by_trip(tenant_id: UUID, pool) -> dict[UUID, list[AtomRecord]]:
    """Replaces `quarter.fetch_atoms_by_trip()` for T7 — `owner_scope = tenant_id`, not the
    buggy `raw_tours.tenant_id` join. `tenant_id` is passed as a plain str/UUID positional
    param (matches `tour_atoms.owner_scope`'s column type — free-text per ADR-2026-038 Hướng B,
    not a UUID FK — asyncpg will stringify a UUID param automatically for a text column)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(_TENANT_ATOM_QUERY, str(tenant_id))
    by_trip: dict[UUID, list[AtomRecord]] = {}
    for r in rows:
        atom = _row_to_atom(r)
        by_trip.setdefault(atom.trip_id, []).append(atom)
    return by_trip


async def fetch_used_atom_ids(tenant_id: UUID, year: int, month: int, pool) -> dict[str, UsedAtom]:
    """AA-494 Decision 6 — the atom-availability rule. Returns every atom_id "used" (locked) for
    calendar month `year`-`month`, keyed to its real write date + channel (see `_USED_ATOMS_QUERY`
    above for the exact rule). Callers (T7's slot-view, T8's free-atom picker) treat any atom_id
    NOT in this dict's keys as free for the month."""
    start, end = _month_bounds(year, month)
    async with pool.acquire() as conn:
        rows = await conn.fetch(_USED_ATOMS_QUERY, tenant_id, start, end)
    return {
        r["atom_id"]: UsedAtom(used_at=r["used_at"].isoformat(), channel=r["channel"], request_id=r["request_id"])
        for r in rows
    }


__all__ = ["fetch_tenant_trips", "fetch_tenant_atoms_by_trip", "fetch_used_atom_ids", "UsedAtom"]
