"""AA-309 [N1] — tenant onboarding endpoints (api/routers/admin.py).

Mocks the asyncpg pool per the pool.acquire() convention established in
test_aa300_admin_atoms.py / test_aa330_admin_marketplace.py — no live DB, no LLM.
Auth is exercised against the real verify_admin_secret() from the same module.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.routers import admin

_TEST_SECRET = "test-admin-secret"

TENANT_ID = uuid.uuid4()
PORTFOLIO_ID = uuid.uuid4()
TOUR_A = uuid.uuid4()
TOUR_B = uuid.uuid4()


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


class _TxnCM:
    """conn.transaction() is a sync method returning an async context manager --
    AsyncMock's default auto-mocking makes it a coroutine instead, which breaks
    `async with conn.transaction():`. Same fix as test_aa361_atom_usage.py /
    test_aa367_packets.py."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _make_conn():
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=_TxnCM())
    return conn


class TestConstants:
    def test_assigned_angles_has_7_entries(self):
        assert len(admin.ASSIGNED_ANGLES) == 7

    def test_posts_per_week_matches_confirmed_decision(self):
        assert admin.POSTS_PER_WEEK_BY_PLAN_TIER == {
            "starter": 1, "growth": 3, "business": 5, "enterprise": 7, "internal": 7,
        }


class TestCreateTenantIsInactive:
    @pytest.mark.asyncio
    async def test_new_tenant_is_active_false(self):
        conn = _make_conn()
        # slug-existing check -> None, INSERT RETURNING -> TENANT_ID, has_rules check -> None (no
        # existing brand_rules row for this brand-new tenant)
        conn.fetchval.side_effect = [None, TENANT_ID, None]
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.CreateTenantRequest(name="Test Agency", slug="test-agency")
        result = await admin.create_tenant(body, request, x_admin_secret=_TEST_SECRET)

        assert result.is_active is False
        insert_args = conn.fetchval.call_args_list[1][0]
        assert "VALUES ($1, $2, $3::plan_tier_enum, $4, $5, false)" in insert_args[0]


class TestSeedAtoms:
    @pytest.mark.asyncio
    async def test_tenant_not_found_404(self):
        conn = AsyncMock()
        conn.fetchval.return_value = None
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.SeedAtomsRequest(portfolio_id=PORTFOLIO_ID)
        with pytest.raises(HTTPException) as exc:
            await admin.seed_tenant_atoms(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_portfolio_not_found_404(self):
        conn = AsyncMock()
        conn.fetchval.return_value = TENANT_ID
        conn.fetchrow.return_value = None
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.SeedAtomsRequest(portfolio_id=PORTFOLIO_ID)
        with pytest.raises(HTTPException) as exc:
            await admin.seed_tenant_atoms(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_portfolio_not_finalized_400(self):
        conn = AsyncMock()
        conn.fetchval.return_value = TENANT_ID
        conn.fetchrow.return_value = {
            "portfolio_id": PORTFOLIO_ID, "tour_ids": [TOUR_A, TOUR_B], "status": "draft",
        }
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.SeedAtomsRequest(portfolio_id=PORTFOLIO_ID)
        with pytest.raises(HTTPException) as exc:
            await admin.seed_tenant_atoms(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_seeds_rows_from_finalized_portfolio(self):
        conn = _make_conn()
        conn.fetchval.side_effect = [TENANT_ID, 2]  # tenant check, then seeded_count
        conn.fetchrow.side_effect = [
            {"portfolio_id": PORTFOLIO_ID, "tour_ids": [TOUR_A, TOUR_B], "status": "finalized"},
            None,  # no existing tenant_onboarding row
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.SeedAtomsRequest(portfolio_id=PORTFOLIO_ID)
        result = await admin.seed_tenant_atoms(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)

        assert result["seeded_tour_count"] == 2
        insert_query, insert_tenant, insert_tours = conn.execute.call_args_list[0][0]
        assert "INSERT INTO acp_shared.tenant_atom_state" in insert_query
        assert insert_tours == [TOUR_A, TOUR_B]

    @pytest.mark.asyncio
    async def test_reseed_same_portfolio_is_idempotent_noop(self):
        conn = _make_conn()
        conn.fetchval.side_effect = [TENANT_ID, 2]
        conn.fetchrow.side_effect = [
            {"portfolio_id": PORTFOLIO_ID, "tour_ids": [TOUR_A, TOUR_B], "status": "finalized"},
            {"portfolio_id": PORTFOLIO_ID},  # already seeded from the SAME portfolio
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.SeedAtomsRequest(portfolio_id=PORTFOLIO_ID)
        result = await admin.seed_tenant_atoms(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)
        assert result["seeded_tour_count"] == 2  # no exception -- safe no-op

    @pytest.mark.asyncio
    async def test_reseed_different_portfolio_rejected_409(self):
        other_portfolio = uuid.uuid4()
        conn = AsyncMock()
        conn.fetchval.return_value = TENANT_ID
        conn.fetchrow.side_effect = [
            {"portfolio_id": PORTFOLIO_ID, "tour_ids": [TOUR_A, TOUR_B], "status": "finalized"},
            {"portfolio_id": other_portfolio},  # seeded from a DIFFERENT portfolio previously
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.SeedAtomsRequest(portfolio_id=PORTFOLIO_ID)
        with pytest.raises(HTTPException) as exc:
            await admin.seed_tenant_atoms(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 409


class TestAssignAngle:
    @pytest.mark.asyncio
    async def test_invalid_angle_rejected_400(self):
        conn = AsyncMock()
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.AssignAngleRequest(assigned_angle="made_up_angle")
        with pytest.raises(HTTPException) as exc:
            await admin.assign_tenant_angle(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_valid_angle_updates_rows(self):
        conn = AsyncMock()
        conn.execute.return_value = "UPDATE 4"
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.AssignAngleRequest(assigned_angle="culinary_people")
        result = await admin.assign_tenant_angle(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)

        assert result["tour_rows_updated"] == 4
        assert result["assigned_angle"] == "culinary_people"
        assert result["assigned_angle_label"] == "Ẩm thực & Con người"

    @pytest.mark.asyncio
    async def test_no_seeded_rows_404(self):
        conn = AsyncMock()
        conn.execute.return_value = "UPDATE 0"
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.AssignAngleRequest(assigned_angle="culinary_people")
        with pytest.raises(HTTPException) as exc:
            await admin.assign_tenant_angle(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 404


class TestMirror:
    @pytest.mark.asyncio
    async def test_tenant_not_found_404(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = _make_pool(conn)
        request = _make_request(pool)

        with pytest.raises(HTTPException) as exc:
            await admin.get_tenant_mirror(TENANT_ID, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_seeded_rows_404(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"tenant_id": TENANT_ID, "plan_tier": "growth"}
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        request = _make_request(pool)

        with pytest.raises(HTTPException) as exc:
            await admin.get_tenant_mirror(TENANT_ID, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_fresh_atom_count_never_trusts_stale_snapshot(self):
        """The mock's tour_atoms COUNT(*) mock value is what must appear in the
        response -- proves the endpoint re-counts live rather than reading any
        marketplace_portfolios.atom_snapshot value (never queried at all here)."""
        conn = AsyncMock()
        conn.fetchrow.return_value = {"tenant_id": TENANT_ID, "plan_tier": "growth"}
        conn.fetch.return_value = [
            {"tour_id": TOUR_A, "assigned_angle": "culinary_people"},
            {"tour_id": TOUR_B, "assigned_angle": "culinary_people"},
        ]
        conn.fetchval.return_value = 87  # fresh COUNT(*)
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin.get_tenant_mirror(TENANT_ID, request, x_admin_secret=_TEST_SECRET)

        assert result["atom_count"] == 87
        assert result["posts_per_week"] == 3  # growth tier
        assert result["runway_months"] == 7  # matches runway_months(87, 3)
        assert "marketplace_portfolios" not in str(conn.fetch.call_args) + str(conn.fetchval.call_args)

    @pytest.mark.asyncio
    async def test_upsell_matches_issue_worked_example(self):
        """87 atoms / 12 tours @growth(3/week) -> 7 months. Issue's own example:
        'muốn 5 bài/tuần -> license thêm ~8 tour' -- verifies the endpoint
        reproduces that exact number, not an invented one."""
        conn = AsyncMock()
        conn.fetchrow.return_value = {"tenant_id": TENANT_ID, "plan_tier": "growth"}
        conn.fetch.return_value = [{"tour_id": uuid.uuid4(), "assigned_angle": "culinary_people"} for _ in range(12)]
        conn.fetchval.return_value = 87
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin.get_tenant_mirror(TENANT_ID, request, x_admin_secret=_TEST_SECRET)

        assert result["upsell_suggestion"]["next_plan_tier"] == "business"
        assert result["upsell_suggestion"]["next_posts_per_week"] == 5
        assert result["upsell_suggestion"]["additional_atoms_needed"] == 53
        assert result["upsell_suggestion"]["additional_tours_needed_estimate"] == 8

    @pytest.mark.asyncio
    async def test_no_upsell_at_top_tier(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"tenant_id": TENANT_ID, "plan_tier": "enterprise"}
        conn.fetch.return_value = [{"tour_id": TOUR_A, "assigned_angle": None}]
        conn.fetchval.return_value = 30
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin.get_tenant_mirror(TENANT_ID, request, x_admin_secret=_TEST_SECRET)
        assert result["upsell_suggestion"] is None


class TestGateAApprove:
    @pytest.mark.asyncio
    async def test_no_onboarding_row_404(self):
        conn = _make_conn()
        conn.fetchrow.return_value = None
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.GateAApproveRequest(approved_by="Ms. Thu")
        with pytest.raises(HTTPException) as exc:
            await admin.approve_gate_a(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_angle_assigned_rejected_400(self):
        conn = _make_conn()
        conn.fetchrow.return_value = {"approval_status": "pending"}
        conn.fetchval.return_value = None  # no row has assigned_angle set
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.GateAApproveRequest(approved_by="Ms. Thu")
        with pytest.raises(HTTPException) as exc:
            await admin.approve_gate_a(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_approve_success_sets_is_active_true(self):
        conn = _make_conn()
        conn.fetchrow.side_effect = [
            {"approval_status": "pending"},
            {
                "tenant_id": TENANT_ID, "portfolio_id": PORTFOLIO_ID, "approval_status": "approved",
                "approved_by": "Ms. Thu", "approved_at": __import__("datetime").datetime(2026, 8, 8),
                "created_at": __import__("datetime").datetime(2026, 8, 8),
            },
        ]
        conn.fetchval.return_value = 1  # has_angle check passes
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.GateAApproveRequest(approved_by="Ms. Thu")
        result = await admin.approve_gate_a(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)

        assert result["tenant_is_active"] is True
        assert result["approved_by"] == "Ms. Thu"
        update_queries = [c[0][0] for c in conn.execute.call_args_list]
        assert any("SET approval_status = 'approved'" in q for q in update_queries)
        assert any("SET is_active = true" in q for q in update_queries)

    @pytest.mark.asyncio
    async def test_double_approve_rejected_409(self):
        conn = _make_conn()
        conn.fetchrow.return_value = {"approval_status": "approved"}
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.GateAApproveRequest(approved_by="Ms. Thu")
        with pytest.raises(HTTPException) as exc:
            await admin.approve_gate_a(TENANT_ID, body, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 409


class TestGateAStatus:
    @pytest.mark.asyncio
    async def test_not_found_404(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = _make_pool(conn)
        request = _make_request(pool)

        with pytest.raises(HTTPException) as exc:
            await admin.get_gate_a_status(TENANT_ID, request, x_admin_secret=_TEST_SECRET)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_pending_status(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {
            "tenant_id": TENANT_ID, "portfolio_id": PORTFOLIO_ID, "approval_status": "pending",
            "approved_by": None, "approved_at": None,
            "created_at": __import__("datetime").datetime(2026, 8, 8), "is_active": False,
        }
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin.get_gate_a_status(TENANT_ID, request, x_admin_secret=_TEST_SECRET)
        assert result["approval_status"] == "pending"
        assert result["tenant_is_active"] is False
