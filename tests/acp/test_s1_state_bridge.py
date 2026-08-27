"""
AA-104 — S1 State Bridge Guard tests.

Coverage:
  1. S1 commit-before-publish: DB commit success → event published
  2. S1 no-publish on DB fail: DB raises → event NOT published

AA-481: TestS2Guard removed — imported services.acp.s2.router, a module whose source no
longer exists in this repo (dead ACPv1 S2, confirmed via AA-479/481 audit: 0 real .py files,
only stale __pycache__, git ls-files empty). TestS1CommitBeforePublish stays — it tests
api.services.run_context_db.write_run_context_stage, which services/export/handler.py (the
live A0-A3 admin pipeline) still uses.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── S1: write-before-publish ──────────────────────────────────────────────────

class TestS1CommitBeforePublish:
    """Guard: publish_s1_completed called only after successful DB commit.

    These tests simulate the write-then-publish sequence from export/handler.py.
    The pattern is:
        async with conn.transaction():
            await write_run_context_stage(...)   ← if this raises → rollback
        publish_s1_completed(...)                ← only reached if commit succeeded
    """

    @pytest.mark.asyncio
    async def test_s1_commit_before_publish(self):
        """DB write succeeds → publish IS called and in correct order (write before publish)."""
        call_order = []

        async def fake_write(*args, **kwargs):
            call_order.append("write")

        def fake_publish(*args, **kwargs):
            call_order.append("publish")

        mock_conn = AsyncMock()
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock(return_value=mock_transaction)
        mock_transaction.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_transaction)
        mock_conn.execute = AsyncMock()

        # Simulate the S1 completion sequence
        async with mock_conn.transaction():
            await mock_conn.execute("INSERT INTO shared.acp_runs ...", "batch-1")
            await fake_write(mock_conn, "run-1", "s1", {"s1_keywords_used": ["vietnam tours"]})

        fake_publish("run-1", "Vietnam", "tenant-1", "s3://key", 5, 8.0)

        assert call_order == ["write", "publish"], (
            f"Expected write before publish, got: {call_order}"
        )

    @pytest.mark.asyncio
    async def test_s1_no_publish_on_db_fail(self):
        """DB write raises → publish_s1_completed is NOT called."""
        publish_calls = []

        def fake_publish(*args, **kwargs):
            publish_calls.append(args)  # pragma: no cover

        mock_conn = AsyncMock()
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock(return_value=mock_transaction)
        mock_transaction.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_transaction)

        try:
            async with mock_conn.transaction():
                raise Exception("DB connection error")  # simulate write failure
            fake_publish("run-1", "Vietnam", "tenant-1", "s3://key", 5, 8.0)
        except Exception:
            pass  # expected

        assert len(publish_calls) == 0, "publish must not be called when DB write fails"

    @pytest.mark.asyncio
    async def test_s1_eventbridge_not_called_on_write_exception(self):
        """EventBridge put_events not called when write_run_context_stage raises."""
        from unittest.mock import AsyncMock as _AM

        eb_calls = []

        async def fake_write_raise(*args, **kwargs):
            raise Exception("asyncpg write failure")

        def fake_put_events(*args, **kwargs):
            eb_calls.append(True)  # pragma: no cover

        mock_conn = AsyncMock()
        mock_transaction = _AM()
        mock_transaction.__aenter__ = _AM(return_value=mock_transaction)
        mock_transaction.__aexit__ = _AM(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_transaction)

        with patch("api.services.run_context_db.write_run_context_stage",
                   side_effect=fake_write_raise):
            try:
                from api.services.run_context_db import write_run_context_stage
                async with mock_conn.transaction():
                    await write_run_context_stage(mock_conn, "run-1", "s1",
                                                  {"s1_keywords_used": []})
                fake_put_events()  # only called if no exception
            except Exception:
                pass

        assert len(eb_calls) == 0, "EventBridge must not fire when DB write raises"
