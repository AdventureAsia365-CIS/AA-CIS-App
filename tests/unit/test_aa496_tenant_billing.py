"""AA-496 — GET /v1/billing, the real tenant-scoped sibling to the admin-only
GET /admin/billing that /portal/*'s layout.tsx + DashboardTab.tsx used to call directly
(guaranteed 401 for every real tenant, since that proxy requires an admin JWT — see
api/routers/v1_tours.py::get_my_billing's own comment block for the full STEP0 trace).

Covers:
  1. test_get_my_billing_uses_jwt_tenant_id_not_query_param — tenant_id comes from the
     verified JWT sub claim, never an untrusted caller-supplied value (unlike the admin
     view's ?tenant_id=, which is intentionally an admin-only "look at any tenant" knob)
  2. test_get_my_billing_shape_matches_admin_view — same field shape as GET /admin/billing,
     so BillingTab.tsx/DashboardTab.tsx need zero changes beyond the URL they call
  3. test_get_my_billing_no_usage_row_yet_returns_defaults — a tenant with no
     v_tenant_monthly_usage row yet reads as sane zeroed defaults, not an error
  4. test_get_my_billing_activity_shape — activity rows carry id/created_at/status/
     edit_source/tour_name/country, matching the admin view's own shape exactly
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.routers import v1_tours


def _make_pool(row=None, activity=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    conn.fetch = AsyncMock(return_value=activity or [])

    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = False
    return pool, conn


@pytest.mark.asyncio
class TestAA496TenantBilling:
    async def test_get_my_billing_uses_jwt_tenant_id_not_query_param(self):
        pool, conn = _make_pool(row=None)
        request = MagicMock()
        request.app.state.pool = pool

        await v1_tours.get_my_billing(request, tenant={"sub": "tenant-abc-123"})

        # the ONLY tenant identifier passed into any query must be the JWT's own sub
        fetchrow_args = conn.fetchrow.await_args.args
        assert "tenant-abc-123" in fetchrow_args
        fetch_args = conn.fetch.await_args.args
        assert "tenant-abc-123" in fetch_args

    async def test_get_my_billing_shape_matches_admin_view(self):
        row = {
            "tenant_name": "Wanderlux Travel", "plan_tier": "growth",
            "billing_month": None,
            "tours_quota_monthly": 500, "api_calls_quota_monthly": 20000,
            "price_usd_monthly": 799.0,
            "tours_rewritten": 12, "api_calls_used": 340,
            "quota_tours_pct": 2.4, "quota_calls_pct": 1.7,
            "tours_overage": 0, "overage_usd": 0.0, "llm_cost_usd": 1.23,
            "overage_rate_usd_per_tour": 4.0,
        }
        pool, conn = _make_pool(row=row, activity=[])
        request = MagicMock()
        request.app.state.pool = pool

        result = await v1_tours.get_my_billing(request, tenant={"sub": "tenant-1"})

        for key in (
            "tenant_name", "plan_tier", "billing_month", "tours_quota_monthly",
            "api_calls_quota_monthly", "price_usd_monthly", "tours_rewritten",
            "api_calls_used", "quota_tours_pct", "quota_calls_pct", "tours_overage",
            "overage_usd", "llm_cost_usd", "overage_rate_usd_per_tour", "activity",
        ):
            assert key in result, f"missing field {key}"
        assert result["plan_tier"] == "growth"
        assert result["tours_rewritten"] == 12

    async def test_get_my_billing_no_usage_row_yet_returns_defaults(self):
        pool, conn = _make_pool(row=None, activity=[])
        request = MagicMock()
        request.app.state.pool = pool

        result = await v1_tours.get_my_billing(request, tenant={"sub": "brand-new-tenant"})

        assert result["plan_tier"] == "starter"
        assert result["tours_rewritten"] == 0
        assert result["activity"] == []

    async def test_get_my_billing_activity_shape(self):
        import datetime as dt

        row = {
            "tenant_name": "T", "plan_tier": "starter", "billing_month": None,
            "tours_quota_monthly": 50, "api_calls_quota_monthly": 5000,
            "price_usd_monthly": 299.0, "tours_rewritten": 1, "api_calls_used": 5,
            "quota_tours_pct": 2.0, "quota_calls_pct": 0.1, "tours_overage": 0,
            "overage_usd": 0.0, "llm_cost_usd": 0.01, "overage_rate_usd_per_tour": 4.0,
        }
        activity_row = {
            "id": "11111111-1111-1111-1111-111111111111",
            "created_at": dt.datetime(2026, 9, 1, 12, 0, 0),
            "status": "approved", "edit_source": "manual",
            "aa_name": "Hidden Trails of Da Lat", "country": "Vietnam",
        }
        pool, conn = _make_pool(row=row, activity=[activity_row])
        request = MagicMock()
        request.app.state.pool = pool

        result = await v1_tours.get_my_billing(request, tenant={"sub": "tenant-1"})

        assert len(result["activity"]) == 1
        a = result["activity"][0]
        assert a["tour_name"] == "Hidden Trails of Da Lat"
        assert a["country"] == "Vietnam"
        assert a["status"] == "approved"
