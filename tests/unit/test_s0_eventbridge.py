"""
Unit tests for S0 EventBridge retry logic + stuck-run detection — AA-123.
"""
import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_pool_with_rows(rows):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    conn.fetchval = AsyncMock(return_value=None)
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


def _make_request(pool):
    req = MagicMock()
    req.app.state.pool = pool
    req.headers = {}
    return req


# ── test_publish_s0_retry_success_first_attempt ───────────────────────────────

@pytest.mark.asyncio
async def test_publish_s0_retry_success_first_attempt():
    """EventBridge succeeds on first attempt — returns True, put_events called once."""
    mock_eb = MagicMock()
    mock_eb.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "abc-123"}]}

    with patch("boto3.client", return_value=mock_eb):
        from services.acp.handler import publish_s0_completed_with_retry
        result = await publish_s0_completed_with_retry(
            run_id="00000000-0000-0000-0000-000000000001",
            payload={"country": "Vietnam", "tenant_id": "t1"},
        )

    assert result is True
    assert mock_eb.put_events.call_count == 1
    call_kwargs = mock_eb.put_events.call_args[1]
    entry = call_kwargs["Entries"][0]
    assert entry["Source"] == "acp.s0"
    assert entry["DetailType"] == "acp.s0.completed"


# ── test_publish_s0_retry_exhausted_marks_failed ──────────────────────────────

@pytest.mark.asyncio
async def test_publish_s0_retry_exhausted_marks_failed():
    """3 retries all raise — _update_run_failed called once with correct message."""
    mock_eb = MagicMock()
    mock_eb.put_events.side_effect = RuntimeError("Connection refused")

    with patch("boto3.client", return_value=mock_eb), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
         patch("services.acp.handler._update_run_failed", new_callable=AsyncMock) as mock_fail:
        from services.acp import handler as h
        with pytest.raises(RuntimeError, match="Connection refused"):
            await h.publish_s0_completed_with_retry(
                run_id="00000000-0000-0000-0000-000000000002",
                payload={"country": "Thailand"},
                max_retries=3,
            )

    assert mock_eb.put_events.call_count == 3
    assert mock_sleep.call_count == 2  # sleeps between attempts 1→2 and 2→3 only
    mock_fail.assert_called_once()
    fail_run_id, fail_msg = mock_fail.call_args[0]
    assert fail_run_id == "00000000-0000-0000-0000-000000000002"
    assert "failed after 3 retries" in fail_msg


# ── test_stuck_run_detection_returns_correct_runs ─────────────────────────────

@pytest.mark.asyncio
async def test_stuck_run_detection_returns_correct_runs():
    """Stuck-run endpoint returns run rows older than 30 min with s1_pending status."""
    old_dt = datetime.datetime(2026, 6, 5, 10, 0, 0, tzinfo=datetime.timezone.utc)
    fake_rows = [
        {
            "run_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "status": "s1_pending",
            "started_at": old_dt,
            "age_minutes": 45.3,
        }
    ]
    pool, _ = _make_pool_with_rows(fake_rows)
    request = _make_request(pool)

    with patch("api.routers.admin_pipeline.verify_admin_secret"):
        from api.routers.admin_pipeline import get_stuck_runs
        result = await get_stuck_runs(request, x_admin_secret="test-secret")

    assert result["count"] == 1
    run = result["stuck_runs"][0]
    assert run["run_id"] == "aaaaaaaa-0000-0000-0000-000000000001"
    assert run["status"] == "s1_pending"
    assert run["age_minutes"] == 45.3
    assert run["started_at"] == old_dt.isoformat()


# ── test_force_fail_updates_run_status ────────────────────────────────────────

@pytest.mark.asyncio
async def test_force_fail_updates_run_status():
    """force-fail endpoint calls UPDATE and returns status=failed."""
    run_id = "bbbbbbbb-0000-0000-0000-000000000001"
    pool, conn = _make_pool_with_rows([])
    conn.fetchval = AsyncMock(return_value=run_id)
    request = _make_request(pool)

    with patch("api.routers.admin_pipeline.verify_admin_secret"):
        from api.routers.admin_pipeline import force_fail_acp_run, ForceFailRequest
        body = ForceFailRequest(reason="Manually failed — S0 EventBridge publish timed out")
        result = await force_fail_acp_run(run_id, body, request, x_admin_secret="test-secret")

    assert result["run_id"] == run_id
    assert result["status"] == "failed"
    assert "EventBridge" in result["reason"]
    conn.fetchval.assert_called_once()
