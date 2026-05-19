"""
Unit tests for v1_competitors router logic.
Uses mock asyncpg connections — no live DB required.
Covers: max-10 enforcement, ownership validation on PATCH/DELETE.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_pool(fetchval=None, fetchrow=None, fetch=None, execute=None):
    """Return a mock pool whose acquire() context manager yields a mock conn."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=fetchval)
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.fetch    = AsyncMock(return_value=fetch or [])
    conn.execute  = AsyncMock(return_value=execute or "UPDATE 1")

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


def _make_request(pool):
    req = MagicMock()
    req.app.state.pool = pool
    req.headers = {}
    return req


TENANT = {"sub": "00000000-0000-0000-0000-000000000001", "role": "tenant"}


# ── add_competitor: max-10 enforcement ───────────────────────────────────────

@pytest.mark.asyncio
async def test_add_competitor_rejects_at_limit():
    """POST /v1/competitors raises 422 when active count >= 10."""
    from api.routers.v1_competitors import add_competitor, AddCompetitorRequest

    pool, _ = _make_pool(fetchval=10)   # count = 10 → at limit
    req = _make_request(pool)
    body = AddCompetitorRequest(country="Vietnam", url="https://example.com", label="Ex")

    with pytest.raises(HTTPException) as exc_info:
        await add_competitor(body, req, TENANT)

    assert exc_info.value.status_code == 422
    assert "10" in exc_info.value.detail


@pytest.mark.asyncio
async def test_add_competitor_accepts_below_limit():
    """POST /v1/competitors succeeds when active count < 10."""
    from api.routers.v1_competitors import add_competitor, AddCompetitorRequest
    import datetime

    fake_row = {
        "id":         "aaaaaaaa-0000-0000-0000-000000000001",
        "country":    "Vietnam",
        "url":        "https://example.com",
        "label":      "Ex",
        "is_active":  True,
        "created_at": datetime.datetime(2026, 5, 19, 12, 0, 0),
    }
    pool, conn = _make_pool(fetchval=9, fetchrow=fake_row)   # count = 9 → allowed
    req = _make_request(pool)
    body = AddCompetitorRequest(country="Vietnam", url="https://example.com", label="Ex")

    result = await add_competitor(body, req, TENANT)

    assert result["url"] == "https://example.com"
    assert result["is_active"] is True


@pytest.mark.asyncio
async def test_add_competitor_rejects_invalid_url():
    """POST /v1/competitors raises 400 for non-http URLs."""
    from api.routers.v1_competitors import add_competitor, AddCompetitorRequest

    pool, _ = _make_pool(fetchval=0)
    req = _make_request(pool)
    body = AddCompetitorRequest(country="Vietnam", url="ftp://bad.com")

    with pytest.raises(HTTPException) as exc_info:
        await add_competitor(body, req, TENANT)

    assert exc_info.value.status_code == 400


# ── update_competitor: ownership validation ───────────────────────────────────

@pytest.mark.asyncio
async def test_update_competitor_returns_404_when_not_owner():
    """PATCH /v1/competitors/{id} raises 404 when row not found for tenant."""
    from api.routers.v1_competitors import update_competitor, UpdateCompetitorRequest

    pool, conn = _make_pool(fetchrow=None)   # UPDATE returns nothing → not owned
    req = _make_request(pool)
    body = UpdateCompetitorRequest(label="New label")

    with pytest.raises(HTTPException) as exc_info:
        await update_competitor("some-uuid", body, req, TENANT)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_competitor_succeeds_for_owner():
    """PATCH /v1/competitors/{id} returns updated row when tenant owns it."""
    from api.routers.v1_competitors import update_competitor, UpdateCompetitorRequest
    import datetime

    fake_row = {
        "id":         "aaaaaaaa-0000-0000-0000-000000000001",
        "country":    "Thailand",
        "url":        "https://competitor.com",
        "label":      "New label",
        "is_active":  True,
        "updated_at": datetime.datetime(2026, 5, 19, 13, 0, 0),
    }
    pool, _ = _make_pool(fetchrow=fake_row)
    req = _make_request(pool)
    body = UpdateCompetitorRequest(label="New label")

    result = await update_competitor("aaaaaaaa-0000-0000-0000-000000000001", body, req, TENANT)

    assert result["label"] == "New label"


@pytest.mark.asyncio
async def test_update_competitor_rejects_empty_body():
    """PATCH /v1/competitors/{id} raises 400 when no fields provided."""
    from api.routers.v1_competitors import update_competitor, UpdateCompetitorRequest

    pool, _ = _make_pool()
    req = _make_request(pool)
    body = UpdateCompetitorRequest()   # both None

    with pytest.raises(HTTPException) as exc_info:
        await update_competitor("some-uuid", body, req, TENANT)

    assert exc_info.value.status_code == 400


# ── delete_competitor: ownership validation ───────────────────────────────────

@pytest.mark.asyncio
async def test_delete_competitor_returns_404_when_not_owner():
    """DELETE /v1/competitors/{id} raises 404 when row not found for tenant."""
    from api.routers.v1_competitors import delete_competitor

    pool, _ = _make_pool(execute="UPDATE 0")
    req = _make_request(pool)

    with pytest.raises(HTTPException) as exc_info:
        await delete_competitor("some-uuid", req, TENANT)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_competitor_succeeds_for_owner():
    """DELETE /v1/competitors/{id} returns None (204) when tenant owns it."""
    from api.routers.v1_competitors import delete_competitor

    pool, _ = _make_pool(execute="UPDATE 1")
    req = _make_request(pool)

    result = await delete_competitor("some-uuid", req, TENANT)
    assert result is None
