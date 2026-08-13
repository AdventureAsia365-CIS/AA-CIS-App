"""AA-345 — tour-selection UI backend (GET /admin/tours WHERE fix +
GET /admin/tours-for-atomization).

Mocks the asyncpg pool per the pool.acquire() convention established in
test_aa299_atom_insert.py / test_aa300_admin_atoms.py — no live DB. Verifies
the WHERE clause text (NULL-safety) and the new endpoint's response shape by
inspecting conn.fetch.call_args, same style as test_aa300_admin_atoms.py.
Does NOT test N2 decompose itself (verified live against real Bedrock, AA-345
STEP 0 Phần 4, 20/20 tours succeeded) — only that the UI-facing endpoints
query and shape data correctly.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.routers import admin_pipeline

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


def _raw_tour_row(**over):
    base = {
        "tour_id": str(uuid.uuid4()), "src_name": "Sapa Valley Trek", "country": "Vietnam",
        "pipeline_status": "published", "ingest_at": None, "batch_id": None,
        "source_id": None, "filename": None, "rewrite_count": 2, "last_rewritten_at": None,
    }
    base.update(over)
    return base


class TestGetAllToursWhereClause:
    """GET /admin/tours — AA-345 Part A: NULL-safe trash/delete/empty-itinerary
    floor, copied from acp_contract.v_trip_registry (migration 083)."""

    @pytest.mark.asyncio
    async def test_where_clause_is_null_safe_on_source_status(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_pipeline.get_all_tours(request, x_admin_secret=_TEST_SECRET)

        query = conn.fetch.call_args[0][0]
        # A bare `!= 'trashed'` silently drops every NULL row (SQL
        # three-valued logic) — the fix must explicitly allow NULL through.
        assert "rt.source_status IS NULL OR rt.source_status::text <> 'trashed'::text" in query

    @pytest.mark.asyncio
    async def test_where_clause_excludes_deleted_and_empty_itinerary(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_pipeline.get_all_tours(request, x_admin_secret=_TEST_SECRET)

        query = conn.fetch.call_args[0][0]
        assert "rt.deleted_at IS NULL" in query
        assert "rt.src_itineraries IS NOT NULL" in query
        assert "TRIM(BOTH FROM rt.src_itineraries) <> ''" in query

    @pytest.mark.asyncio
    async def test_published_tour_still_returned_with_pipeline_status(self):
        """Published tours are NOT filtered out (open product question, AA-345
        STEP 0 Phần 1) — pipeline_status is still returned so the existing
        frontend badge (s1-rewrite/page.tsx) keeps working unchanged."""
        conn = AsyncMock()
        conn.fetch.return_value = [_raw_tour_row(pipeline_status="published", rewrite_count=3)]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_pipeline.get_all_tours(request, x_admin_secret=_TEST_SECRET)

        assert result["total"] == 1
        assert result["tours"][0]["pipeline_status"] == "published"


class TestToursForAtomization:
    """GET /admin/tours-for-atomization — new AA-345 endpoint."""

    def _base_row(self, **over):
        base = {
            "tour_id": str(uuid.uuid4()), "name": "Sapa Valley Trek", "destination": "Vietnam",
            "duration_raw": "3 days", "itinerary_length": 2140, "pct_rank": 0.481,
            "quality_score": None, "trip_url": None, "url_alive": None,
            "is_published": False, "atom_count": 0,
        }
        base.update(over)
        return base

    @pytest.mark.asyncio
    async def test_reads_from_v_trip_registry(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_pipeline.get_tours_for_atomization(request, include_atomized=False, x_admin_secret=_TEST_SECRET)

        query = conn.fetch.call_args[0][0]
        assert "acp_contract.v_trip_registry" in query

    @pytest.mark.asyncio
    async def test_default_excludes_already_atomized_tours(self):
        """Default view = 763 - already-atomized, per AA-345's own design
        note (STEP 0 Phần 3.1: 'để không cho chọn lại tour đã atom hoá')."""
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_pipeline.get_tours_for_atomization(request, include_atomized=False, x_admin_secret=_TEST_SECRET)

        query = conn.fetch.call_args[0][0]
        assert "WHERE a.tour_id IS NULL" in query

    @pytest.mark.asyncio
    async def test_include_atomized_true_drops_the_filter(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_pipeline.get_tours_for_atomization(request, include_atomized=True, x_admin_secret=_TEST_SECRET)

        query = conn.fetch.call_args[0][0]
        assert "WHERE a.tour_id IS NULL" not in query

    @pytest.mark.asyncio
    async def test_percentile_computed_before_atomized_filter(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_pipeline.get_tours_for_atomization(request, include_atomized=False, x_admin_secret=_TEST_SECRET)

        query = conn.fetch.call_args[0][0]
        assert "PERCENT_RANK() OVER (ORDER BY LENGTH(vtr.itinerary_source))" in query

    @pytest.mark.asyncio
    async def test_has_atoms_and_is_thin_derived_correctly(self):
        rows = [
            self._base_row(atom_count=0),   # never atomized -> not thin
            self._base_row(atom_count=3),   # atomized, below THIN_TRIP_ATOM_MIN(5) -> thin
            self._base_row(atom_count=8),   # atomized, healthy -> not thin
        ]
        conn = AsyncMock()
        conn.fetch.return_value = rows
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_pipeline.get_tours_for_atomization(request, include_atomized=True, x_admin_secret=_TEST_SECRET)

        tours = result["tours"]
        assert tours[0]["has_atoms"] is False and tours[0]["is_thin"] is False
        assert tours[1]["has_atoms"] is True and tours[1]["is_thin"] is True
        assert tours[2]["has_atoms"] is True and tours[2]["is_thin"] is False

    @pytest.mark.asyncio
    async def test_is_published_reflects_view_flag(self):
        rows = [self._base_row(is_published=True), self._base_row(is_published=False)]
        conn = AsyncMock()
        conn.fetch.return_value = rows
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_pipeline.get_tours_for_atomization(request, include_atomized=True, x_admin_secret=_TEST_SECRET)

        assert result["tours"][0]["is_published"] is True
        assert result["tours"][1]["is_published"] is False

    @pytest.mark.asyncio
    async def test_percentile_scaled_to_0_100(self):
        rows = [self._base_row(pct_rank=0.481)]
        conn = AsyncMock()
        conn.fetch.return_value = rows
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_pipeline.get_tours_for_atomization(request, include_atomized=True, x_admin_secret=_TEST_SECRET)

        assert result["tours"][0]["itinerary_length_percentile"] == 48.1

    @pytest.mark.asyncio
    async def test_total_matches_row_count(self):
        rows = [self._base_row() for _ in range(5)]
        conn = AsyncMock()
        conn.fetch.return_value = rows
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_pipeline.get_tours_for_atomization(request, include_atomized=False, x_admin_secret=_TEST_SECRET)

        assert result["total"] == 5
        assert len(result["tours"]) == 5
