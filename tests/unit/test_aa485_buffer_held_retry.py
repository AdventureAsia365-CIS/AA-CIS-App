"""AA-485 (Q5=C origin, AA-331 — "buffer chạy lại slot HELD", transferred from dead N6/
slot_runner.py to T9/T10's real content_piece.status='held'). Covers
_maybe_buffer_retry_held_piece()'s 2 eligibility rules (repairable-cause only, exactly N=1 per
request) and _run_buffer_retry_attempt()'s own single-attempt write (seeded with the original
hold's violations via rewrite_with_feedback(), never write_content()).

Mirrors test_aa450_content_writing_service.py's own mocking shape."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_content_writing import service

TENANT_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
HELD_PIECE_ID = uuid.uuid4()
NEW_PIECE_ID = uuid.uuid4()

GOAL = {"key": "promotion", "name": "Promotion", "description": "d", "logic": "AIDA", "marketing_term": "AIDA"}
ANGLE = {"idx": 0, "name": "A", "why_it_works": "wa", "formula_fit": "AIDA",
         "best_final_style": "warm", "recommended": True, "chosen": True, "option_id": str(uuid.uuid4())}
CHANNEL_STYLE = {"key": "facebook", "tone": "casual"}


def _pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _context(**over):
    base = {
        "atom_text": "atom text", "goal": GOAL, "channel_style": CHANNEL_STYLE,
        "brand_audience": {}, "chosen": ANGLE, "cta": "Book a consultation",
        "destination": None, "trip_name": None, "brand_rubric_text": "rubric",
        "channel": "facebook", "atom_id": "atom_abc123", "route_segments": None, "keyword": None,
        "tenant_id": str(TENANT_ID), "route_hub_name": None, "route_segment_count": None,
    }
    base.update(over)
    return base


def _repair_log(repairable=True, violations=None):
    return [{"attempt": 2, "gate_targeted": "F2_banned_patterns",
             "violations": violations or ["banned pattern -> 'breathtaking'"], "repairable": repairable}]


def _placeholder_row():
    return {
        "piece_id": str(NEW_PIECE_ID), "tenant_id": TENANT_ID, "angle_gate_request_id": REQUEST_ID,
        "attempt_number": 1, "content_text": "", "status": "processing",
        "held_reason": None, "gate_ledger": [], "repair_log": [], "created_at": datetime.now(timezone.utc),
        "route_hub_name": None, "route_segment_count": None,
    }


def _finalized_row(**over):
    base = {
        "piece_id": NEW_PIECE_ID, "tenant_id": TENANT_ID, "angle_gate_request_id": REQUEST_ID,
        "attempt_number": 1, "content_text": "retried piece", "status": "approved",
        "held_reason": None, "gate_ledger": [], "repair_log": [], "created_at": datetime.now(timezone.utc),
    }
    base.update(over)
    return base


def _passing_outcome():
    return {"passed": True, "gate_ledger": [], "first_failure": None, "flags": []}


def _failing_outcome():
    failure = {"gate": "F2_banned_patterns", "passed": False, "violations": ["still there"], "repairable": True}
    return {"passed": False, "gate_ledger": [failure], "first_failure": failure, "flags": []}


@pytest.mark.asyncio
class TestEligibility:
    async def test_non_repairable_hold_skips_retry_entirely(self):
        conn = AsyncMock()
        pool = _pool(conn)
        with patch.object(service, "_insert_placeholder_piece") as mock_insert:
            await service._maybe_buffer_retry_held_piece(
                request_id=REQUEST_ID, held_piece_id=HELD_PIECE_ID,
                repair_log=_repair_log(repairable=False), context=_context(), pool=pool,
            )
        mock_insert.assert_not_called()
        conn.fetchrow.assert_not_called()  # doesn't even check "already retried" — short-circuits first

    async def test_empty_repair_log_skips_retry(self):
        """A held piece can reach status='held' with an EMPTY repair_log only via the exception
        handler's own 'failed' finalize (a different status, not 'held') — this guard is
        defensive, not reachable via the real held path, but must not crash if it ever is."""
        pool = _pool(AsyncMock())
        with patch.object(service, "_insert_placeholder_piece") as mock_insert:
            await service._maybe_buffer_retry_held_piece(
                request_id=REQUEST_ID, held_piece_id=HELD_PIECE_ID,
                repair_log=[], context=_context(), pool=pool,
            )
        mock_insert.assert_not_called()

    async def test_already_retried_once_skips_second_retry(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"piece_id": uuid.uuid4()}  # a prior OTHER piece exists
        pool = _pool(conn)
        with patch.object(service, "_insert_placeholder_piece") as mock_insert:
            await service._maybe_buffer_retry_held_piece(
                request_id=REQUEST_ID, held_piece_id=HELD_PIECE_ID,
                repair_log=_repair_log(repairable=True), context=_context(), pool=pool,
            )
        mock_insert.assert_not_called()
        query, *params = conn.fetchrow.call_args[0]
        assert "content_piece" in query
        assert params == [REQUEST_ID, HELD_PIECE_ID]

    async def test_first_repairable_hold_triggers_retry(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None  # no other piece exists yet — eligible
        pool = _pool(conn)
        with patch.object(service, "_insert_placeholder_piece",
                           new=AsyncMock(return_value=_placeholder_row())) as mock_insert, \
             patch.object(service, "_run_buffer_retry_attempt", new=AsyncMock()) as mock_run:
            await service._maybe_buffer_retry_held_piece(
                request_id=REQUEST_ID, held_piece_id=HELD_PIECE_ID,
                repair_log=_repair_log(repairable=True, violations=["v1", "v2"]), context=_context(), pool=pool,
            )
        mock_insert.assert_awaited_once()
        assert mock_insert.call_args.kwargs["angle_gate_option_id"] == ANGLE["option_id"]
        mock_run.assert_awaited_once()
        assert mock_run.call_args.kwargs["original_violations"] == ["v1", "v2"]
        assert mock_run.call_args.kwargs["piece_id"] == NEW_PIECE_ID


@pytest.mark.asyncio
class TestRunBufferRetryAttempt:
    async def test_uses_rewrite_with_feedback_not_write_content(self):
        with patch.object(service, "write_content") as mock_write, \
             patch.object(service, "rewrite_with_feedback",
                           return_value=("retried piece", 0.02, {}, None)) as mock_rewrite, \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()), \
             patch.object(service, "_finalize_piece", new=AsyncMock(return_value=_finalized_row())):
            await service._run_buffer_retry_attempt(
                request_id=REQUEST_ID, piece_id=NEW_PIECE_ID, context=_context(),
                original_violations=["banned pattern -> 'breathtaking'"], pool=MagicMock(),
            )
        mock_write.assert_not_called()
        mock_rewrite.assert_called_once()
        assert mock_rewrite.call_args.kwargs["revision_feedback"] == ["banned pattern -> 'breathtaking'"]

    async def test_single_attempt_no_further_retry_loop(self):
        """If the one buffer-retry attempt ALSO holds, it stays held — no second internal
        attempt, matching Q5=C's own 'không lặp vô hạn'."""
        with patch.object(service, "rewrite_with_feedback", return_value=("still bad", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates", return_value=_failing_outcome()), \
             patch.object(service, "_finalize_piece",
                           new=AsyncMock(return_value=_finalized_row(status="held"))) as mock_finalize:
            await service._run_buffer_retry_attempt(
                request_id=REQUEST_ID, piece_id=NEW_PIECE_ID, context=_context(),
                original_violations=["x"], pool=MagicMock(),
            )
        assert mock_finalize.call_args.kwargs["status"] == "held"
        assert mock_finalize.call_args.kwargs["repair_log"] == []  # no in-flow repair loop of its own

    async def test_approved_outcome_persists_approved(self):
        with patch.object(service, "rewrite_with_feedback", return_value=("fixed piece", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()), \
             patch.object(service, "_finalize_piece", new=AsyncMock(return_value=_finalized_row())) as mock_finalize:
            await service._run_buffer_retry_attempt(
                request_id=REQUEST_ID, piece_id=NEW_PIECE_ID, context=_context(),
                original_violations=["x"], pool=MagicMock(),
            )
        assert mock_finalize.call_args.kwargs["status"] == "approved"
        assert mock_finalize.call_args.kwargs["content_text"] == "fixed piece"


@pytest.mark.asyncio
class TestRunWriteBackgroundTriggersBufferRetry:
    """End-to-end from run_write_background()'s own perspective — the trailing step only fires
    for a real 'held' final status, never for 'approved'."""

    async def test_held_outcome_calls_maybe_buffer_retry(self):
        failure = {"gate": "F2_banned_patterns", "passed": False, "violations": ["v"], "repairable": False}
        failing = {"passed": False, "gate_ledger": [failure], "first_failure": failure, "flags": []}
        with patch.object(service, "write_content", return_value=("draft", 0.02, {}, None)), \
             patch.object(service, "rewrite_with_feedback", return_value=("draft 2", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates", side_effect=[failing, failing]), \
             patch.object(service, "_finalize_piece",
                           new=AsyncMock(return_value=_finalized_row(status="held"))), \
             patch.object(service, "_maybe_buffer_retry_held_piece", new=AsyncMock()) as mock_maybe:
            await service.run_write_background(REQUEST_ID, HELD_PIECE_ID, _context(), pool=MagicMock())
        mock_maybe.assert_awaited_once()
        assert mock_maybe.call_args.kwargs["held_piece_id"] == HELD_PIECE_ID

    async def test_approved_outcome_never_calls_maybe_buffer_retry(self):
        with patch.object(service, "write_content", return_value=("good piece", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()), \
             patch.object(service, "_finalize_piece", new=AsyncMock(return_value=_finalized_row())), \
             patch.object(service, "_maybe_buffer_retry_held_piece", new=AsyncMock()) as mock_maybe:
            await service.run_write_background(REQUEST_ID, HELD_PIECE_ID, _context(), pool=MagicMock())
        mock_maybe.assert_not_awaited()
