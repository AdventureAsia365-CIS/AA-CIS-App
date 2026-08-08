"""AA-330 Phần A — marketplace catalog backend (api/routers/admin_marketplace.py).

Mocks the asyncpg pool per the pool.acquire() convention established in
test_aa300_admin_atoms.py — no live DB, no LLM. Auth is exercised against the
real verify_admin_secret() imported unchanged from admin.py, same as
admin_atoms.py's own tests.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.routers import admin_marketplace

_TEST_SECRET = "test-admin-secret"

TOUR_A = str(uuid.uuid4())
TOUR_B = str(uuid.uuid4())


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


def _catalog_row(**over):
    base = {
        "tour_id": uuid.UUID(TOUR_A), "name": "Sapa Valley Trek", "destination": "Vietnam",
        "duration_raw": "4 days 3 nights", "period": "Mar-May,Sep-Nov",
        "trip_url": None, "url_alive": None,
        "total_atoms": 12, "high_atoms_count": 4, "has_image": True,
    }
    base.update(over)
    return base


class TestAuthGate:
    def test_wrong_secret_rejected(self):
        with pytest.raises(HTTPException) as exc:
            admin_marketplace.verify_admin_secret("wrong-secret")
        assert exc.value.status_code == 403

    def test_reuses_admin_verify_admin_secret(self):
        from api.routers.admin import verify_admin_secret
        assert admin_marketplace.verify_admin_secret is verify_admin_secret


class TestListCatalog:
    @pytest.mark.asyncio
    async def test_destination_filter_uses_ilike(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_marketplace.list_catalog(
            request, destination="Vietnam", duration_min=None, duration_max=None,
            period_month=None, min_atoms=None, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        query, *params = conn.fetch.call_args[0]
        assert "vtr.destination ILIKE" in query
        assert "%Vietnam%" in params

    @pytest.mark.asyncio
    async def test_min_atoms_filter_on_joined_count(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_marketplace.list_catalog(
            request, destination=None, duration_min=None, duration_max=None,
            period_month=None, min_atoms=8, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        query, *params = conn.fetch.call_args[0]
        assert "COALESCE(ac.atom_count, 0) >=" in query
        assert 8 in params

    @pytest.mark.asyncio
    async def test_duration_filter_uses_real_parser(self):
        """4 days should pass a 3-5 day window; a tour whose duration_raw is
        unparseable is excluded (parse_duration_days returns None), not
        silently kept."""
        conn = AsyncMock()
        conn.fetch.return_value = [
            _catalog_row(tour_id=uuid.UUID(TOUR_A), duration_raw="4 days"),
            _catalog_row(tour_id=uuid.UUID(TOUR_B), duration_raw="unparseable text"),
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_marketplace.list_catalog(
            request, destination=None, duration_min=3, duration_max=5,
            period_month=None, min_atoms=None, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        assert result["total"] == 1
        assert result["tours"][0]["tour_id"] == TOUR_A

    @pytest.mark.asyncio
    async def test_period_filter_uses_real_parser(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            _catalog_row(tour_id=uuid.UUID(TOUR_A), period="Mar-May"),
            _catalog_row(tour_id=uuid.UUID(TOUR_B), period="Sep-Nov"),
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_marketplace.list_catalog(
            request, destination=None, duration_min=None, duration_max=None,
            period_month=4, min_atoms=None, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        assert result["total"] == 1
        assert result["tours"][0]["tour_id"] == TOUR_A

    @pytest.mark.asyncio
    async def test_has_image_and_atom_counts_pass_through(self):
        conn = AsyncMock()
        conn.fetch.return_value = [_catalog_row()]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_marketplace.list_catalog(
            request, destination=None, duration_min=None, duration_max=None,
            period_month=None, min_atoms=None, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        tour = result["tours"][0]
        assert tour["total_atoms"] == 12
        assert tour["high_atoms_count"] == 4
        assert tour["has_image"] is True

    @pytest.mark.asyncio
    async def test_pagination_applied_after_python_filters(self):
        conn = AsyncMock()
        conn.fetch.return_value = [_catalog_row(tour_id=uuid.uuid4()) for _ in range(5)]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_marketplace.list_catalog(
            request, destination=None, duration_min=None, duration_max=None,
            period_month=None, min_atoms=None, limit=2, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        assert result["total"] == 5
        assert result["count"] == 2
        assert len(result["tours"]) == 2


class TestSavePortfolio:
    @pytest.mark.asyncio
    async def test_empty_tour_ids_rejected(self):
        conn = AsyncMock()
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin_marketplace.SavePortfolioRequest(tour_ids=[])
        with pytest.raises(HTTPException) as exc:
            await admin_marketplace.save_portfolio(body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_uuid_rejected(self):
        conn = AsyncMock()
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin_marketplace.SavePortfolioRequest(tour_ids=["not-a-uuid"])
        with pytest.raises(HTTPException) as exc:
            await admin_marketplace.save_portfolio(body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_atom_snapshot_uses_real_recomputed_count(self):
        """total_atoms must come from a fresh COUNT(*) against tour_ids, not
        from any value the client already had — a stale client-side count
        must never be trusted into the DB."""
        conn = AsyncMock()
        conn.fetchval.return_value = 27
        conn.fetchrow.return_value = {
            "portfolio_id": uuid.uuid4(), "tour_ids": [uuid.UUID(TOUR_A), uuid.UUID(TOUR_B)],
            "filters_used": '{"destination": "Vietnam"}',
            "atom_snapshot": '{"total_atoms": 27, "runway_months": null, "posts_per_week": null}',
            "status": "draft", "created_at": "2026-08-08T00:00:00", "finalized_at": None,
        }
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin_marketplace.SavePortfolioRequest(
            tour_ids=[TOUR_A, TOUR_B], filters_used={"destination": "Vietnam"},
        )
        result = await admin_marketplace.save_portfolio(body, request, x_admin_secret=_TEST_SECRET)

        count_query, count_params = conn.fetchval.call_args[0][0], conn.fetchval.call_args[0][1]
        assert "count(*)" in count_query
        assert "NOT deleted AND NOT is_empty_marker" in count_query
        assert count_params == [uuid.UUID(TOUR_A), uuid.UUID(TOUR_B)]

        insert_args = conn.fetchrow.call_args[0]
        import json
        snapshot_sent = json.loads(insert_args[3])
        assert snapshot_sent == {"total_atoms": 27, "runway_months": None, "posts_per_week": None}

        assert result["status"] == "draft"
        assert result["atom_snapshot"]["total_atoms"] == 27
        assert result["atom_snapshot"]["runway_months"] is None
        assert result["tour_ids"] == [TOUR_A, TOUR_B]

    @pytest.mark.asyncio
    async def test_insert_always_status_draft(self):
        conn = AsyncMock()
        conn.fetchval.return_value = 0
        conn.fetchrow.return_value = {
            "portfolio_id": uuid.uuid4(), "tour_ids": [uuid.UUID(TOUR_A)],
            "filters_used": "{}", "atom_snapshot": '{"total_atoms": 0, "runway_months": null, "posts_per_week": null}',
            "status": "draft", "created_at": "2026-08-08T00:00:00", "finalized_at": None,
        }
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin_marketplace.SavePortfolioRequest(tour_ids=[TOUR_A])
        await admin_marketplace.save_portfolio(body, request, x_admin_secret=_TEST_SECRET)

        insert_query = conn.fetchrow.call_args[0][0]
        assert "'draft'" in insert_query
