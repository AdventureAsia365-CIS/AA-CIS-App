"""
Unit tests for verify_tenant_api_key — AA-181 single-header ACP tenant auth.
Uses mock asyncpg connections — no live DB required.
"""
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from api.routers.auth import AA_INTERNAL_ADMIN_SUB, verify_tenant_api_key


def _make_request(headers, fetchrow=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)

    req = MagicMock()
    req.headers = headers
    req.app.state.pool = pool
    return req, conn


@pytest.mark.asyncio
async def test_valid_x_api_key_returns_tenant_context():
    raw_key = "cis_validkey123"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    row = {"tenant_id": "11111111-1111-1111-1111-111111111111", "name": "Acme Travel", "plan_tier": "growth"}
    req, conn = _make_request({"X-API-Key": raw_key}, fetchrow=row)

    with patch.dict("os.environ", {"ADMIN_SECRET": "admin-secret"}):
        result = await verify_tenant_api_key(req)

    assert result["sub"] == row["tenant_id"]
    assert result["tenant_id"] == row["tenant_id"]
    assert result["role"] == "tenant"
    assert result["reviewer_type"] == "tenant_self"
    assert result["actor"] == "Acme Travel"

    conn.fetchrow.assert_awaited_once()
    args, _ = conn.fetchrow.call_args
    assert args[1] == key_hash


@pytest.mark.asyncio
async def test_admin_secret_returns_internal_context():
    req, conn = _make_request({"X-Admin-Secret": "admin-secret"})

    with patch.dict("os.environ", {"ADMIN_SECRET": "admin-secret"}):
        result = await verify_tenant_api_key(req)

    assert result["sub"] == AA_INTERNAL_ADMIN_SUB
    assert result["role"] == "admin"
    assert result["reviewer_type"] == "aa_internal"
    conn.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_x_api_key_returns_401():
    req, _ = _make_request({"X-API-Key": "cis_doesnotexist"}, fetchrow=None)

    with patch.dict("os.environ", {"ADMIN_SECRET": "admin-secret"}):
        with pytest.raises(HTTPException) as exc_info:
            await verify_tenant_api_key(req)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_credentials_returns_401():
    req, conn = _make_request({})

    with patch.dict("os.environ", {"ADMIN_SECRET": "admin-secret"}):
        with pytest.raises(HTTPException) as exc_info:
            await verify_tenant_api_key(req)

    assert exc_info.value.status_code == 401
    conn.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_admin_secret_falls_through_to_401():
    req, _ = _make_request({"X-Admin-Secret": "wrong-secret"})

    with patch.dict("os.environ", {"ADMIN_SECRET": "admin-secret"}):
        with pytest.raises(HTTPException) as exc_info:
            await verify_tenant_api_key(req)

    assert exc_info.value.status_code == 401
