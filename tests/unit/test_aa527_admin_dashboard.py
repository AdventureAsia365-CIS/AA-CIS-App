"""AA-527 (bổ sung, Phương án C dashboard) — api/routers/admin_dashboard.py.

The 4 new audit-only endpoints (Segment/Score/Route-Hub/Slate) backing the T5-T11 dashboard's
sections 02-05. Sections 06-08 (Write-Gate/Review/Publish) reuse admin_a4.py's existing
content-log/publish-log endpoints (this same task added an optional `tour_id` filter there,
covered separately at the bottom of this file) rather than new endpoints.

Mocks the asyncpg pool — no live DB. Same x-admin-secret convention/helpers as
test_aa300_admin_atoms.py (monkeypatch api.routers.admin.ADMIN_SECRET, a real fake pool/request).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.routers import admin_a4, admin_dashboard

_TEST_SECRET = "test-admin-secret"


@pytest.fixture(autouse=True)
def _admin_secret(monkeypatch):
    monkeypatch.setattr("api.routers.admin.ADMIN_SECRET", _TEST_SECRET)


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


class TestListSegments:
    @pytest.mark.asyncio
    async def test_returns_segment_rows_scoped_to_tour(self):
        tour_id = str(uuid.uuid4())
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"segment_id": "seg1", "canonical_place": "Sigiriya", "canonical_action": "climb",
             "tenant_id": uuid.uuid4(), "tenant_name": "WanderLux", "member_count": 3,
             "total_rank": 2, "recurrence": 5, "excluded_reason": None,
             "route_id": "r1", "route_hub_name": "Cultural Triangle"},
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_dashboard.list_segments(request, tour_id=tour_id, x_admin_secret=_TEST_SECRET)

        assert result["total"] == 1
        assert result["data"][0]["canonical_place"] == "Sigiriya"
        query, *params = conn.fetch.call_args[0]
        assert "ta.tour_id = $1::uuid" in query
        assert tour_id in params

    @pytest.mark.asyncio
    async def test_empty_when_no_segments(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_dashboard.list_segments(request, tour_id=str(uuid.uuid4()), x_admin_secret=_TEST_SECRET)
        assert result["total"] == 0
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_wrong_admin_secret_rejected(self):
        from fastapi import HTTPException
        conn = AsyncMock()
        pool = _make_pool(conn)
        request = _make_request(pool)
        with pytest.raises(HTTPException) as exc:
            await admin_dashboard.list_segments(request, tour_id=str(uuid.uuid4()), x_admin_secret="wrong")
        assert exc.value.status_code == 403


class TestListScore:
    @pytest.mark.asyncio
    async def test_returns_ranking_rows(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"tenant_id": uuid.uuid4(), "tenant_name": "WanderLux", "segment_id": "seg1",
             "canonical_place": "Sigiriya", "canonical_action": "climb",
             "demand_rank": 1, "recurrence_rank": 2, "questions_rank": 3, "said_rank": 4,
             "total_rank": 10, "demand_market": "US", "demand_volume": 1300,
             "recurrence": 5, "questions": 12, "said": 3, "excluded_reason": None,
             "computed_at": "2026-09-01T00:00:00"},
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_dashboard.list_score(request, tour_id=str(uuid.uuid4()), x_admin_secret=_TEST_SECRET)
        assert result["total"] == 1
        assert result["data"][0]["total_rank"] == 10


class TestListRoutes:
    @pytest.mark.asyncio
    async def test_returns_routes_and_hub_backlog_flag(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"route_id": "r1", "tenant_id": uuid.uuid4(), "tenant_name": "WanderLux",
             "hub_id": None, "hub_name": "Cultural Triangle", "ordered_segment_ids": '["seg1", "seg2"]',
             "first_day": 1, "last_day": 3, "score": 5, "created_at": "2026-09-01T00:00:00",
             "version": 1, "superseded_at": None},
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_dashboard.list_routes(request, tour_id=str(uuid.uuid4()), x_admin_secret=_TEST_SECRET)
        assert result["total"] == 1
        assert result["hub_grouping_backlog"] is True
        # ordered_segment_ids comes back as a raw JSON string (no jsonb codec, same gap
        # admin_atoms.py's media handling already found) — _safe() must parse it.
        assert result["data"][0]["ordered_segment_ids"] == ["seg1", "seg2"]

    @pytest.mark.asyncio
    async def test_does_not_filter_superseded_rows_this_is_the_audit_view(self):
        """AA-532 — every OTHER reader of acp_contract.route filters `superseded_at IS NULL`;
        this admin audit panel deliberately does not, since showing version history is the point."""
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"route_id": "r1", "tenant_id": uuid.uuid4(), "tenant_name": "WanderLux",
             "hub_id": None, "hub_name": "Cultural Triangle", "ordered_segment_ids": '["seg1"]',
             "first_day": 1, "last_day": 3, "score": 5, "created_at": "2026-09-01T00:00:00",
             "version": 1, "superseded_at": "2026-09-02T00:00:00"},
            {"route_id": "r1:v2", "tenant_id": uuid.uuid4(), "tenant_name": "WanderLux",
             "hub_id": None, "hub_name": "Cultural Triangle", "ordered_segment_ids": '["seg1", "seg2"]',
             "first_day": 1, "last_day": 3, "score": 4, "created_at": "2026-09-02T00:00:00",
             "version": 2, "superseded_at": None},
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_dashboard.list_routes(request, tour_id=str(uuid.uuid4()), x_admin_secret=_TEST_SECRET)
        assert result["total"] == 2
        query, *_params = conn.fetch.call_args[0]
        assert "superseded_at" not in query.split("WHERE")[1].split("ORDER BY")[0]


class TestListSlate:
    @pytest.mark.asyncio
    async def test_returns_subjects_and_state_breakdown(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"subject_id": uuid.uuid4(), "tenant_id": uuid.uuid4(), "tenant_name": "WanderLux",
             "channel": "instagram", "state": "picked", "score": 12.5,
             "segment_id": "seg1", "route_id": None, "cleared_bar_reason": '{"needs_demand": true}',
             "created_at": "2026-09-01T00:00:00"},
            {"subject_id": uuid.uuid4(), "tenant_id": uuid.uuid4(), "tenant_name": "WanderLux",
             "channel": "blog", "state": "cut", "score": None,
             "segment_id": None, "route_id": "r1", "cleared_bar_reason": '{}',
             "created_at": "2026-09-01T00:00:00"},
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_dashboard.list_slate(request, tour_id=str(uuid.uuid4()), x_admin_secret=_TEST_SECRET)
        assert result["total"] == 2
        assert result["by_state"]["picked"] == 1
        assert result["by_state"]["cut"] == 1
        assert result["by_state"]["proposed"] == 0


class TestContentLogPublishLogTourFilter:
    """AA-527 (bổ sung) — the tour_id filter added to admin_a4.py's pre-existing endpoints."""

    @pytest.mark.asyncio
    async def test_content_log_tour_id_filters_on_trip_id(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)
        tour_id = str(uuid.uuid4())

        await admin_a4.get_content_log(request, tenant_id=None, tour_id=tour_id, limit=200, x_admin_secret=_TEST_SECRET)

        query, *params = conn.fetch.call_args[0]
        assert "agr.trip_id = $1::uuid" in query
        assert tour_id in params

    @pytest.mark.asyncio
    async def test_publish_log_tour_id_joins_through_content_piece(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)
        tour_id = str(uuid.uuid4())

        await admin_a4.get_publish_log(request, tenant_id=None, tour_id=tour_id, limit=200, x_admin_secret=_TEST_SECRET)

        query, *params = conn.fetch.call_args[0]
        assert "JOIN acp_shared.content_piece cp ON cp.piece_id = pl.piece_id" in query
        assert "agr.trip_id = $1::uuid" in query
        assert tour_id in params

    @pytest.mark.asyncio
    async def test_publish_log_without_tour_id_has_no_join(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_a4.get_publish_log(request, tenant_id=None, tour_id=None, limit=200, x_admin_secret=_TEST_SECRET)

        query, *_params = conn.fetch.call_args[0]
        assert "JOIN acp_shared.content_piece" not in query
