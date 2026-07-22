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
import uuid
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
            request, tour_id=None, distinctiveness=None, unreviewed_only=False,
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
            request, tour_id=None, distinctiveness=None, unreviewed_only=False,
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
            request, tour_id=None, distinctiveness=None, unreviewed_only=True,
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
            request, tour_id=None, distinctiveness=None, unreviewed_only=False,
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
            request, tour_id=None, distinctiveness="HIGH", unreviewed_only=False,
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
            request, tour_id=None, distinctiveness=None, unreviewed_only=False,
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
            request, tour_id=None, distinctiveness=None, unreviewed_only=False,
            thin_only=False, include_deleted=True, limit=50, offset=0,
            x_admin_secret=_TEST_SECRET,
        )
        query = conn.fetch.call_args[0][0]
        assert "NOT ta.is_empty_marker" in query


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


class TestPreviewSlotgrid:
    @pytest.mark.asyncio
    async def test_invalid_tenant_id_400(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.preview_slotgrid(request, tenant_id="not-a-uuid", x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_calls_full_n4_n5_n6_chain_and_gate_b_approved(self):
        conn = AsyncMock()
        conn.fetch.return_value = []  # no trips -> empty chain, still must not crash
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.preview_slotgrid(request, tenant_id=TENANT, x_admin_secret=_TEST_SECRET)

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
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.preview_slotgrid(request, tenant_id=TENANT, x_admin_secret=_TEST_SECRET)

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
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin_atoms.preview_slotgrid(request, tenant_id=TENANT, x_admin_secret=_TEST_SECRET)

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
        pool = _make_pool(conn)
        request = _make_request(pool)
        result = await admin_atoms.preview_slotgrid(
            request, tenant_id=str(admin_atoms._AA_INTERNAL_TENANT_ID), x_admin_secret=_TEST_SECRET,
        )
        assert result["slot_grid"]["tenant_id"] == str(admin_atoms._AA_INTERNAL_TENANT_ID)

    @pytest.mark.asyncio
    async def test_wrong_secret_rejected_on_preview(self):
        pool = _make_pool(AsyncMock())
        request = _make_request(pool)
        with pytest.raises(HTTPException) as exc:
            await admin_atoms.preview_slotgrid(request, tenant_id=TENANT, x_admin_secret="wrong")
        assert exc.value.status_code == 403


class TestNoV1AtomsRegression:
    def test_decompose_endpoint_untouched(self):
        """PHẦN A decision — this issue must not modify v1_atoms.py at all."""
        from api.routers import v1_atoms
        assert hasattr(v1_atoms, "decompose")
        assert hasattr(v1_atoms, "router")
