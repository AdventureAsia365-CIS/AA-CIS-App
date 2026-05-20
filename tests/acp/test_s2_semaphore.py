"""
test_s2_semaphore: 3rd concurrent run from the same tenant should return 429 CONCURRENCY_LIMIT.
Tests the router's synchronous semaphore pre-check.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


TENANT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
TENANT = {"sub": TENANT_ID, "role": "admin"}
_RUN_ID = "bbbbbbbb-0000-0000-0000-000000000001"


def _ctx(conn):
    """Wrap a mock connection in an async context manager."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _idem_conn(existing=None):
    """Connection for idempotency SELECT (no existing key)."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=existing)
    return _ctx(conn)


def _insert_conn(run_id=_RUN_ID):
    """Connection for acp_runs INSERT RETURNING + idempotency_keys INSERT."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"run_id": run_id})
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    return _ctx(conn)


def _make_request(pool):
    req = MagicMock()
    req.app.state.pool = pool
    req.headers = {}
    return req


@pytest.mark.asyncio
async def test_semaphore_allows_two_concurrent():
    """First two runs for a tenant should succeed (HTTP 200)."""
    from services.acp.s2.router import run_s2, RunS2Request
    from acpcore.concurrency import _semaphores

    # Ensure fresh semaphore for this tenant
    if TENANT_ID in _semaphores:
        del _semaphores[TENANT_ID]

    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=[_idem_conn(), _insert_conn()])
    request = _make_request(pool)

    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value={})
    request.app.state.s2_graph = mock_graph

    with patch("asyncio.create_task"):
        result = await run_s2(
            body=RunS2Request(country="Thailand"),
            request=request,
            tenant=TENANT,
        )
    assert result["status"] == "running"


@pytest.mark.asyncio
async def test_semaphore_blocks_third_run():
    """Third concurrent run for same tenant should raise 429."""
    from services.acp.s2.router import run_s2, RunS2Request
    from acpcore.concurrency import _semaphores

    # Pre-fill the semaphore to simulate 2 active runs (value = 0)
    sem = asyncio.Semaphore(2)
    await sem.acquire()
    await sem.acquire()
    _semaphores[TENANT_ID] = sem

    pool = MagicMock()
    request = _make_request(pool)

    with pytest.raises(HTTPException) as exc_info:
        await run_s2(
            body=RunS2Request(country="Vietnam"),
            request=request,
            tenant=TENANT,
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error_code"] == "CONCURRENCY_LIMIT"

    # Cleanup
    sem.release()
    sem.release()
    del _semaphores[TENANT_ID]
