"""
tests/unit/test_aa298_reliability.py — services/acp_produce/reliability.py::run_produce_slot()
(AA-298 Nhóm 5, sync-on-failure).

Verifies every exit path (success, exception, asyncio.CancelledError) writes
a terminal checkpoint status and never swallows the real outcome — the AA-295
lesson (never swallow CancelledError; asyncio needs it to propagate for
cooperative cancellation to work).
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services.acp_produce.reliability import PRODUCE_SLOT_ITEM_TYPE, run_produce_slot

RUN_ID = "11111111-1111-1111-1111-111111111111"
SLOT_ID = "slot-week3-blog"


@pytest.mark.asyncio
async def test_run_produce_slot_success_checkpoints_start_then_complete():
    db = AsyncMock()

    async def work():
        return {"body": "final content"}

    with patch("services.acp_produce.reliability.checkpoint_start", new=AsyncMock()) as m_start, \
         patch("services.acp_produce.reliability.checkpoint_complete", new=AsyncMock()) as m_complete, \
         patch("services.acp_produce.reliability.checkpoint_failed", new=AsyncMock()) as m_failed:
        result = await run_produce_slot(db, RUN_ID, SLOT_ID, work)

    assert result == {"body": "final content"}
    m_start.assert_awaited_once_with(db, RUN_ID, PRODUCE_SLOT_ITEM_TYPE, SLOT_ID)
    m_complete.assert_awaited_once_with(db, RUN_ID, PRODUCE_SLOT_ITEM_TYPE, SLOT_ID)
    m_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_produce_slot_exception_checkpoints_failed_then_reraises():
    db = AsyncMock()

    async def work():
        raise ValueError("gate exhausted retries")

    with patch("services.acp_produce.reliability.checkpoint_start", new=AsyncMock()), \
         patch("services.acp_produce.reliability.checkpoint_complete", new=AsyncMock()) as m_complete, \
         patch("services.acp_produce.reliability.checkpoint_failed", new=AsyncMock()) as m_failed:
        with pytest.raises(ValueError, match="gate exhausted retries"):
            await run_produce_slot(db, RUN_ID, SLOT_ID, work)

    m_failed.assert_awaited_once_with(db, RUN_ID, PRODUCE_SLOT_ITEM_TYPE, SLOT_ID, "gate exhausted retries")
    m_complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_produce_slot_cancelled_error_checkpoints_failed_and_is_not_swallowed():
    """AA-295: CancelledError must reach the caller/asyncio, not vanish here."""
    db = AsyncMock()

    async def work():
        raise asyncio.CancelledError()

    with patch("services.acp_produce.reliability.checkpoint_start", new=AsyncMock()), \
         patch("services.acp_produce.reliability.checkpoint_complete", new=AsyncMock()), \
         patch("services.acp_produce.reliability.checkpoint_failed", new=AsyncMock()) as m_failed:
        with pytest.raises(asyncio.CancelledError):
            await run_produce_slot(db, RUN_ID, SLOT_ID, work)

    m_failed.assert_awaited_once_with(db, RUN_ID, PRODUCE_SLOT_ITEM_TYPE, SLOT_ID, "cancelled")


@pytest.mark.asyncio
async def test_run_produce_slot_never_leaves_checkpoint_running_on_any_outcome():
    """Property test across all 3 outcomes: checkpoint_start is always followed
    by exactly one terminal call (complete xor failed), never neither."""
    db = AsyncMock()

    for work, expect_complete in [
        (AsyncMock(return_value="ok"), True),
        (AsyncMock(side_effect=RuntimeError("boom")), False),
        (AsyncMock(side_effect=asyncio.CancelledError()), False),
    ]:
        with patch("services.acp_produce.reliability.checkpoint_start", new=AsyncMock()), \
             patch("services.acp_produce.reliability.checkpoint_complete", new=AsyncMock()) as m_complete, \
             patch("services.acp_produce.reliability.checkpoint_failed", new=AsyncMock()) as m_failed:
            try:
                await run_produce_slot(db, RUN_ID, SLOT_ID, work)
            except (RuntimeError, asyncio.CancelledError):
                pass
            terminal_calls = m_complete.await_count + m_failed.await_count
            assert terminal_calls == 1, f"expected exactly 1 terminal checkpoint call, got {terminal_calls}"
            assert m_complete.await_count == (1 if expect_complete else 0)
