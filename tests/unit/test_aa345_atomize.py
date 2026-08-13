"""AA-345 — tour-selection UI backend (GET /admin/tours WHERE fix,
GET /admin/tours-for-atomization, POST /admin/atoms/decompose alias).

Mocks the asyncpg pool per the pool.acquire() convention established in
test_aa299_atom_insert.py / test_aa300_admin_atoms.py — no live DB. Verifies
the WHERE clause text (NULL-safety) and the new endpoints' response shape by
inspecting conn.fetch.call_args, same style as test_aa300_admin_atoms.py.
Does NOT test N2 decompose itself (verified live against real Bedrock, AA-345
STEP 0 Phần 4, 20/20 tours succeeded) — only that the UI-facing endpoints
query and shape data correctly.

AA-345 fixes round (live prod verify found 2 real bugs — see
docs/implementation-notes/AA-345-fixes.md):
- Bug 1: POST /admin/atoms/decompose is a new admin-side alias (same shape as
  admin_pipeline.py's existing AA-230 review-queue aliases) added because the
  old dedicated /v1/atoms/decompose path sits behind the API Gateway Lambda
  Authorizer in production and 401'd there before reaching the app at all.
- Bug 2: GET /admin/tours-for-atomization's old `include_atomized` bool could
  only widen "pending" into "everything" — no way to see ONLY already-
  atomized tours. Replaced with a 3-way `status` filter; tests below cover
  all three values, not just one direction as before.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
        conn = AsyncMock()
        conn.fetch.return_value = [_raw_tour_row(pipeline_status="published", rewrite_count=3)]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_pipeline.get_all_tours(request, x_admin_secret=_TEST_SECRET)

        assert result["total"] == 1
        assert result["tours"][0]["pipeline_status"] == "published"


class TestToursForAtomization:
    """GET /admin/tours-for-atomization — status filter (pending/atomized/all)
    + pagination (AA-345 fixes round, Bug 2 + UX 3)."""

    def _base_row(self, **over):
        base = {
            "tour_id": str(uuid.uuid4()), "name": "Sapa Valley Trek", "destination": "Vietnam",
            "duration_raw": "3 days", "itinerary_length": 2140, "pct_rank": 0.481,
            "quality_score": None, "trip_url": None, "url_alive": None,
            "is_published": False, "atom_count": 0, "atomized_at": None,
        }
        base.update(over)
        return base

    def _mock_conn(self, rows, total, destination_rows=None):
        # get_tours_for_atomization() calls conn.fetch() TWICE (distinct
        # destinations, then the paginated rows) — a plain return_value
        # would make both calls return the same thing, which is fine for
        # tests that only care about the rows/WHERE-clause (call_args always
        # reflects the LAST call, i.e. the rows query), but wrong for tests
        # asserting on distinct_destinations specifically, so side_effect is
        # used whenever destination_rows is given explicitly.
        conn = AsyncMock()
        conn.fetchval.return_value = total
        if destination_rows is not None:
            conn.fetch.side_effect = [destination_rows, rows]
        else:
            conn.fetch.return_value = rows
        return conn

    async def _call(self, request, status="pending", destination="", sort="length_asc", limit=150, offset=0):
        return await admin_pipeline.get_tours_for_atomization(
            request, status=status, destination=destination, sort=sort,
            limit=limit, offset=offset, x_admin_secret=_TEST_SECRET,
        )

    @pytest.mark.asyncio
    async def test_reads_from_v_trip_registry(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request)

        query = conn.fetch.call_args[0][0]
        assert "acp_contract.v_trip_registry" in query

    @pytest.mark.asyncio
    async def test_status_pending_filters_to_unatomized_only(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request)

        query = conn.fetch.call_args[0][0]
        assert "WHERE a.tour_id IS NULL" in query

    @pytest.mark.asyncio
    async def test_status_atomized_filters_to_atomized_only(self):
        """Bug 2: the old include_atomized bool had NO way to show only
        already-atomized tours — this is the exact gap the live bug report
        flagged ('list still mixes in not-yet-atomized tours'). Verifies the
        new status=atomized value actually produces the opposite WHERE
        clause, not just a widened one."""
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="atomized")

        query = conn.fetch.call_args[0][0]
        assert "WHERE a.tour_id IS NOT NULL" in query
        assert "WHERE a.tour_id IS NULL" not in query

    @pytest.mark.asyncio
    async def test_status_empty_string_means_no_filter(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="")

        query = conn.fetch.call_args[0][0]
        assert "WHERE a.tour_id IS NULL" not in query
        assert "WHERE a.tour_id IS NOT NULL" not in query

    @pytest.mark.asyncio
    async def test_percentile_computed_over_full_floor(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request)

        query = conn.fetch.call_args[0][0]
        assert "PERCENT_RANK() OVER (ORDER BY LENGTH(vtr.itinerary_source))" in query

    @pytest.mark.asyncio
    async def test_pagination_params_forwarded(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, limit=50, offset=100)

        query, limit_param, offset_param = conn.fetch.call_args[0]
        assert "LIMIT $1 OFFSET $2" in query
        assert limit_param == 50
        assert offset_param == 100

    @pytest.mark.asyncio
    async def test_total_is_full_count_not_page_size(self):
        """UX 3: total must reflect the whole filtered set (via a separate
        COUNT(*)), not just how many rows this page returned — otherwise
        'Showing X of Y' and Load More can't work."""
        rows = [self._base_row() for _ in range(5)]
        conn = self._mock_conn(rows, total=628)
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await self._call(request, limit=5)

        assert len(result["tours"]) == 5
        assert result["total"] == 628

    @pytest.mark.asyncio
    async def test_has_atoms_and_is_thin_derived_correctly(self):
        rows = [
            self._base_row(atom_count=0),   # never atomized -> not thin
            self._base_row(atom_count=3),   # atomized, below THIN_TRIP_ATOM_MIN(5) -> thin
            self._base_row(atom_count=8),   # atomized, healthy -> not thin
        ]
        conn = self._mock_conn(rows, total=3)
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await self._call(request, status="")

        tours = result["tours"]
        assert tours[0]["has_atoms"] is False and tours[0]["is_thin"] is False
        assert tours[1]["has_atoms"] is True and tours[1]["is_thin"] is True
        assert tours[2]["has_atoms"] is True and tours[2]["is_thin"] is False

    @pytest.mark.asyncio
    async def test_is_published_reflects_view_flag(self):
        rows = [self._base_row(is_published=True), self._base_row(is_published=False)]
        conn = self._mock_conn(rows, total=2)
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await self._call(request, status="")

        assert result["tours"][0]["is_published"] is True
        assert result["tours"][1]["is_published"] is False

    @pytest.mark.asyncio
    async def test_percentile_scaled_to_0_100(self):
        rows = [self._base_row(pct_rank=0.481)]
        conn = self._mock_conn(rows, total=1)
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await self._call(request, status="")

        assert result["tours"][0]["itinerary_length_percentile"] == 48.1

    # ── AA-345 round 2, Bug 5 (regression) ──────────────────────────────────
    # The frontend's `if (statusFilter) params.set("status", statusFilter)`
    # treated status="" (the "All tours" option) as falsy -> "send nothing" ->
    # silently fell back to this endpoint's own "pending" default. That bug
    # was entirely client-side (fixed in atomize/page.tsx), but these three
    # tests re-confirm the SERVER side of all 3 status values explicitly and
    # independently — not just 1 or 2 as before — so a future regression on
    # either side gets caught here regardless of which layer breaks.
    @pytest.mark.asyncio
    async def test_bug5_status_pending_is_restrictive(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="pending")

        query = conn.fetch.call_args[0][0]
        assert "WHERE a.tour_id IS NULL" in query

    @pytest.mark.asyncio
    async def test_bug5_status_atomized_is_restrictive(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="atomized")

        query = conn.fetch.call_args[0][0]
        assert "WHERE a.tour_id IS NOT NULL" in query

    @pytest.mark.asyncio
    async def test_bug5_status_all_is_unrestrictive(self):
        """This is the exact case the regression broke: status="" reaching
        the backend must produce NO status filter at all, not silently
        collapse to the "pending" default's WHERE clause."""
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="")

        query = conn.fetch.call_args[0][0]
        assert "a.tour_id IS NULL" not in query
        assert "a.tour_id IS NOT NULL" not in query

    # ── Việc 2: destination filter + sort ───────────────────────────────────
    @pytest.mark.asyncio
    async def test_destination_filter_adds_where_clause(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="", destination="Japan")

        query, *params = conn.fetch.call_args[0]
        assert "b.destination = $" in query
        assert "Japan" in params

    @pytest.mark.asyncio
    async def test_no_destination_filter_when_empty(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="", destination="")

        query = conn.fetch.call_args[0][0]
        assert "b.destination = $" not in query

    @pytest.mark.asyncio
    async def test_distinct_destinations_in_response(self):
        rows = [self._base_row()]
        dest_rows = [{"destination": "Japan"}, {"destination": "Laos"}]
        conn = self._mock_conn(rows, total=1, destination_rows=dest_rows)
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await self._call(request)

        assert result["distinct_destinations"] == ["Japan", "Laos"]

    @pytest.mark.asyncio
    async def test_sort_length_desc(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="", sort="length_desc")

        query = conn.fetch.call_args[0][0]
        assert "ORDER BY b.itinerary_length DESC" in query

    @pytest.mark.asyncio
    async def test_sort_duration_asc(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="", sort="duration_asc")

        query = conn.fetch.call_args[0][0]
        assert "ORDER BY b.duration_raw ASC" in query

    # ── AA-345 round 3, Việc 1: "Newest/Oldest atomized first" ──────────────
    @pytest.mark.asyncio
    async def test_sort_atomized_desc(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="atomized", sort="atomized_desc")

        query = conn.fetch.call_args[0][0]
        assert "ORDER BY a.atomized_at DESC NULLS LAST" in query

    @pytest.mark.asyncio
    async def test_sort_atomized_asc(self):
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        await self._call(request, status="atomized", sort="atomized_asc")

        query = conn.fetch.call_args[0][0]
        assert "ORDER BY a.atomized_at ASC NULLS LAST" in query

    @pytest.mark.asyncio
    async def test_sort_atomized_desc_orders_rows_by_real_timestamp(self):
        import datetime
        newer = datetime.datetime(2026, 8, 13, 2, 41, 59, tzinfo=datetime.timezone.utc)
        older = datetime.datetime(2026, 7, 21, 15, 51, 28, tzinfo=datetime.timezone.utc)
        # Mock DB order deliberately matches what a real DESC-sorted query
        # would return — this test isn't re-verifying Postgres's ORDER BY
        # (that's the DB's job, and can't be exercised against a mock), it's
        # confirming the endpoint doesn't re-shuffle rows after fetching them.
        rows = [self._base_row(name="Punakha Festival", atomized_at=newer),
                self._base_row(name="Yaksa Trek", atomized_at=older)]
        conn = self._mock_conn(rows, total=2)
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await self._call(request, status="atomized", sort="atomized_desc")

        assert result["tours"][0]["name"] == "Punakha Festival"
        assert result["tours"][0]["atomized_at"] == newer.isoformat()
        assert result["tours"][1]["atomized_at"] == older.isoformat()

    @pytest.mark.asyncio
    async def test_invalid_sort_value_not_silently_accepted(self):
        """A real HTTP request with an unrecognized `sort` never reaches this
        function body at all — FastAPI's own Query(pattern=...) rejects it
        with a 422 first. That layer isn't exercised by calling the function
        directly (no request parsing happens), so this only proves the
        second line of defense: _SORT_COLUMNS has no silent fallback that
        would let a bad value slip into raw SQL string interpolation."""
        conn = self._mock_conn([], 0)
        pool = _make_pool(conn)
        request = _make_request(pool)

        with pytest.raises(KeyError):
            await admin_pipeline.get_tours_for_atomization(
                request, status="", destination="", sort="not_a_real_sort",
                limit=150, offset=0, x_admin_secret=_TEST_SECRET,
            )

    # ── Việc 4: atomized_at timestamp ───────────────────────────────────────
    @pytest.mark.asyncio
    async def test_atomized_at_present_when_tour_has_atoms(self):
        import datetime
        ts = datetime.datetime(2026, 8, 9, 6, 14, 45, tzinfo=datetime.timezone.utc)
        rows = [self._base_row(atom_count=5, atomized_at=ts)]
        conn = self._mock_conn(rows, total=1)
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await self._call(request, status="")

        assert result["tours"][0]["atomized_at"] == ts.isoformat()

    @pytest.mark.asyncio
    async def test_atomized_at_null_when_never_atomized(self):
        rows = [self._base_row(atom_count=0, atomized_at=None)]
        conn = self._mock_conn(rows, total=1)
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await self._call(request, status="")

        assert result["tours"][0]["atomized_at"] is None


class TestAdminDecomposeAlias:
    """POST /admin/atoms/decompose — AA-345 fixes round Bug 1: an admin-side
    alias (same shape as admin_pipeline.py's existing AA-230 review-queue
    aliases) that bypasses the API Gateway Lambda Authorizer gating
    /v1/atoms/decompose in production. Reuses v1_atoms.decompose() verbatim —
    this test only verifies the alias wires auth + delegation correctly, not
    decompose's own internal logic (already covered by v1_atoms's own tests /
    STEP 0's live verify)."""

    @pytest.mark.asyncio
    async def test_requires_admin_secret(self):
        from fastapi import HTTPException
        request = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await admin_pipeline.admin_decompose_atoms(
                body=admin_pipeline._V1DecomposeRequest(tour_ids=["t1"]),
                request=request, x_admin_secret="wrong-secret",
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delegates_to_v1_atoms_decompose_with_tenant_none(self):
        request = MagicMock()
        body = admin_pipeline._V1DecomposeRequest(tour_ids=["t1", "t2"])
        fake_result = {"job_id": "atomjob_x", "tour_count": 2, "mode": "inline"}

        with patch("api.routers.v1_atoms.decompose", new=AsyncMock(return_value=fake_result)) as mock_decompose:
            result = await admin_pipeline.admin_decompose_atoms(
                body=body, request=request, x_admin_secret=_TEST_SECRET,
            )

        mock_decompose.assert_awaited_once_with(body=body, request=request, tenant=None)
        assert result == fake_result
