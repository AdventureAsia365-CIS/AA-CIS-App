"""AA-300 — curation UI backend (api/routers/admin_atoms.py).

Mocks the asyncpg pool per the pool.acquire() convention established in
test_aa299_atom_insert.py — no live DB, no LLM. Auth is exercised against
the real verify_admin_secret() imported unchanged from admin.py (AA-300
PHẦN A decision — nothing in admin.py itself is touched by this issue).

ADMIN_SECRET is a module-level constant in api/routers/admin.py, captured
from the environment at import time — verify_admin_secret() reads that
module global directly (it's defined in admin.py, so Python resolves the
name against admin.py's globals even when the function is re-exported into
admin_atoms.py via `from api.routers.admin import verify_admin_secret`).
monkeypatch.setenv() after import has no effect on it; every test here uses
monkeypatch.setattr("api.routers.admin.ADMIN_SECRET", ...) instead.
"""
import json
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.routers import admin_atoms

TENANT = "00000000-0000-0000-0000-000000000001"
_TEST_SECRET = "test-admin-secret"


@pytest.fixture(autouse=True)
def _admin_secret(monkeypatch):
    """Every test in this file runs with a known, non-empty ADMIN_SECRET —
    call sites pass _TEST_SECRET explicitly to authenticate."""
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


def _atom_row(**over):
    # media is JSONB on tour_atoms — asyncpg has no jsonb codec registered
    # on this app's connections, so it comes back as a raw JSON string, not
    # a parsed dict (found live in AA-300's preview-slotgrid 500 bug; fixed
    # in admin_atoms.py::_safe()). Fixtures must match real asyncpg shape,
    # not a hand-convenient Python dict, or a regression here goes untested.
    base = {
        "atom_id": "atom_abc1234567", "tour_id": uuid.uuid4(), "tour_name": "Sapa Valley Trek",
        "text": "Crossing the bamboo bridge at Ta Van village", "activity_type": "trek",
        "emotional_hook": None, "visual_potential": 2, "distinctiveness": "LOW",
        "media": '{"has_photo": false, "has_video": false, "media_refs": []}',
        "starred": False, "deleted": False,
        "created_at": "2026-07-01T00:00:00", "updated_at": "2026-07-01T00:00:00",
        "unreviewed": True, "tour_atom_count": 4,
    }
    base.update(over)
    return base


class TestAuthGate:
    def test_wrong_secret_rejected(self):
        with pytest.raises(HTTPException) as exc:
            admin_atoms.verify_admin_secret("wrong-secret")
        assert exc.value.status_code == 403

    def test_no_secret_configured_503(self, monkeypatch):
        monkeypatch.setattr("api.routers.admin.ADMIN_SECRET", "")
        with pytest.raises(HTTPException) as exc:
            admin_atoms.verify_admin_secret("anything")
        assert exc.value.status_code == 503

    def test_correct_secret_passes(self):
        admin_atoms.verify_admin_secret(_TEST_SECRET)  # must not raise

    def test_admin_atoms_reuses_admin_verify_admin_secret(self):
        """PHẦN A decision — admin_atoms.py must import, not redefine."""
        from api.routers.admin import verify_admin_secret
        assert admin_atoms.verify_admin_secret is verify_admin_secret


class TestListAtoms:
    @pytest.mark.asyncio
    async def test_default_batch_size_50(self):
        conn = AsyncMock()
        conn.fetch.return_value = [_atom_row(atom_id=f"atom_{i}") for i in range(50)]
        conn.fetchval.return_value = 137
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.list_atoms(
            request, tour_id=None, tour_ids=None, atom_ids=None, distinctiveness=None, unreviewed_only=False,
            thin_only=False, include_deleted=False, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        assert result["limit"] == 50
        assert len(result["atoms"]) == 50

    @pytest.mark.asyncio
    async def test_total_count_from_separate_count_query(self):
        """Pagination.tsx (reused as-is on the frontend) needs a total
        matching-filter count, not just the current page's row count — a
        second COUNT(*) query using the same WHERE clause."""
        conn = AsyncMock()
        conn.fetch.return_value = [_atom_row(atom_id=f"atom_{i}") for i in range(50)]
        conn.fetchval.return_value = 137
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.list_atoms(
            request, tour_id=None, tour_ids=None, atom_ids=None, distinctiveness=None, unreviewed_only=False,
            thin_only=False, include_deleted=False, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        assert result["total"] == 137
        count_query = conn.fetchval.call_args[0][0]
        assert count_query.strip().startswith("SELECT count(*)")

    @pytest.mark.asyncio
    async def test_unreviewed_filter_adds_clause(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_atoms.list_atoms(
            request, tour_id=None, tour_ids=None, atom_ids=None, distinctiveness=None, unreviewed_only=True,
            thin_only=False, include_deleted=False, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        query = conn.fetch.call_args[0][0]
        assert "ta.updated_at = ta.created_at" in query

    @pytest.mark.asyncio
    async def test_thin_only_filter_uses_thin_trip_atom_min(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        from services.acp_shared.atom_constants import THIN_TRIP_ATOM_MIN

        await admin_atoms.list_atoms(
            request, tour_id=None, tour_ids=None, atom_ids=None, distinctiveness=None, unreviewed_only=False,
            thin_only=True, include_deleted=False, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        query, *params = conn.fetch.call_args[0]
        assert "tc.atom_count <" in query
        assert THIN_TRIP_ATOM_MIN in params

    @pytest.mark.asyncio
    async def test_distinctiveness_filter(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_atoms.list_atoms(
            request, tour_id=None, tour_ids=None, atom_ids=None, distinctiveness="HIGH", unreviewed_only=False,
            thin_only=False, include_deleted=False, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        query, *params = conn.fetch.call_args[0]
        assert "ta.distinctiveness =" in query
        assert "HIGH" in params

    @pytest.mark.asyncio
    async def test_deleted_excluded_by_default(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_atoms.list_atoms(
            request, tour_id=None, tour_ids=None, atom_ids=None, distinctiveness=None, unreviewed_only=False,
            thin_only=False, include_deleted=False, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        query = conn.fetch.call_args[0][0]
        assert "NOT ta.deleted" in query

    @pytest.mark.asyncio
    async def test_empty_marker_atoms_always_excluded(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_atoms.list_atoms(
            request, tour_id=None, tour_ids=None, atom_ids=None, distinctiveness=None, unreviewed_only=False,
            thin_only=False, include_deleted=True, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        query = conn.fetch.call_args[0][0]
        assert "NOT ta.is_empty_marker" in query

    # ── AA-345 round 2, Việc 4: tour_ids (plural) deep link ─────────────────
    @pytest.mark.asyncio
    async def test_tour_ids_plural_filters_to_exact_set(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        await admin_atoms.list_atoms(
            request, tour_id=None, tour_ids=",".join(ids), atom_ids=None, distinctiveness=None,
            unreviewed_only=False, thin_only=False, include_deleted=False,
            limit=50, offset=0, x_admin_secret=_TEST_SECRET,
        )
        query, *params = conn.fetch.call_args[0]
        assert "ta.tour_id = ANY(" in query
        assert ids in params

    @pytest.mark.asyncio
    async def test_tour_ids_plural_wins_over_singular_tour_id(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)
        ids = [str(uuid.uuid4())]

        await admin_atoms.list_atoms(
            request, tour_id="some-other-id", tour_ids=ids[0], atom_ids=None, distinctiveness=None,
            unreviewed_only=False, thin_only=False, include_deleted=False,
            limit=50, offset=0, x_admin_secret=_TEST_SECRET,
        )
        query = conn.fetch.call_args[0][0]
        assert "ta.tour_id = ANY(" in query
        assert "ta.tour_id = $" not in query

    # AA-345 round 4 — Nghiep live-verified a real atomize run with EXACTLY
    # ONE tour_id ("Jomolhari Trek") and the deep link's ?tour_ids=<one uuid>
    # did not show that tour in Curation. Investigated end to end (live DB
    # query + a direct curl against the actual running ECS container,
    # bypassing the gateway/frontend entirely, using the real tour_id from
    # the incident) — both the SQL this handler builds and the live HTTP
    # response are correct for a single tour_id: `ta.tour_id =
    # ANY($1::uuid[])` with a 1-element array matches fine in Postgres, and
    # `test_tour_ids_plural_wins_over_singular_tour_id` above already
    # exercises a single-id string through this code path, but never
    # actually asserted the resulting SQL PARAMS were a proper 1-element
    # list (only that the ANY(...) clause was chosen) — that's the exact gap
    # this closes. Root cause of the live report was not found in this
    # handler; see docs/implementation-notes/AA-345-round4.md for the full
    # investigation (live data proved both this endpoint and
    # GET /admin/atoms/summary return the tour correctly).
    @pytest.mark.asyncio
    async def test_tour_ids_single_element_produces_single_element_param(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)
        single_id = str(uuid.uuid4())

        await admin_atoms.list_atoms(
            request, tour_id=None, tour_ids=single_id, atom_ids=None, distinctiveness=None,
            unreviewed_only=False, thin_only=False, include_deleted=False,
            limit=50, offset=0, x_admin_secret=_TEST_SECRET,
        )
        query, *params = conn.fetch.call_args[0]
        assert "ta.tour_id = ANY(" in query
        assert [single_id] in params

    @pytest.mark.asyncio
    async def test_singular_tour_id_still_works_when_tour_ids_absent(self):
        """Backward compat — the older single-tour deep link (still used
        elsewhere) must keep working unchanged."""
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        await admin_atoms.list_atoms(
            request, tour_id="abc-123", tour_ids=None, atom_ids=None, distinctiveness=None,
            unreviewed_only=False, thin_only=False, include_deleted=False,
            limit=50, offset=0, x_admin_secret=_TEST_SECRET,
        )
        query, *params = conn.fetch.call_args[0]
        assert "ta.tour_id = $1::uuid" in query
        assert "abc-123" in params


class TestPatchAtom:
    @pytest.mark.asyncio
    async def test_star_atom(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _atom_row(starred=True)
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin_atoms.AtomPatchRequest(starred=True)
        result = await admin_atoms.patch_atom(
            "atom_abc1234567", body, request, x_admin_secret=_TEST_SECRET)
        assert result["starred"] is True
        query, *params = conn.fetchrow.call_args[0]
        assert "starred = $1" in query
        assert "updated_at = now()" in query

    @pytest.mark.asyncio
    async def test_soft_delete_atom(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _atom_row(deleted=True)
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin_atoms.AtomPatchRequest(deleted=True)
        result = await admin_atoms.patch_atom(
            "atom_abc1234567", body, request, x_admin_secret=_TEST_SECRET)
        assert result["deleted"] is True

    @pytest.mark.asyncio
    async def test_edit_text(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _atom_row(text="Corrected text")
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin_atoms.AtomPatchRequest(text="Corrected text")
        result = await admin_atoms.patch_atom(
            "atom_abc1234567", body, request, x_admin_secret=_TEST_SECRET)
        assert result["text"] == "Corrected text"

    @pytest.mark.asyncio
    async def test_empty_text_rejected(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        body = admin_atoms.AtomPatchRequest(text="   ")
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.patch_atom("atom_abc1234567", body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_no_fields_rejected(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        body = admin_atoms.AtomPatchRequest()
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.patch_atom("atom_abc1234567", body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_atom_not_found_404(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = _make_pool(conn)
        request = _make_request(pool)
        body = admin_atoms.AtomPatchRequest(starred=True)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.patch_atom("atom_nonexistent", body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_query_excludes_empty_marker_rows(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _atom_row()
        pool = _make_pool(conn)
        request = _make_request(pool)
        body = admin_atoms.AtomPatchRequest(starred=True)
        await admin_atoms.patch_atom("atom_abc1234567", body, request, x_admin_secret=_TEST_SECRET)
        query = conn.fetchrow.call_args[0][0]
        assert "NOT is_empty_marker" in query

    @pytest.mark.asyncio
    async def test_wrong_secret_rejected_on_patch(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        body = admin_atoms.AtomPatchRequest(starred=True)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.patch_atom("atom_abc1234567", body, request, x_admin_secret="wrong")
        assert exc.value.status_code == 403


class TestAtomsSummary:
    @pytest.mark.asyncio
    async def test_breakdown_and_totals_independent_of_list_filters(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [{"distinctiveness": "LOW", "c": 230}, {"distinctiveness": "HIGH", "c": 5}],
            [
                {"tour_id": uuid.uuid4(), "tour_name": "Sapa Valley Trek",
                 "atom_count": 4, "unreviewed_count": 4, "atomized_at": None},
                {"tour_id": uuid.uuid4(), "tour_name": "Mongolia Gobi",
                 "atom_count": 12, "unreviewed_count": 0, "atomized_at": None},
            ],
        ]
        conn.fetchrow.return_value = {"total": 235, "reviewed": 12}
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.atoms_summary(request, x_admin_secret=_TEST_SECRET)

        assert result["distinctiveness_breakdown"] == {"HIGH": 5, "MED": 0, "LOW": 230}
        assert result["total_count"] == 235
        assert result["reviewed_count"] == 12

    @pytest.mark.asyncio
    async def test_by_tour_marks_thin_trips(self):
        from services.acp_shared.atom_constants import THIN_TRIP_ATOM_MIN
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [],
            [
                {"tour_id": uuid.uuid4(), "tour_name": "Ha Giang Loop",
                 "atom_count": 4, "unreviewed_count": 4, "atomized_at": None},  # < THIN_TRIP_ATOM_MIN=5 -> thin
                {"tour_id": uuid.uuid4(), "tour_name": "Mongolia Gobi",
                 "atom_count": 12, "unreviewed_count": 0, "atomized_at": None},  # not thin
            ],
        ]
        conn.fetchrow.return_value = {"total": 16, "reviewed": 0}
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.atoms_summary(request, x_admin_secret=_TEST_SECRET)

        by_name = {t["tour_name"]: t for t in result["by_tour"]}
        assert by_name["Ha Giang Loop"]["atom_count"] < THIN_TRIP_ATOM_MIN
        assert by_name["Ha Giang Loop"]["is_thin"] is True
        assert by_name["Mongolia Gobi"]["is_thin"] is False

    @pytest.mark.asyncio
    async def test_atomized_at_isoformatted_for_newest_first_sort(self):
        """AA-345 round 2, Việc 4: 'Newest first' sort on the curation page
        reads by_tour[i].atomized_at — must be a JSON-safe ISO string, not a
        raw datetime (which json.dumps can't serialize as-is)."""
        import datetime
        ts = datetime.datetime(2026, 8, 9, 6, 14, 45, tzinfo=datetime.timezone.utc)
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [],
            [{"tour_id": uuid.uuid4(), "tour_name": "Classic Laos",
              "atom_count": 48, "unreviewed_count": 0, "atomized_at": ts}],
        ]
        conn.fetchrow.return_value = {"total": 48, "reviewed": 48}
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.atoms_summary(request, x_admin_secret=_TEST_SECRET)

        assert result["by_tour"][0]["atomized_at"] == ts.isoformat()

    @pytest.mark.asyncio
    async def test_atomized_at_null_when_no_atoms_have_a_timestamp(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [],
            [{"tour_id": uuid.uuid4(), "tour_name": "Untouched Tour",
              "atom_count": 0, "unreviewed_count": 0, "atomized_at": None}],
        ]
        conn.fetchrow.return_value = {"total": 0, "reviewed": 0}
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.atoms_summary(request, x_admin_secret=_TEST_SECRET)

        assert result["by_tour"][0]["atomized_at"] is None

    @pytest.mark.asyncio
    async def test_wrong_secret_rejected(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.atoms_summary(request, x_admin_secret="wrong")
        assert exc.value.status_code == 403


class TestBulkPatchAtoms:
    @pytest.mark.asyncio
    async def test_bulk_star(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            _atom_row(atom_id="atom_1", starred=True),
            _atom_row(atom_id="atom_2", starred=True),
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin_atoms.BulkAtomPatchRequest(atom_ids=["atom_1", "atom_2"], starred=True)
        result = await admin_atoms.patch_atoms_bulk(body, request, x_admin_secret=_TEST_SECRET)

        assert result["updated_count"] == 2
        query, *params = conn.fetch.call_args[0]
        assert "atom_id = ANY($" in query
        assert "starred = $1" in query
        assert ["atom_1", "atom_2"] in params

    @pytest.mark.asyncio
    async def test_bulk_delete_uses_single_update_not_n_calls(self):
        """One UPDATE ... WHERE atom_id = ANY($1), not N sequential PATCH
        calls — the whole point of the bulk endpoint."""
        conn = AsyncMock()
        conn.fetch.return_value = [_atom_row(atom_id=f"atom_{i}", deleted=True) for i in range(5)]
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin_atoms.BulkAtomPatchRequest(
            atom_ids=[f"atom_{i}" for i in range(5)], deleted=True)
        result = await admin_atoms.patch_atoms_bulk(body, request, x_admin_secret=_TEST_SECRET)

        assert result["updated_count"] == 5
        assert conn.fetch.call_count == 1  # exactly one DB round-trip

    @pytest.mark.asyncio
    async def test_empty_atom_ids_rejected(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        body = admin_atoms.BulkAtomPatchRequest(atom_ids=[], starred=True)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.patch_atoms_bulk(body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_no_fields_rejected(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        body = admin_atoms.BulkAtomPatchRequest(atom_ids=["atom_1"])
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.patch_atoms_bulk(body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_wrong_secret_rejected(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        body = admin_atoms.BulkAtomPatchRequest(atom_ids=["atom_1"], starred=True)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.patch_atoms_bulk(body, request, x_admin_secret="wrong")
        assert exc.value.status_code == 403

    def test_bulk_route_registered_before_dynamic_atom_id_route(self):
        """FastAPI route-order regression guard — this repo's own CRITICAL
        rule (CLAUDE.md: '/{id}/full MUST come BEFORE /{id}') applies here:
        PATCH /atoms/bulk must be registered before PATCH /atoms/{atom_id}
        or FastAPI would greedily match 'bulk' as {atom_id}.

        Makes a REAL HTTP request through a real (but minimal, lifespan-free)
        FastAPI app mounting just this router, and confirms PATCH
        /admin/atoms/bulk actually invokes the bulk handler — identified by
        its distinctive response shape ({"updated": [...], "updated_count"}),
        which patch_atom("bulk", ...) could never produce.

        Deliberately NOT introspecting app.routes (the previous version of
        this test): a real CI failure — fresh `pip install -r
        requirements.txt` resolving the unpinned `fastapi>=0.110.1` to
        fastapi 0.139.2/starlette 1.3.1, a newer major Starlette than this
        dev environment's frozen 0.37.2 — showed that newer FastAPI wraps
        include_router()'d routes in an opaque `_IncludedRouter` object.
        `app.routes` no longer exposes a flat, walkable list of `Route`
        objects with `.path`/`.methods` for anything added via
        `include_router()` — an internal implementation detail this test
        must not depend on, reproduced directly in a clean venv built from
        this exact requirements.txt before writing this fix.

        Also deliberately NOT using the real api.main.app + TestClient's
        lifespan — that dials real Redis/Postgres on startup
        (api/main.py's `lifespan()`), which would hang/fail in the Unit
        Tests CI job (no Redis/Postgres service available there). Mounting
        just this router on a bare `FastAPI()` instance exercises real
        Starlette routing/dispatch without any of that."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        conn = AsyncMock()
        conn.fetch.return_value = [_atom_row(atom_id="atom_1", starred=True)]
        conn.fetchrow.return_value = _atom_row(atom_id="atom_abc1234567", starred=True)
        pool = _make_pool(conn)

        mini_app = FastAPI()
        mini_app.include_router(admin_atoms.router)
        mini_app.state.pool = pool

        client = TestClient(mini_app)

        bulk_res = client.patch(
            "/admin/atoms/bulk",
            json={"atom_ids": ["atom_1"], "starred": True},
            headers={"x-admin-secret": _TEST_SECRET},
        )
        assert bulk_res.status_code == 200, bulk_res.text
        bulk_body = bulk_res.json()
        assert "updated_count" in bulk_body, (
            f"PATCH /admin/atoms/bulk did not hit the bulk handler — got {bulk_body!r}. "
            "If routing regressed (bulk matched as {atom_id}), this would 404/500 instead.")
        assert bulk_body["updated_count"] == 1

        # contrasting real request — confirms the dynamic route still works
        # for an actual atom_id, i.e. this isn't just "bulk 404s so 200 must
        # mean it worked"
        single_res = client.patch(
            "/admin/atoms/atom_abc1234567",
            json={"starred": True},
            headers={"x-admin-secret": _TEST_SECRET},
        )
        assert single_res.status_code == 200, single_res.text
        single_body = single_res.json()
        assert "updated_count" not in single_body
        assert single_body["atom_id"] == "atom_abc1234567"


def _preview_fetchrow_side_effect(query, *args):
    """AA-323 — preview_slotgrid now issues two conn.fetchrow() calls before
    the N4/N5/N6 chain: fetch_tenant_planning_config() (tenant_config +
    posts_per_week join) and fetch_approved_quarter_plan() (Gate B lookup).
    Returns a real config row (no tenant_config row -> markets/channels fall
    back to defaults, same as the old hardcoded constants) and None for the
    quarter-plan lookup (no approved plan -> demo_mode=True), preserving
    every pre-AA-323 assertion below unchanged."""
    if "posts_per_week" in query:
        return {"posts_per_week": 4, "markets": None, "channels": None}
    return None


class TestPreviewSlotgrid:
    @pytest.mark.asyncio
    async def test_invalid_tenant_id_400(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.preview_slotgrid(
                request, tenant_id="not-a-uuid", version_id=None, x_admin_secret=_TEST_SECRET,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_calls_full_n4_n5_n6_chain_and_gate_b_approved(self):
        conn = AsyncMock()
        conn.fetch.return_value = []  # no trips -> empty chain, still must not crash
        conn.fetchrow.side_effect = _preview_fetchrow_side_effect
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.preview_slotgrid(
            request, tenant_id=TENANT, version_id=None, x_admin_secret=_TEST_SECRET,
        )

        assert result["quarter_plan"]["approved"] is True
        assert result["quarter_plan"]["approved_by"] == "admin-preview-demo"
        assert result["slot_grid"]["tenant_id"] == TENANT
        assert result["demo_params"]["markets"] == ["US"]
        assert result["demo_params"]["channels"] == ["blog"]
        assert result["demo_params"]["capacity_posts_per_week"] == 4

        # AA-320 follow-up gap, closed here: previously nothing asserted
        # that this read-only preview endpoint never writes to the DB —
        # runway_map()/plan_quarter()/allocate_month() only ever call
        # conn.fetch, and approve_quarter_plan() is a plain in-memory
        # mutation with no conn/pool argument at all (services/acp_planning
        # has zero conn.execute/INSERT/UPDATE anywhere, grep-confirmed) —
        # this makes that guarantee regression-proof instead of only true
        # by current code inspection. executemany is not used anywhere in
        # this call chain either (checked before adding this).
        conn.execute.assert_not_called()
        conn.executemany.assert_not_called()

    @staticmethod
    def _trip_row(trip_id):
        return {
            "id": trip_id, "name": "Ha Giang Loop", "destination": "Ha Giang",
            "period": "Mar-May", "duration_raw": "4 days", "itinerary_source": "trekking",
            "lifecycle_stage": "active", "trip_url": None, "url_alive": None,
        }

    @staticmethod
    def _atom_db_row(atom_id, trip_id, **over):
        # cooldown_until/usage_log are JSONB on tour_atoms — asyncpg returns
        # raw JSON strings here, not parsed dict/list (the exact live bug
        # this fixture must reproduce: services/acp_planning/quarter.py's
        # _row_to_atom() crashed on this with a real 500, uncaught by this
        # test suite because these fixtures used real Python {}/[] instead
        # of the actual string shape asyncpg produces).
        base = {
            "atom_id": atom_id, "tour_id": trip_id, "text": f"{atom_id} text content here",
            "activity_type": "trek",
            "distinctiveness": "HIGH", "starred": False, "deleted": False, "weight": 1.0,
            "cooldown_until": "{}", "usage_log": "[]",
        }
        base.update(over)
        return base

    @pytest.mark.asyncio
    async def test_deleted_atom_never_appears_in_slotgrid_end_to_end(self):
        """Issue verify: 'atom bị xoá -> không bao giờ xuất hiện trong slot' —
        exercised through the real preview endpoint, not just the pure
        allocator function (already covered in AA-301's own test suite)."""
        trip_id = uuid.uuid4()

        def fetch_side_effect(query, *args):
            if "v_trip_registry" in query:
                return [self._trip_row(trip_id)]
            if "tour_atoms" in query:
                return [
                    self._atom_db_row("atom_live", trip_id, deleted=False),
                    self._atom_db_row("atom_deleted_must_not_appear", trip_id, deleted=True),
                ]
            return []

        conn = AsyncMock()
        conn.fetch.side_effect = fetch_side_effect
        conn.fetchrow.side_effect = _preview_fetchrow_side_effect
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.preview_slotgrid(
            request, tenant_id=TENANT, version_id=None, x_admin_secret=_TEST_SECRET,
        )

        all_atom_ids = {aid for slot in result["slot_grid"]["slots"] for aid in slot["atom_ids"]}
        assert "atom_deleted_must_not_appear" not in all_atom_ids

    @pytest.mark.asyncio
    async def test_starred_atom_weight_boost_end_to_end(self):
        """Issue verify: 'atom star -> weight tăng trong allocator' —
        exercised through the real preview endpoint. 1 starred (1.5x
        weight) + 4 plain atoms, all HIGH distinctiveness, same trip. The
        blog channel fills each slot with up to 4 atoms sorted by weight
        descending — the starred atom must land in the FIRST slot created
        for this trip+channel (proving it was weight-sorted ahead of the
        plain ones), not merely "somewhere in the month" (with only one
        destination and enough capacity, a second slot for the same
        trip+channel can mop up whatever's left over, so a same-month
        presence check alone wouldn't distinguish "prioritized" from
        "eventually used anyway")."""
        trip_id = uuid.uuid4()
        atoms = [self._atom_db_row("atom_starred", trip_id, starred=True)] + [
            self._atom_db_row(f"atom_plain_{i}", trip_id) for i in range(4)
        ]

        def fetch_side_effect(query, *args):
            if "v_trip_registry" in query:
                return [self._trip_row(trip_id)]
            if "tour_atoms" in query:
                return atoms
            return []

        conn = AsyncMock()
        conn.fetch.side_effect = fetch_side_effect
        conn.fetchrow.side_effect = _preview_fetchrow_side_effect
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.preview_slotgrid(
            request, tenant_id=TENANT, version_id=None, x_admin_secret=_TEST_SECRET,
        )

        evergreen_slots = [s for s in result["slot_grid"]["slots"] if s["kind"] == "evergreen"]
        assert evergreen_slots, "expected at least one evergreen slot"
        first_slot_atom_ids = evergreen_slots[0]["atom_ids"]
        assert "atom_starred" in first_slot_atom_ids, (
            "starred atom (1.5x weight) must be weight-sorted into the first slot, "
            f"got {first_slot_atom_ids}")

    @pytest.mark.asyncio
    async def test_defaults_to_aa_internal_tenant(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        conn.fetchrow.side_effect = _preview_fetchrow_side_effect
        pool = _make_pool(conn)
        request = _make_request(pool)
        result = await admin_atoms.preview_slotgrid(
            request, tenant_id=str(admin_atoms._AA_INTERNAL_TENANT_ID), version_id=None,
            x_admin_secret=_TEST_SECRET,
        )
        assert result["slot_grid"]["tenant_id"] == str(admin_atoms._AA_INTERNAL_TENANT_ID)

    @pytest.mark.asyncio
    async def test_reads_real_approved_quarter_plan_when_one_exists(self):
        """AA-323 Gap 1 — the full create -> Gate B approve -> N6 reads the
        real version chain, exercised at the unit level since live AWS
        (ECS/RDS) is stopped and needs interactive MFA this session (cannot
        be driven headlessly here — flagged to Nghiep for a live re-check).
        Confirms: when fetch_approved_quarter_plan() finds an approved
        version, preview_slotgrid takes the allocate_month_from_db() branch
        (demo_mode=False, approved_by is the REAL approver, not
        "admin-preview-demo"), instead of the in-memory demo auto-approve."""
        trip_id = uuid.uuid4()
        real_payload = json.dumps({
            "tenant_id": TENANT, "year": 2026, "quarter": 3,
            "trip_ids": [str(trip_id)], "forced_specials": [], "big_rocks": [],
            "destination_shares": {}, "thin_trip_notes": [], "capacity_note": None,
            "trips_hash": None, "trip_scores": [], "approved": False, "approved_by": None,
        })

        def fetchrow_side_effect(query, *args):
            if "posts_per_week" in query:
                return {"posts_per_week": 4, "markets": None, "channels": None}
            if "quarter_plan_version" in query:
                return {"payload": real_payload, "approved_by": "real-admin@example.com"}
            return None

        def fetch_side_effect(query, *args):
            if "v_trip_registry" in query:
                return [self._trip_row(trip_id)]
            if "tour_atoms" in query:
                return [self._atom_db_row("atom_real", trip_id)]
            return []

        conn = AsyncMock()
        conn.fetch.side_effect = fetch_side_effect
        conn.fetchrow.side_effect = fetchrow_side_effect
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.preview_slotgrid(
            request, tenant_id=TENANT, version_id=None, x_admin_secret=_TEST_SECRET,
        )

        assert result["demo_params"]["demo_mode"] is False
        assert result["quarter_plan"]["approved_by"] == "real-admin@example.com"
        assert result["quarter_plan"]["approved"] is True
        conn.execute.assert_not_called()  # still read-only

    @pytest.mark.asyncio
    async def test_wrong_secret_rejected_on_preview(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.preview_slotgrid(request, tenant_id=TENANT, x_admin_secret="wrong")
        assert exc.value.status_code == 403

    # ── AA-323 round 6, Phần A — version-scoped Preview (?version_id=) ─────

    @pytest.mark.asyncio
    async def test_invalid_version_id_400(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.preview_slotgrid(
                request, tenant_id=TENANT, version_id="not-a-uuid", x_admin_secret=_TEST_SECRET,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_version_id_404(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None  # fetch_quarter_plan_version finds nothing
        pool = _make_pool(conn)
        request = _make_request(pool)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.preview_slotgrid(
                request, tenant_id=TENANT, version_id=str(uuid.uuid4()), x_admin_secret=_TEST_SECRET,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_pending_version_id_400_not_500(self):
        """Gate B: N6 must never allocate from an un-approved plan — a pending/
        rejected version_id must be a clear 400, not silently treated as
        approved or a crash."""
        pending_payload = json.dumps({
            "tenant_id": TENANT, "year": 2026, "quarter": 3,
            "trip_ids": [], "forced_specials": [], "big_rocks": [],
            "destination_shares": {}, "thin_trip_notes": [], "capacity_note": None,
            "trips_hash": None, "trip_scores": [], "approved": False, "approved_by": None,
        })

        def fetchrow_side_effect(query, *args):
            if "qpv.version_id = $1" in query:
                return {
                    "tenant_id": TENANT, "year": 2026, "quarter": 3, "version_no": 2,
                    "payload": pending_payload, "approval_status": "pending", "approved_by": None,
                }
            return None

        conn = AsyncMock()
        conn.fetchrow.side_effect = fetchrow_side_effect
        pool = _make_pool(conn)
        request = _make_request(pool)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.preview_slotgrid(
                request, tenant_id=TENANT, version_id=str(uuid.uuid4()), x_admin_secret=_TEST_SECRET,
            )
        assert exc.value.status_code == 400
        assert "v2" in exc.value.detail
        assert "pending" in exc.value.detail

    @pytest.mark.asyncio
    async def test_approved_version_id_reads_that_specific_version(self):
        """The version row's own tenant_id/year/quarter drive the computation
        (not the tenant_id query param, not today's date) — proves this by
        using a year/quarter that couldn't possibly be "today"."""
        trip_id = uuid.uuid4()
        historical_payload = json.dumps({
            "tenant_id": TENANT, "year": 2024, "quarter": 1,
            "trip_ids": [str(trip_id)], "forced_specials": [], "big_rocks": [],
            "destination_shares": {}, "thin_trip_notes": [], "capacity_note": None,
            "trips_hash": None, "trip_scores": [], "approved": False, "approved_by": None,
        })

        def fetchrow_side_effect(query, *args):
            if "qpv.version_id = $1" in query:
                # asyncpg returns tenant_id as a real UUID object (it's a uuid
                # column) — QuarterPlan(**payload) pydantic-coerces the JSON
                # payload's tenant_id string to UUID too, so this must match
                # or compute_slot_grid()'s cross-tenant guard trips.
                return {
                    "tenant_id": uuid.UUID(TENANT), "year": 2024, "quarter": 1, "version_no": 3,
                    "payload": historical_payload, "approval_status": "approved",
                    "approved_by": "ms.thu",
                }
            if "posts_per_week" in query:
                return {"posts_per_week": 4, "markets": None, "channels": None}
            return None

        def fetch_side_effect(query, *args):
            if "v_trip_registry" in query:
                return [self._trip_row(trip_id)]
            if "tour_atoms" in query:
                return [self._atom_db_row("atom_hist", trip_id)]
            return []

        conn = AsyncMock()
        conn.fetch.side_effect = fetch_side_effect
        conn.fetchrow.side_effect = fetchrow_side_effect
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.preview_slotgrid(
            request, tenant_id=TENANT, version_id=str(uuid.uuid4()), x_admin_secret=_TEST_SECRET,
        )

        assert result["demo_params"]["demo_mode"] is False
        assert result["quarter_plan_version_no"] == 3
        assert result["quarter_plan"]["year"] == 2024
        assert result["quarter_plan"]["quarter"] == 1
        assert result["slot_grid"]["year"] == 2024
        assert result["slot_grid"]["month"] == 1  # first month of Q1, not "today"
        conn.execute.assert_not_called()  # still read-only

    # ── AA-323 round 7 — same version, two entry points, must agree ────────
    # Live-verified real bug: v6 (aa_internal, Q3 2026, approved, current)
    # gave MOFU/PAS via ?version_id= (month=7, quarter's first month) but
    # BOFU/AIDA via the plain default link (month=8, today's real month) —
    # runway.stage("South Korea", "US", 7) vs (..., 8) genuinely differ.
    # Root cause: preview_slotgrid()'s two branches derived `month`
    # independently. Fixed via a single shared `_preview_month_for_quarter()`.

    def test_preview_month_current_quarter_uses_todays_real_month(self, monkeypatch):
        fixed_today = date(2026, 8, 13)  # Q3 2026, NOT July (Q3's first month)

        class _FixedDate(date):
            @classmethod
            def today(cls):
                return fixed_today

        monkeypatch.setattr(admin_atoms, "date", _FixedDate)
        assert admin_atoms._preview_month_for_quarter(2026, 3) == 8

    def test_preview_month_different_quarter_uses_quarters_first_month(self, monkeypatch):
        fixed_today = date(2026, 8, 13)  # Q3 2026 — 2020 Q1 is a different quarter/year

        class _FixedDate(date):
            @classmethod
            def today(cls):
                return fixed_today

        monkeypatch.setattr(admin_atoms, "date", _FixedDate)
        assert admin_atoms._preview_month_for_quarter(2020, 1) == 1
        assert admin_atoms._preview_month_for_quarter(2026, 4) == 10  # same year, different quarter

    @pytest.mark.asyncio
    async def test_current_version_via_version_id_matches_plain_default_exactly(self, monkeypatch):
        """The core round 7 invariant: `?version_id=<the tenant's current
        version>` and no `?version_id=` at all must compute the byte-identical
        SlotGrid — both represent "the tenant's current approved plan"."""
        fixed_today = date(2026, 8, 13)

        class _FixedDate(date):
            @classmethod
            def today(cls):
                return fixed_today

        monkeypatch.setattr(admin_atoms, "date", _FixedDate)

        trip_id = uuid.uuid4()
        payload = json.dumps({
            "tenant_id": TENANT, "year": 2026, "quarter": 3,
            "trip_ids": [str(trip_id)], "forced_specials": [], "big_rocks": [],
            "destination_shares": {}, "thin_trip_notes": [], "capacity_note": None,
            "trips_hash": None, "trip_scores": [], "approved": False, "approved_by": None,
        })
        current_version_id = str(uuid.uuid4())

        def fetchrow_side_effect(query, *args):
            if "qpv.version_id = $1" in query:
                return {
                    "tenant_id": uuid.UUID(TENANT), "year": 2026, "quarter": 3, "version_no": 6,
                    "payload": payload, "approval_status": "approved", "approved_by": "ms.thu",
                }
            if "posts_per_week" in query:
                return {"posts_per_week": 4, "markets": None, "channels": None}
            if "qpv.payload, qpv.approved_by" in query:
                return {"payload": payload, "approved_by": "ms.thu"}
            return None

        def fetch_side_effect(query, *args):
            if "v_trip_registry" in query:
                return [self._trip_row(trip_id)]
            if "tour_atoms" in query:
                return [self._atom_db_row("atom_current", trip_id)]
            return []

        # Path 1: explicit ?version_id= for the tenant's current version.
        conn1 = AsyncMock()
        conn1.fetch.side_effect = fetch_side_effect
        conn1.fetchrow.side_effect = fetchrow_side_effect
        result_with_id = await admin_atoms.preview_slotgrid(
            _make_request(_make_pool(conn1)), tenant_id=TENANT,
            version_id=current_version_id, x_admin_secret=_TEST_SECRET,
        )

        # Path 2: no version_id — the plain default link (Atom Curation's button).
        conn2 = AsyncMock()
        conn2.fetch.side_effect = fetch_side_effect
        conn2.fetchrow.side_effect = fetchrow_side_effect
        result_default = await admin_atoms.preview_slotgrid(
            _make_request(_make_pool(conn2)), tenant_id=TENANT,
            version_id=None, x_admin_secret=_TEST_SECRET,
        )

        # slot_id is intentionally random for reactive_hold slots (unrelated
        # to round 7 — a placeholder ID, not real content) and left out of
        # this comparison; everything else (funnel_stage, framework,
        # atom_ids, trip_id — the actual content round 7's bug changed)
        # must match exactly.
        def _content(slots):
            return [{k: v for k, v in s.items() if k != "slot_id"} for s in slots]

        assert result_with_id["slot_grid"]["month"] == result_default["slot_grid"]["month"] == 8
        assert _content(result_with_id["slot_grid"]["slots"]) == _content(result_default["slot_grid"]["slots"]), (
            "same approved version reached via the two different UI entry points "
            "produced two different Slot Grids — this is exactly round 7's bug"
        )
        assert result_with_id["demo_params"]["demo_mode"] is False
        assert result_default["demo_params"]["demo_mode"] is False

    @pytest.mark.asyncio
    async def test_demo_mode_never_true_when_current_version_id_exists(self):
        """AA-323 round 7 — confirms (not just asserts in a comment) that the
        in-memory demo path is structurally unreachable once a real approved
        current version exists: fetch_approved_quarter_plan()'s WHERE clause
        (qpv.version_id = qp.current_version_id AND approval_status =
        'approved') is what guarantees this, not a separate flag check."""
        payload = json.dumps({
            "tenant_id": TENANT, "year": 2026, "quarter": 3,
            "trip_ids": [], "forced_specials": [], "big_rocks": [],
            "destination_shares": {}, "thin_trip_notes": [], "capacity_note": None,
            "trips_hash": None, "trip_scores": [], "approved": False, "approved_by": None,
        })

        def fetchrow_side_effect(query, *args):
            if "posts_per_week" in query:
                return {"posts_per_week": 4, "markets": None, "channels": None}
            if "qpv.payload, qpv.approved_by" in query:
                return {"payload": payload, "approved_by": "ms.thu"}
            return None

        conn = AsyncMock()
        conn.fetch.return_value = []
        conn.fetchrow.side_effect = fetchrow_side_effect
        result = await admin_atoms.preview_slotgrid(
            _make_request(_make_pool(conn)), tenant_id=TENANT, version_id=None,
            x_admin_secret=_TEST_SECRET,
        )
        assert result["demo_params"]["demo_mode"] is False
        assert result["quarter_plan"]["approved_by"] == "ms.thu"


class TestNoV1AtomsRegression:
    def test_decompose_endpoint_untouched(self):
        """PHẦN A decision — this issue must not modify v1_atoms.py at all."""
        from api.routers import v1_atoms
        assert hasattr(v1_atoms, "decompose")
        assert hasattr(v1_atoms, "router")
