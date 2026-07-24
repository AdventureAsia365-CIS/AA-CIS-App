"""
tests/unit/test_aa298_sweeper.py — services/acp_produce/sweeper_lambda.py
(AA-298 Nhóm 5).
"""
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_produce.sweeper_lambda import _sweep_async, handler

DSN = "postgresql://user:pass@host:5432/db"


def _stuck_row(run_id="11111111-1111-1111-1111-111111111111", slot_id="slot-1", minutes_ago=90):
    return {
        "id": "cp-uuid-1", "run_id": run_id, "item_id": slot_id,
        "created_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago + 5),
        "updated_at": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago),
    }


@pytest.mark.asyncio
async def test_sweep_marks_stuck_slot_failed_and_returns_it():
    conn = AsyncMock()
    conn.fetch.return_value = [_stuck_row()]
    conn.execute = AsyncMock()

    with patch("asyncpg.connect", new=AsyncMock(return_value=conn)):
        swept = await _sweep_async(DSN, sla_hours=1.0)

    assert len(swept) == 1
    assert swept[0]["slot_id"] == "slot-1"
    conn.execute.assert_awaited_once()
    update_call = conn.execute.call_args
    assert "UPDATE" in update_call.args[0]
    assert "SLA" in update_call.args[1]  # error_msg mentions the sweep reason
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_sweep_no_stuck_slots_returns_empty_no_update():
    conn = AsyncMock()
    conn.fetch.return_value = []

    with patch("asyncpg.connect", new=AsyncMock(return_value=conn)):
        swept = await _sweep_async(DSN, sla_hours=1.0)

    assert swept == []
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_sweep_queries_only_produce_slot_item_type_and_running_status():
    conn = AsyncMock()
    conn.fetch.return_value = []

    with patch("asyncpg.connect", new=AsyncMock(return_value=conn)):
        await _sweep_async(DSN, sla_hours=2.5)

    query_call = conn.fetch.call_args
    query_sql = query_call.args[0]
    assert "item_type" in query_sql and "status" in query_sql and "'running'" in query_sql
    assert query_call.args[1] == "produce_slot"
    assert query_call.args[2] == "2.5"


def test_handler_publishes_alert_only_when_slots_were_swept():
    with patch("services.acp_produce.sweeper_lambda._get_dsn", return_value=DSN), \
         patch("services.acp_produce.sweeper_lambda._sweep_async", new=AsyncMock(return_value=[{"slot_id": "x"}])), \
         patch("services.acp_produce.sweeper_lambda._publish_alert") as mock_alert:
        result = handler({}, None)

    assert result["status"] == "OK"
    assert result["swept_count"] == 1
    mock_alert.assert_called_once()


def test_handler_no_alert_when_nothing_swept():
    with patch("services.acp_produce.sweeper_lambda._get_dsn", return_value=DSN), \
         patch("services.acp_produce.sweeper_lambda._sweep_async", new=AsyncMock(return_value=[])), \
         patch("services.acp_produce.sweeper_lambda._publish_alert") as mock_alert:
        result = handler({}, None)

    assert result["swept_count"] == 0
    mock_alert.assert_not_called()


def test_handler_returns_error_status_on_sweep_failure_not_raise():
    with patch("services.acp_produce.sweeper_lambda._get_dsn", return_value=DSN), \
         patch("services.acp_produce.sweeper_lambda._sweep_async", new=AsyncMock(side_effect=RuntimeError("db down"))):
        result = handler({}, None)

    assert result["status"] == "ERROR"
    assert "db down" in result["error"]


def test_publish_alert_skips_when_sns_arn_not_configured():
    with patch("services.acp_produce.sweeper_lambda.SWEEPER_ALERT_SNS_ARN", ""), \
         patch("services.acp_produce.sweeper_lambda.boto3.client") as mock_boto:
        from services.acp_produce.sweeper_lambda import _publish_alert
        _publish_alert([{"slot_id": "x"}])
    mock_boto.assert_not_called()
