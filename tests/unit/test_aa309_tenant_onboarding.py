"""AA-309 [N1] — tenant onboarding endpoints (api/routers/admin.py).

Mocks the asyncpg pool per the pool.acquire() convention established in
test_aa300_admin_atoms.py — no live DB, no LLM. Auth is exercised against the
real verify_admin_secret() from the same module.

AA-472 (Hướng B): seed-atoms/assign-angle/mirror endpoints and their tests are removed —
portfolio seeding was never required, and angle was found to be the wrong concept at the
tenant level. Gate A approval no longer depends on either.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.routers import admin

_TEST_SECRET = "test-admin-secret"

TENANT_ID = uuid.uuid4()
PORTFOLIO_ID = uuid.uuid4()


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


class TestCreateTenantPostsPerWeek:
    """AA-384: posts_per_week is now a free, caller-supplied value (1-14), not derived from
    plan_tier — POSTS_PER_WEEK_BY_PLAN_TIER was removed entirely."""

    def test_posts_per_week_required(self):
        with pytest.raises(Exception):
            admin.CreateTenantRequest(name="Test Agency", slug="test-agency")

    def test_posts_per_week_out_of_range_rejected(self):
        with pytest.raises(Exception):
            admin.CreateTenantRequest(name="Test Agency", slug="test-agency", posts_per_week=15)
        with pytest.raises(Exception):
            admin.CreateTenantRequest(name="Test Agency", slug="test-agency", posts_per_week=0)

    def test_posts_per_week_need_not_match_any_tier(self):
        """The whole point of AA-384: 4 doesn't match any old tier value (1/3/5/7) and must still
        be accepted."""
        body = admin.CreateTenantRequest(name="Test Agency", slug="test-agency", posts_per_week=4)
        assert body.posts_per_week == 4


class TestCreateTenantIsInactive:
    @pytest.mark.asyncio
    async def test_new_tenant_is_active_false(self):
        conn = _make_conn()
        # slug-existing check -> None, INSERT RETURNING -> TENANT_ID, has_rules check -> None (no
        # existing brand_rules row for this brand-new tenant)
        conn.fetchval.side_effect = [None, TENANT_ID, None]
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.CreateTenantRequest(name="Test Agency", slug="test-agency", posts_per_week=4)
        result = await admin.create_tenant(body, request, x_admin_secret=_TEST_SECRET)

        assert result.is_active is False
        assert result.posts_per_week == 4
        insert_args = conn.fetchval.call_args_list[1][0]
        assert "VALUES ($1, $2, $3::plan_tier_enum, $4, $5, $6, false)" in insert_args[0]
        assert insert_args[4] == 4  # posts_per_week bound param


class TestGateAApprove:
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


class TestListTenantsPending:
    """AA-389 (reopened): GET /admin/tenants used to return active tenants only, so a brand-new
    tenant (is_active=false by Gate A design) vanished from the UI with no way back in. Now also
    returns pending_tenants with real onboarding progress, not inferred from is_active alone."""

    @pytest.mark.asyncio
    async def test_pending_tenant_not_started(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [],  # active tenants
            [{
                "tenant_id": TENANT_ID, "name": "TEST-N1-flow", "slug": "test-n1-flow",
                "plan_tier": "business", "posts_per_week": 3, "country": None,
                "created_at": __import__("datetime").datetime(2026, 8, 12),
                "approval_status": None,
            }],
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin.list_tenants(request, x_admin_secret=_TEST_SECRET)

        assert result["pending_total"] == 1
        p = result["pending_tenants"][0]
        assert p["tenant_id"] == str(TENANT_ID)
        assert p["onboarding"] == {"gate_a_status": "not_started"}

    @pytest.mark.asyncio
    async def test_pending_tenant_gate_a_pending(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [],
            [{
                "tenant_id": TENANT_ID, "name": "TEST-N1-flow", "slug": "test-n1-flow",
                "plan_tier": "business", "posts_per_week": 3, "country": None,
                "created_at": __import__("datetime").datetime(2026, 8, 12),
                "approval_status": "pending",
            }],
        ]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin.list_tenants(request, x_admin_secret=_TEST_SECRET)

        p = result["pending_tenants"][0]
        assert p["onboarding"] == {"gate_a_status": "pending"}

    @pytest.mark.asyncio
    async def test_no_pending_tenants_empty_list(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [[], []]
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin.list_tenants(request, x_admin_secret=_TEST_SECRET)

        assert result["pending_tenants"] == []
        assert result["pending_total"] == 0


class TestUpdateTenantGateAGuard:
    """AA-389: PATCH /tenants/{id} used to be able to activate a tenant with zero Gate A checks —
    a one-click bypass of the REQUIRED/NEVER-auto guarantee gate-a/approve exists to enforce.
    Deactivation must stay unrestricted; activation must only succeed for a tenant whose Gate A
    onboarding row is already 'approved' (a legitimate reactivate-after-suspend, not a bypass)."""

    @pytest.mark.asyncio
    async def test_activate_never_onboarded_tenant_rejected_400(self):
        conn = _make_conn()
        conn.fetchval.return_value = None  # no tenant_onboarding row at all
        pool = _make_pool(conn)
        request = _make_request(pool)

        with pytest.raises(HTTPException) as exc:
            await admin.update_tenant(TENANT_ID, request, x_admin_secret=_TEST_SECRET, is_active=True)
        assert exc.value.status_code == 400
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_activate_pending_gate_a_rejected_400(self):
        conn = _make_conn()
        conn.fetchval.return_value = "pending"
        pool = _make_pool(conn)
        request = _make_request(pool)

        with pytest.raises(HTTPException) as exc:
            await admin.update_tenant(TENANT_ID, request, x_admin_secret=_TEST_SECRET, is_active=True)
        assert exc.value.status_code == 400
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_activate_approved_gate_a_allowed(self):
        conn = _make_conn()
        conn.fetchval.return_value = "approved"
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin.update_tenant(TENANT_ID, request, x_admin_secret=_TEST_SECRET, is_active=True)
        assert result["status"] == "updated"
        conn.execute.assert_called_once()
        assert conn.execute.call_args[0][2] is True  # is_active bound param

    @pytest.mark.asyncio
    async def test_deactivate_never_checks_gate_a(self):
        conn = _make_conn()
        pool = _make_pool(conn)
        request = _make_request(pool)

        result = await admin.update_tenant(TENANT_ID, request, x_admin_secret=_TEST_SECRET, is_active=False)
        assert result["status"] == "updated"
        conn.fetchval.assert_not_called()
        conn.execute.assert_called_once()
        assert conn.execute.call_args[0][2] is False
