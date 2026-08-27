"""AA-309 [N1] — tenant onboarding endpoints (api/routers/admin.py).

Mocks the asyncpg pool per the pool.acquire() convention established in
test_aa300_admin_atoms.py — no live DB, no LLM. Auth is exercised against the
real verify_admin_secret() from the same module.

AA-472 (Hướng B): seed-atoms/assign-angle/mirror endpoints and their tests are removed —
portfolio seeding was never required, and angle was found to be the wrong concept at the
tenant level.

AA-473: Gate A removed entirely (ADR-2026-038 §0.2) -- create_tenant() now inserts
is_active=true directly, no approval step, no acp_shared.tenant_onboarding table. All
Gate A-specific test classes (TestCreateTenantIsInactive, TestGateAApprove, TestGateAStatus,
TestListTenantsPending, TestUpdateTenantGateAGuard) removed with the code they tested;
TestCreateTenantIsActive added below in their place.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.routers import admin

_TEST_SECRET = "test-admin-secret"

TENANT_ID = uuid.uuid4()


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


class TestCreateTenantIsActive:
    """AA-473: Gate A removed -- a new tenant is active immediately, no onboarding row."""

    @pytest.mark.asyncio
    async def test_new_tenant_is_active_true(self):
        conn = _make_conn()
        # slug-existing check -> None, INSERT RETURNING -> TENANT_ID, has_rules check -> None (no
        # existing brand_rules row for this brand-new tenant)
        conn.fetchval.side_effect = [None, TENANT_ID, None]
        pool = _make_pool(conn)
        request = _make_request(pool)

        body = admin.CreateTenantRequest(name="Test Agency", slug="test-agency", posts_per_week=4)
        result = await admin.create_tenant(body, request, x_admin_secret=_TEST_SECRET)

        assert result.is_active is True
        assert result.posts_per_week == 4
        insert_args = conn.fetchval.call_args_list[1][0]
        assert "VALUES ($1, $2, $3::plan_tier_enum, $4, $5, $6, true)" in insert_args[0]
        assert insert_args[4] == 4  # posts_per_week bound param
