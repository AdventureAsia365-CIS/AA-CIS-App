"""AA-448 — T7 Content Planning router (api/routers/v1_planning.py).

Same conventions as test_aa444_marketplace_view.py: mocked asyncpg pool, `tenant=` dependency
bypassed (called directly, not through FastAPI's Depends() machinery).
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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


def _plan_side_effect(dfs_rows=None):
    """The 4 conn.fetch() calls _compute_plan()+lock-status make, in order: trips, atoms, dfs
    relevance, then acp_v2_runs (lock status)."""
    return [[_trip_row()], [_atom_row()], dfs_rows or [], []]


class TestPreviewQuarterPlan:
    @pytest.mark.asyncio
    async def test_uses_tenant_scoped_pool_not_platform_catalog(self):
        """The exact thing this router exists to guarantee: trips come from
        tenant_tour_versions (via tenant_pool.fetch_tenant_trips), not the platform-wide
        763-trip v_trip_registry."""
        conn = AsyncMock()
        conn.fetchrow.return_value = {"posts_per_week": 2, "markets": None, "channels": None}
        conn.fetch.side_effect = _plan_side_effect()
        pool = _make_pool(conn)
        request = _make_request(pool)
        body = v1_planning.QuarterPlanRequest(year=2026, quarter=4)

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
        assert result["fully_locked"] is False  # no acp_v2_runs rows, quarter is in the future

    @pytest.mark.asyncio
    async def test_config_never_client_supplied_always_read_fresh(self):
        """Self-service means the tenant's OWN configured markets/channels/capacity —
        QuarterPlanRequest has no field for any of these."""
        assert "markets" not in v1_planning.QuarterPlanRequest.model_fields
        assert "capacity_posts_per_week" not in v1_planning.QuarterPlanRequest.model_fields
        assert "channels" not in v1_planning.QuarterPlanRequest.model_fields

    @pytest.mark.asyncio
    async def test_dfs_relevance_feeds_into_plan_scoring(self):
        """A tour with a real HIGH search-volume keyword idea should surface a nonzero
        dfs_relevance_score in the returned trip_scores (not the flat MED default)."""
        conn = AsyncMock()
        conn.fetchrow.return_value = {"posts_per_week": 2, "markets": None, "channels": None}
        conn.fetch.side_effect = _plan_side_effect(dfs_rows=[{
            "tour_id": TRIP_ID,
            "keyword_ideas": json.dumps([{"keyword": "sapa trekking", "search_volume": 900}]),
        }])
        pool = _make_pool(conn)
        request = _make_request(pool)
        body = v1_planning.QuarterPlanRequest(year=2026, quarter=4)

        result = await v1_planning.preview_quarter_plan(body, request, tenant={"sub": TENANT_ID})

        score = result["plan"]["trip_scores"][0]
        assert score["dfs_relevance_score"] == 1.0  # HIGH -> SIGNAL_SCORE_MAP["HIGH"]

    @pytest.mark.asyncio
    async def test_unknown_tenant_404s_not_500s(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None  # fetch_tenant_planning_config raises TenantNotFoundError
        pool = _make_pool(conn)
        request = _make_request(pool)
        body = v1_planning.QuarterPlanRequest(year=2026, quarter=4)

        with pytest.raises(Exception) as exc_info:
            await v1_planning.preview_quarter_plan(body, request, tenant={"sub": TENANT_ID})
        assert getattr(exc_info.value, "status_code", None) == 404


class TestFinalizeQuarterPlan:
    @pytest.mark.asyncio
    async def test_refuses_when_quarter_fully_locked(self):
        """Round 6: only a FULLY locked quarter blocks finalize — simulate every one of the 12
        (month, week) slots as already 'produced' (acp_v2_runs has a row for each)."""
        conn = AsyncMock()
        produced_rows = [
            {"month": m, "week": w}
            for m in (1, 2, 3) for w in (1, 2, 3, 4)
        ]
        conn.fetch.side_effect = [produced_rows]  # only fetch_quarter_lock_status runs
        pool = _make_pool(conn)
        request = _make_request(pool)
        body = v1_planning.QuarterPlanRequest(year=2020, quarter=1)  # safely in the past too

        with pytest.raises(Exception) as exc_info:
            await v1_planning.finalize_quarter_plan(body, request, tenant={"sub": TENANT_ID})
        assert getattr(exc_info.value, "status_code", None) == 409

    @pytest.mark.asyncio
    async def test_finalize_saves_and_auto_approves(self):
        """Gate B Option A: finalize calls save_quarter_plan_version() then
        approve_quarter_plan_version() immediately — no pending/human step exposed."""
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [],                    # lock status (acp_v2_runs) — nothing locked
            [_trip_row()],         # fetch_tenant_trips
            [_atom_row()],         # fetch_tenant_atoms_by_trip
            [],                    # fetch_dfs_relevance_by_tour
        ]
        conn.fetchrow.return_value = {"posts_per_week": 2, "markets": None, "channels": None}
        conn.fetchval.side_effect = [
            None, uuid.uuid4(),                 # year_plan insert-select
            uuid.uuid4(),                        # quarter_plan plan_id
            1,                                    # next_version_no
            uuid.uuid4(),                          # quarter_plan_version insert -> version_id
        ]
        txn_ctx = AsyncMock()
        txn_ctx.__aenter__ = AsyncMock(return_value=None)
        txn_ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=txn_ctx)
        pool = _make_pool(conn)
        request = _make_request(pool)
        body = v1_planning.QuarterPlanRequest(year=2026, quarter=4)

        with patch("api.routers.v1_planning.approve_quarter_plan_version", new=AsyncMock()) as mock_approve:
            result = await v1_planning.finalize_quarter_plan(body, request, tenant={"sub": TENANT_ID})

        mock_approve.assert_awaited_once()
        assert mock_approve.await_args.kwargs["approved_by"] == f"tenant:{TENANT_ID}"
        assert "version_id" in result
        # Live-verify finding (post-deploy real HTTP): the response's own `plan.approved` must
        # already read true — a client polling the finalize response itself, not just a
        # follow-up GET, should never see a stale approved=false.
        assert result["plan"]["approved"] is True
        assert result["plan"]["approved_by"] == f"tenant:{TENANT_ID}"


class TestGetQuarterPlan:
    @pytest.mark.asyncio
    async def test_404_when_no_finalized_plan(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None  # fetch_approved_quarter_plan -> None
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        with pytest.raises(Exception) as exc_info:
            await v1_planning.get_quarter_plan(request, tenant={"sub": TENANT_ID}, year=2026, quarter=4)
        assert getattr(exc_info.value, "status_code", None) == 404


class TestAuthReusesV1ToursDependency:
    def test_get_tenant_imported_not_redefined(self):
        from api.routers.v1_tours import get_tenant

        assert v1_planning.get_tenant is get_tenant


class TestMetricsEndpoints:
    @pytest.mark.asyncio
    async def test_post_metric_unowned_piece_404s(self):
        with patch(
            "api.routers.v1_planning.record_metric_snapshot",
            new=AsyncMock(side_effect=v1_planning.PieceNotOwnedError("nope")),
        ):
            body = v1_planning.MetricSnapshotRequest(piece_id="piece_x", reach=100, engagement=10)
            request = _make_request(MagicMock())
            with pytest.raises(Exception) as exc_info:
                await v1_planning.post_metric_snapshot(body, request, tenant={"sub": TENANT_ID})
            assert getattr(exc_info.value, "status_code", None) == 404

    @pytest.mark.asyncio
    async def test_rollup_wires_through_to_service(self):
        with patch(
            "api.routers.v1_planning.rollup_atom_weights",
            new=AsyncMock(return_value={"atom_1": 1.4}),
        ):
            request = _make_request(MagicMock())
            result = await v1_planning.post_metrics_rollup(request, tenant={"sub": TENANT_ID})
            assert result == {"atoms_adjusted": 1, "weights": {"atom_1": 1.4}}


class TestTripReallocationEndpoints:
    @pytest.mark.asyncio
    async def test_suggest_wires_through_to_service(self):
        with patch(
            "api.routers.v1_planning.suggest_trip_reallocation",
            new=AsyncMock(return_value={"added": [], "removed": []}),
        ) as mock_suggest:
            request = _make_request(MagicMock())
            result = await v1_planning.get_trip_reallocation_suggestion(
                request, tenant={"sub": TENANT_ID}, year=2026, quarter=1,
            )
            mock_suggest.assert_awaited_once()
            assert result == {"added": [], "removed": []}

    @pytest.mark.asyncio
    async def test_confirm_wires_through_to_service(self):
        with patch(
            "api.routers.v1_planning.confirm_trip_reallocation",
            new=AsyncMock(return_value={"accepted": True}),
        ) as mock_confirm:
            body = v1_planning.TripReallocationConfirmRequest(year=2026, quarter=1, accept=True)
            request = _make_request(MagicMock())
            result = await v1_planning.post_trip_reallocation_confirm(
                body, request, tenant={"sub": TENANT_ID},
            )
            mock_confirm.assert_awaited_once()
            assert result == {"accepted": True}
