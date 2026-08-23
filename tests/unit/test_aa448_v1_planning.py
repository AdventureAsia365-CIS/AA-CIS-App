"""AA-448 — T7 Content Planning router (api/routers/v1_planning.py), preview endpoint only
(the finalize/read/slot-grid endpoints are added once the Gate B replacement decision is made —
see docs/implementation-notes/AA-448-t7-content-planning.md).

Same conventions as test_aa444_marketplace_view.py: mocked asyncpg pool, `tenant=` dependency
bypassed (called directly, not through FastAPI's Depends() machinery).
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.routers import v1_planning

TENANT_ID = str(uuid.uuid4())
TRIP_ID = uuid.uuid4()


def _make_pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _make_request(pool):
    request = MagicMock()
    request.app.state.pool = pool
    return request


def _trip_row(**over):
    base = {
        "id": TRIP_ID, "name": "Sapa Trek", "destination": "Vietnam",
        "period": "Mar-May", "duration_raw": "4 days", "itinerary_source": "day 1: arrive...",
        "lifecycle_stage": "active", "trip_url": None, "url_alive": None,
    }
    base.update(over)
    return base


def _atom_row(**over):
    base = {
        "atom_id": "atom_1", "tour_id": TRIP_ID, "text": "Cross the bamboo bridge at dawn",
        "activity_type": "trek", "distinctiveness": "HIGH", "starred": False, "deleted": False,
        "weight": 1.0, "cooldown_until": "{}", "usage_log": "[]",
    }
    base.update(over)
    return base


class TestPreviewQuarterPlan:
    @pytest.mark.asyncio
    async def test_uses_tenant_scoped_pool_not_platform_catalog(self):
        """The exact thing this router exists to guarantee: trips come from
        tenant_tour_versions (via tenant_pool.fetch_tenant_trips), not the platform-wide
        763-trip v_trip_registry."""
        conn = AsyncMock()
        conn.fetchrow.return_value = {"posts_per_week": 2, "markets": None, "channels": None}
        conn.fetch.side_effect = [
            [_trip_row()],       # fetch_tenant_trips
            [_atom_row()],       # fetch_tenant_atoms_by_trip
            [],                  # fetch_dfs_relevance_by_tour
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)
        body = v1_planning.QuarterPlanPreviewRequest(year=2026, quarter=4)

        result = await v1_planning.preview_quarter_plan(body, request, tenant={"sub": TENANT_ID})

        trips_query, trips_tenant_param = conn.fetch.call_args_list[0][0]
        assert "tenant_tour_versions" in trips_query
        assert "v_trip_registry" not in trips_query
        assert str(trips_tenant_param) == TENANT_ID

        atoms_query, atoms_owner_scope_param = conn.fetch.call_args_list[1][0]
        assert "owner_scope = $1" in atoms_query
        assert atoms_owner_scope_param == TENANT_ID

        assert result["trip_pool_size"] == 1
        assert len(result["plan"]["trip_scores"]) == 1
        assert result["plan"]["trip_scores"][0]["trip_id"] == str(TRIP_ID)

    @pytest.mark.asyncio
    async def test_config_never_client_supplied_always_read_fresh(self):
        """Self-service means the tenant's OWN configured markets/channels/capacity —
        QuarterPlanPreviewRequest has no field for any of these."""
        assert "markets" not in v1_planning.QuarterPlanPreviewRequest.model_fields
        assert "capacity_posts_per_week" not in v1_planning.QuarterPlanPreviewRequest.model_fields
        assert "channels" not in v1_planning.QuarterPlanPreviewRequest.model_fields

    @pytest.mark.asyncio
    async def test_dfs_relevance_feeds_into_plan_scoring(self):
        """A tour with a real HIGH search-volume keyword idea should surface a nonzero
        dfs_relevance_score in the returned trip_scores (not the flat MED default)."""
        conn = AsyncMock()
        conn.fetchrow.return_value = {"posts_per_week": 2, "markets": None, "channels": None}
        conn.fetch.side_effect = [
            [_trip_row()],
            [_atom_row()],
            [{"tour_id": TRIP_ID, "keyword_ideas": json.dumps(
                [{"keyword": "sapa trekking", "search_volume": 900}])}],
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)
        body = v1_planning.QuarterPlanPreviewRequest(year=2026, quarter=4)

        result = await v1_planning.preview_quarter_plan(body, request, tenant={"sub": TENANT_ID})

        score = result["plan"]["trip_scores"][0]
        assert score["dfs_relevance_score"] == 1.0  # HIGH -> SIGNAL_SCORE_MAP["HIGH"]

    @pytest.mark.asyncio
    async def test_unknown_tenant_404s_not_500s(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None  # fetch_tenant_planning_config raises TenantNotFoundError
        pool = _make_pool(conn)
        request = _make_request(pool)
        body = v1_planning.QuarterPlanPreviewRequest(year=2026, quarter=4)

        with pytest.raises(Exception) as exc_info:
            await v1_planning.preview_quarter_plan(body, request, tenant={"sub": TENANT_ID})
        assert getattr(exc_info.value, "status_code", None) == 404


class TestAuthReusesV1ToursDependency:
    def test_get_tenant_imported_not_redefined(self):
        from api.routers.v1_tours import get_tenant

        assert v1_planning.get_tenant is get_tenant
