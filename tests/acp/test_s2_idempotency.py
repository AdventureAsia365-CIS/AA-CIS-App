"""
test_s2_idempotency: Calling POST /run twice with the same idempotency key should
return the existing run_id on the second call without creating a new DB record.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID


TENANT = {"sub": "11111111-0000-0000-0000-000000000001", "role": "admin"}
EXISTING_RUN_ID = "22222222-0000-0000-0000-000000000001"
IDEM_KEY = "tenant-001:Thailand"


def _make_request(pool):
    req = MagicMock()
    req.app.state.pool = pool
    req.headers = {}
    return req


def _make_pool_with_existing_key():
    """Pool that returns an existing idempotency_key row."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"run_id": UUID(EXISTING_RUN_ID)})
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _make_pool_no_existing_key(run_id: str):
    """Pool that returns no existing idempotency_key and creates a new run.
    Uses separate connections per pool.acquire() call to avoid side_effect ordering issues.
    """
    def _ctx(conn):
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    # Connection 1: idempotency SELECT → None (no duplicate)
    conn1 = AsyncMock()
    conn1.fetchrow = AsyncMock(return_value=None)

    # Connection 2: acp_runs INSERT RETURNING + idempotency_keys INSERT
    conn2 = AsyncMock()
    conn2.fetchrow = AsyncMock(return_value={"run_id": UUID(run_id)})
    conn2.execute = AsyncMock(return_value="INSERT 0 1")

    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=[_ctx(conn1), _ctx(conn2)])
    return pool


@pytest.mark.asyncio
async def test_idempotency_second_call_returns_existing_run():
    """Second POST /run with same idempotency_key returns the first run_id, status='existing'."""
    from services.acp.s2.router import run_s2, RunS2Request
    from acpcore.concurrency import _semaphores

    tenant_id = str(TENANT["sub"])
    # Ensure semaphore has capacity
    if tenant_id in _semaphores:
        del _semaphores[tenant_id]

    pool = _make_pool_with_existing_key()
    request = _make_request(pool)

    result = await run_s2(
        body=RunS2Request(country="Thailand", idempotency_key=IDEM_KEY),
        request=request,
        tenant=TENANT,
    )

    assert result["status"] == "existing"
    assert result["run_id"] == EXISTING_RUN_ID
    assert result["idempotency_key"] == IDEM_KEY


@pytest.mark.asyncio
async def test_idempotency_first_call_creates_run():
    """First POST /run creates a new run and stores the idempotency key."""
    from services.acp.s2.router import run_s2, RunS2Request
    from acpcore.concurrency import _semaphores

    new_run_id = "33333333-0000-0000-0000-000000000001"
    tenant_id = str(TENANT["sub"])

    if tenant_id in _semaphores:
        del _semaphores[tenant_id]

    pool = _make_pool_no_existing_key(new_run_id)
    request = _make_request(pool)

    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value={})
    request.app.state.s2_graph = mock_graph

    with patch("asyncio.create_task"):
        result = await run_s2(
            body=RunS2Request(country="Thailand", idempotency_key=IDEM_KEY),
            request=request,
            tenant=TENANT,
        )

    assert result["status"] == "running"
    assert result["run_id"] == new_run_id


@pytest.mark.asyncio
async def test_idempotency_default_key_is_tenant_country():
    """When no idempotency_key provided, default key is '{tenant_id}:{country}'."""
    from services.acp.s2.router import run_s2, RunS2Request
    from acpcore.concurrency import _semaphores

    new_run_id = "44444444-0000-0000-0000-000000000001"
    tenant_id = str(TENANT["sub"])
    expected_key = f"{tenant_id}:Vietnam"

    if tenant_id in _semaphores:
        del _semaphores[tenant_id]

    # Build pool with explicit connection objects so we can inspect calls
    def _ctx(conn):
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    conn1 = AsyncMock()
    conn1.fetchrow = AsyncMock(return_value=None)  # no existing idempotency key

    conn2 = AsyncMock()
    conn2.fetchrow = AsyncMock(return_value={"run_id": UUID(new_run_id)})
    conn2.execute = AsyncMock(return_value="INSERT 0 1")

    pool = MagicMock()
    pool.acquire = MagicMock(side_effect=[_ctx(conn1), _ctx(conn2)])
    request = _make_request(pool)

    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value={})
    request.app.state.s2_graph = mock_graph

    with patch("asyncio.create_task"):
        result = await run_s2(
            body=RunS2Request(country="Vietnam"),
            request=request,
            tenant=TENANT,
        )

    assert result["status"] == "running"

    # Verify conn2.execute was called with the expected idempotency key
    execute_calls = conn2.execute.call_args_list
    idem_call = next(
        (c for c in execute_calls if "idempotency_keys" in str(c)),
        None,
    )
    assert idem_call is not None, "idempotency_keys INSERT not called"
    # First positional arg after the SQL is the key
    call_args = idem_call.args
    assert expected_key in call_args, (
        f"Expected key {expected_key!r} in INSERT args: {call_args}"
    )
