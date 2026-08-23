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


__all__ = ["fetch_tenant_trips", "fetch_tenant_atoms_by_trip"]
