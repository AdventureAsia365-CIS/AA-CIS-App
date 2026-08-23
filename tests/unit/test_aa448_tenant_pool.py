"""AA-448 — tenant_pool.py: T7's tenant-scoped trip+atom fetch (replaces fetch_trips()/
fetch_atoms_by_trip() for T7's own code path only — those two functions are UNTOUCHED and still
used by admin_atoms.py's preview-slotgrid + admin_produce.py's /run trigger, confirmed by grep
before this task started, see docs/implementation-notes/AA-448-t7-content-planning.md Decision
1).

DB-backed — tested with a mocked asyncpg pool, same pool.acquire() convention as
test_aa301_quarter.py/test_aa299_atom_insert.py.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.acp_planning.tenant_pool import fetch_tenant_atoms_by_trip, fetch_tenant_trips

TENANT = uuid.uuid4()


def _mock_pool(rows):
    conn = AsyncMock()
    conn.fetch.return_value = rows
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


class TestFetchTenantTrips:
    @pytest.mark.asyncio
    async def test_query_scoped_by_tenant_id_param(self):
        """Confirms the query is called with tenant_id (not the platform-wide, unfiltered
        fetch_trips() shape) — the exact behavior this module exists to guarantee."""
        trip_id = uuid.uuid4()
        pool, conn = _mock_pool([{
            "id": trip_id, "name": "Sapa Trek", "destination": "Vietnam",
            "period": "Mar-May", "duration_raw": "4 days", "itinerary_source": "day 1...",
            "lifecycle_stage": "active", "trip_url": None, "url_alive": None,
        }])

        trips = await fetch_tenant_trips(TENANT, pool)

        conn.fetch.assert_awaited_once()
        call_args = conn.fetch.await_args.args
        assert call_args[1] == TENANT  # query, tenant_id
        assert len(trips) == 1
        assert trips[0].id == trip_id
        assert trips[0].name == "Sapa Trek"

    @pytest.mark.asyncio
    async def test_no_tours_for_tenant_returns_empty_list(self):
        pool, _ = _mock_pool([])
        trips = await fetch_tenant_trips(TENANT, pool)
        assert trips == []

    @pytest.mark.asyncio
    async def test_null_lifecycle_stage_defaults_active_same_as_row_to_trip(self):
        """Reuses runway.py's own _row_to_trip() unchanged — confirms that reuse actually
        applies its `or "active"` fallback, not a divergent copy."""
        trip_id = uuid.uuid4()
        pool, _ = _mock_pool([{
            "id": trip_id, "name": "T", "destination": "D", "period": None,
            "duration_raw": None, "itinerary_source": None, "lifecycle_stage": None,
            "trip_url": None, "url_alive": None,
        }])
        trips = await fetch_tenant_trips(TENANT, pool)
        assert trips[0].lifecycle_stage == "active"


class TestFetchTenantAtomsByTrip:
    @pytest.mark.asyncio
    async def test_query_scoped_by_owner_scope_str_tenant_id(self):
        """The one thing this module exists to fix vs. the old fetch_atoms_by_trip(): the query
        param passed must be the OWNER_SCOPE value (str(tenant_id)), not raw_tours.tenant_id."""
        trip_id = uuid.uuid4()
        pool, conn = _mock_pool([{
            "atom_id": "atom_1", "tour_id": trip_id, "text": "text", "activity_type": "trek",
            "distinctiveness": "HIGH", "starred": False, "deleted": False, "weight": 1.0,
            "cooldown_until": "{}", "usage_log": "[]",
        }])

        by_trip = await fetch_tenant_atoms_by_trip(TENANT, pool)

        conn.fetch.assert_awaited_once()
        call_args = conn.fetch.await_args.args
        assert call_args[1] == str(TENANT)  # query, owner_scope (text column -> str)
        assert trip_id in by_trip
        assert by_trip[trip_id][0].distinctiveness == "HIGH"

    @pytest.mark.asyncio
    async def test_jsonb_string_shape_parsed_via_reused_row_to_atom(self):
        """Reuses quarter.py's own _row_to_atom()/_parse_jsonb() unchanged (asyncpg-has-no-
        jsonb-codec workaround) — confirms cooldown_until/usage_log arriving as raw JSON
        strings still parse correctly through this new query path."""
        trip_id = uuid.uuid4()
        pool, _ = _mock_pool([{
            "atom_id": "atom_1", "tour_id": trip_id, "text": "text", "activity_type": None,
            "distinctiveness": "MED", "starred": True, "deleted": False, "weight": 1.5,
            "cooldown_until": '{"blog": "2026-09-01"}', "usage_log": "[]",
        }])
        by_trip = await fetch_tenant_atoms_by_trip(TENANT, pool)
        atom = by_trip[trip_id][0]
        assert atom.cooldown_until == {"blog": "2026-09-01"}
        assert atom.usage_log == []

    @pytest.mark.asyncio
    async def test_no_atoms_for_tenant_returns_empty_dict(self):
        pool, _ = _mock_pool([])
        by_trip = await fetch_tenant_atoms_by_trip(TENANT, pool)
        assert by_trip == {}
