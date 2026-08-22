"""
AA-432 — Redis per-tenant rate-limit + revoke, api/middleware/rate_limit.py.

STEP0 (docs/claude_audit/AA-432-api-gateway-401-step0.md) found the API Gateway's
X-API-Key gate on /v1/* was redundant — get_tenant() already verifies the JWT itself
and never consulted the gateway authorizer's context. That gate is removed (Terraform,
AA-CIS-Infra); this test file covers what replaces its two jobs at the app layer:
per-tenant rate limiting (using the real shared.tenants.rate_limit_rpm, not a
plan-tier bucket) and revoke (shared.tenants.is_active checked every request, not
just at login).

Tests:
  1. test_deactivated_tenant_blocked_403       — is_active=false -> 403, no rate-limit check reached
  2. test_active_tenant_uses_real_rpm_from_db  — rate_limit_rpm from shared.tenants, not PLAN_RPM
  3. test_tenant_meta_cached_in_redis          — second call hits Redis cache, not the DB
  4. test_fail_open_when_meta_lookup_fails     — Redis AND DB both down -> falls back to PLAN_RPM,
                                                  does not 403 (is_active check never bypasses to
                                                  a block on infra failure — the opposite: it fails
                                                  open, same posture as the pre-existing Redis-error
                                                  handling for the rate-limit counter itself)
  5. test_over_limit_still_returns_429_not_401 — rate limit breach is 429, not 401/403
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_request(path="/v1/tours/pool", token="fake.jwt.token"):
    request = MagicMock()
    request.url.path = path
    request.headers = {"Authorization": f"Bearer {token}"}
    request.app.state.redis = AsyncMock()
    request.app.state.pool = MagicMock()
    return request


def _jwt_payload():
    return {"sub": "9fb0a3db-59aa-468a-a082-ded01ac50bee", "plan_tier": "starter", "role": "tenant"}


@pytest.mark.asyncio
class TestAA432RateLimitRevoke:
    async def test_deactivated_tenant_blocked_403(self):
        from api.middleware import rate_limit

        request = _make_request()
        request.app.state.redis.get = AsyncMock(return_value=None)  # cache miss
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"rate_limit_rpm": 60, "is_active": False})
        request.app.state.pool.acquire.return_value.__aenter__.return_value = conn

        call_next = AsyncMock()

        with patch.object(rate_limit, "verify_jwt", return_value=_jwt_payload()):
            resp = await rate_limit.rate_limit_middleware(request, call_next)

        assert resp.status_code == 403
        call_next.assert_not_awaited()  # blocked before the request ever reaches the route

    async def test_active_tenant_uses_real_rpm_from_db(self):
        from api.middleware import rate_limit

        request = _make_request()
        request.app.state.redis.get = AsyncMock(return_value=None)
        request.app.state.redis.set = AsyncMock()
        # rate_limit_rpm=5 is far below PLAN_RPM["starter"]=60 — if the code were
        # still using PLAN_RPM this request would NOT be rate-limited at count=6.
        request.app.state.redis.incr = AsyncMock(return_value=6)
        request.app.state.redis.expire = AsyncMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"rate_limit_rpm": 5, "is_active": True})
        request.app.state.pool.acquire.return_value.__aenter__.return_value = conn

        call_next = AsyncMock()

        with patch.object(rate_limit, "verify_jwt", return_value=_jwt_payload()), \
             patch.object(rate_limit, "track_api_call", new=AsyncMock()):
            resp = await rate_limit.rate_limit_middleware(request, call_next)

        assert resp.status_code == 429
        assert "5 RPM" in resp.body.decode()

    async def test_tenant_meta_cached_in_redis(self):
        from api.middleware import rate_limit

        request = _make_request()
        cached = json.dumps({"rate_limit_rpm": 42, "is_active": True})
        request.app.state.redis.get = AsyncMock(return_value=cached)
        request.app.state.redis.incr = AsyncMock(return_value=1)
        request.app.state.redis.expire = AsyncMock()

        call_next = AsyncMock(return_value=MagicMock(status_code=200, headers={}))

        with patch.object(rate_limit, "verify_jwt", return_value=_jwt_payload()), \
             patch.object(rate_limit, "track_api_call", new=AsyncMock()):
            await rate_limit.rate_limit_middleware(request, call_next)

        request.app.state.pool.acquire.assert_not_called()  # DB never touched — cache hit

    async def test_fail_open_when_meta_lookup_fails(self):
        from api.middleware import rate_limit

        request = _make_request()
        request.app.state.redis.get = AsyncMock(side_effect=Exception("redis down"))
        request.app.state.pool.acquire.side_effect = Exception("db down")
        request.app.state.redis.incr = AsyncMock(return_value=1)
        request.app.state.redis.expire = AsyncMock()

        call_next = AsyncMock(return_value=MagicMock(status_code=200, headers={}))

        with patch.object(rate_limit, "verify_jwt", return_value=_jwt_payload()), \
             patch.object(rate_limit, "track_api_call", new=AsyncMock()):
            resp = await rate_limit.rate_limit_middleware(request, call_next)

        # Both lookups failed -> fail open, PLAN_RPM["starter"]=60 path taken, request proceeds
        assert resp.status_code == 200

    async def test_over_limit_still_returns_429_not_401(self):
        from api.middleware import rate_limit

        request = _make_request()
        request.app.state.redis.get = AsyncMock(return_value=None)
        request.app.state.redis.set = AsyncMock()
        request.app.state.redis.incr = AsyncMock(return_value=999)
        request.app.state.redis.expire = AsyncMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"rate_limit_rpm": 60, "is_active": True})
        request.app.state.pool.acquire.return_value.__aenter__.return_value = conn

        call_next = AsyncMock()

        with patch.object(rate_limit, "verify_jwt", return_value=_jwt_payload()), \
             patch.object(rate_limit, "track_api_call", new=AsyncMock()):
            resp = await rate_limit.rate_limit_middleware(request, call_next)

        assert resp.status_code == 429
        assert resp.status_code != 401
