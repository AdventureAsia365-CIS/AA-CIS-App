"""AA-489 — real per-tenant monthly rewrite quota (api/routers/v1_tours.py).

Covers:
  1. test_get_tenant_plan_limit_uses_plan_limits_table  — reads live plan_tier from DB, maps
     through PLAN_LIMITS (starter/growth/business/internal), unknown plan falls back to starter
  2. test_check_and_consume_under_limit_passes          — increments, no exception
  3. test_check_and_consume_over_limit_raises_429        — increment happens, then 429 with a
     clear detail message (used/limit/reset date)
  4. test_check_and_consume_at_exact_limit_passes        — boundary: used == limit is allowed,
     used == limit + 1 is not
  5. test_get_quota_endpoint_shape                       — GET /v1/quota is read-only (no
     INSERT), returns rewrites_remaining/rewrites_used/tours_per_month/plan_tier/resets_at
  6. test_get_quota_no_usage_row_yet_returns_zero_used    — a tenant with no
     tenant_rewrite_usage row yet (hasn't rewritten this month) reads as used=0, not an error
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.routers import v1_tours


def _make_conn(plan_tier="starter", used_count=None):
    conn = AsyncMock()

    async def _fetchval(query, *args):
        if "plan_tier" in query:
            return plan_tier
        if "INSERT INTO shared.tenant_rewrite_usage" in query:
            return used_count
        if "SELECT rewrite_count FROM shared.tenant_rewrite_usage" in query:
            return used_count
        raise AssertionError(f"unexpected query in test double: {query}")

    conn.fetchval = AsyncMock(side_effect=_fetchval)
    return conn


@pytest.mark.asyncio
class TestAA489RewriteQuota:
    async def test_get_tenant_plan_limit_uses_plan_limits_table(self):
        conn = _make_conn(plan_tier="growth")
        plan, limit = await v1_tours._get_tenant_plan_limit(conn, "tenant-1")
        assert plan == "growth"
        assert limit == v1_tours.PLAN_LIMITS["growth"]["tours_per_month"] == 500

    async def test_get_tenant_plan_limit_unknown_plan_falls_back_to_starter(self):
        conn = _make_conn(plan_tier="some-future-tier-not-yet-in-PLAN_LIMITS")
        plan, limit = await v1_tours._get_tenant_plan_limit(conn, "tenant-1")
        assert limit == v1_tours.PLAN_LIMITS["starter"]["tours_per_month"] == 100

    async def test_check_and_consume_under_limit_passes(self):
        conn = _make_conn(plan_tier="starter", used_count=5)  # 5 <= 100
        await v1_tours._check_and_consume_rewrite_quota(conn, "tenant-1")  # no raise

    async def test_check_and_consume_over_limit_raises_429(self):
        from fastapi import HTTPException
        conn = _make_conn(plan_tier="starter", used_count=101)  # 101 > 100
        with pytest.raises(HTTPException) as exc_info:
            await v1_tours._check_and_consume_rewrite_quota(conn, "tenant-1")
        assert exc_info.value.status_code == 429
        assert "100" in exc_info.value.detail  # limit surfaced
        assert "quota" in exc_info.value.detail.lower()

    async def test_check_and_consume_at_exact_limit_passes(self):
        conn = _make_conn(plan_tier="starter", used_count=100)  # == limit, allowed
        await v1_tours._check_and_consume_rewrite_quota(conn, "tenant-1")  # no raise

        from fastapi import HTTPException
        conn2 = _make_conn(plan_tier="starter", used_count=101)  # one past, blocked
        with pytest.raises(HTTPException):
            await v1_tours._check_and_consume_rewrite_quota(conn2, "tenant-1")

    async def test_get_quota_endpoint_shape(self):
        conn = _make_conn(plan_tier="business", used_count=42)
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = conn
        pool.acquire.return_value.__aexit__.return_value = False

        request = MagicMock()
        request.app.state.pool = pool

        result = await v1_tours.get_quota(request, tenant={"sub": "tenant-1"})

        assert result["plan_tier"] == "business"
        assert result["tours_per_month"] == 2000
        assert result["rewrites_used"] == 42
        assert result["rewrites_remaining"] == 2000 - 42
        assert "resets_at" in result
        # read-only: only a SELECT, never the INSERT/UPSERT
        for call in conn.fetchval.await_args_list:
            assert "INSERT" not in call.args[0]

    async def test_get_quota_no_usage_row_yet_returns_zero_used(self):
        conn = _make_conn(plan_tier="starter", used_count=None)  # no row this month
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = conn
        pool.acquire.return_value.__aexit__.return_value = False

        request = MagicMock()
        request.app.state.pool = pool

        result = await v1_tours.get_quota(request, tenant={"sub": "tenant-1"})

        assert result["rewrites_used"] == 0
        assert result["rewrites_remaining"] == 100
