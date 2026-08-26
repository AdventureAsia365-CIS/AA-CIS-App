"""AA-450 (write/T10 loop) + AA-466 (202 Accepted + poll split) — services/acp_content_writing/
service.py. Mocked asyncpg pool + every collaborator module, same convention
test_aa449_angle_gate_service.py already uses.

AA-466 split the single write_and_check() into:
  - start_write()          — fast pre-flight (no LLM), inserts a 'processing' placeholder row.
  - run_write_background() — the write/rewrite + T10-check loop, UNCHANGED body, now updating
                              the placeholder in place instead of inserting a final row.
Covers Phase 1's confirmed architecture (max 2 attempts, non-repairable = immediate hold),
STEP0's CTA-fallback decision, and AA-466's new failed/processing states."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_content_writing import service

TENANT_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
PIECE_ID = uuid.uuid4()

GOAL = {"key": "promotion", "name": "Promotion", "description": "d", "logic": "AIDA", "marketing_term": "AIDA"}
ANGLE = {"idx": 0, "name": "A", "why_it_works": "wa", "formula_fit": "AIDA",
         "best_final_style": "warm", "recommended": True, "chosen": True}
CHANNEL_STYLE = {"key": "facebook", "tone": "casual"}


def _make_pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _request(status="approved", cta="Book a consultation", angles=None):
    return {
        "request_id": str(REQUEST_ID), "tenant_id": str(TENANT_ID), "atom_id": "atom_abc123",
        "trip_id": None, "channel": "facebook", "goal": "promotion", "cta": cta,
        "status": status, "created_at": "2026-08-24T00:00:00", "updated_at": "2026-08-24T00:00:00",
        "angles": angles if angles is not None else [ANGLE],
    }


def _placeholder_row(**over):
    base = {
        "piece_id": PIECE_ID, "tenant_id": TENANT_ID, "angle_gate_request_id": REQUEST_ID,
        "attempt_number": 1, "content_text": "", "status": "processing",
        "held_reason": None, "gate_ledger": [], "repair_log": [],
        "created_at": datetime.now(timezone.utc),
    }
    base.update(over)
    return base


def _finalized_row(**over):
    base = {
        "piece_id": PIECE_ID, "tenant_id": TENANT_ID, "angle_gate_request_id": REQUEST_ID,
        "attempt_number": 1, "content_text": "final piece text", "status": "approved",
        "held_reason": None, "gate_ledger": [], "repair_log": [],
        "created_at": datetime.now(timezone.utc),
    }
    base.update(over)
    return base


def _context(**over):
    base = {
        "atom_text": "atom text", "goal": GOAL, "channel_style": CHANNEL_STYLE,
        "brand_audience": {}, "chosen": ANGLE, "cta": "Book a consultation",
        "destination": None, "trip_name": None, "brand_rubric_text": "rubric",
        "channel": "facebook", "atom_id": "atom_abc123",
    }
    base.update(over)
    return base


def _passing_outcome():
    ledger = [{"gate": "F6_cta_present", "passed": True, "violations": [], "repairable": True}]
    return {"passed": True, "gate_ledger": ledger, "first_failure": None}


def _failing_outcome(gate="F2_banned_patterns", repairable=True):
    failure = {"gate": gate, "passed": False, "violations": [f"{gate} violation"], "repairable": repairable}
    return {"passed": False, "gate_ledger": [failure], "first_failure": failure}


@pytest.mark.asyncio
class TestStartWrite:
    """Fast pre-flight only — no LLM call, ends with a 'processing' placeholder insert."""

    async def test_happy_path_returns_piece_and_context(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [{"text": "atom text"}, _placeholder_row()]
        pool = _make_pool(conn)

        with patch.object(service.angle_gate_service, "fetch_request", new=AsyncMock(return_value=_request())), \
             patch.object(service, "fetch_brand_audience", new=AsyncMock(return_value={})), \
             patch.object(service, "fetch_brand_rubric_text", new=AsyncMock(return_value="rubric")), \
             patch.object(service, "get_goal", return_value=GOAL), \
             patch.object(service, "write_content") as mock_write, \
             patch.object(service, "run_quality_gates") as mock_gates:
            result = await service.start_write(TENANT_ID, REQUEST_ID, pool)

        assert result["piece"]["status"] == "processing"
        assert result["piece"]["piece_id"] == str(PIECE_ID)
        assert result["context"]["atom_text"] == "atom text"
        assert result["context"]["cta"] == "Book a consultation"
        assert result["context"]["goal"] == GOAL
        mock_write.assert_not_called()   # pre-flight never touches the LLM
        mock_gates.assert_not_called()

    async def test_request_not_approved_raises(self):
        pool = _make_pool(AsyncMock())
        with patch.object(service.angle_gate_service, "fetch_request",
                           new=AsyncMock(return_value=_request(status="pending_choice"))):
            with pytest.raises(service.RequestNotReadyError):
                await service.start_write(TENANT_ID, REQUEST_ID, pool)

    async def test_missing_cta_raises_without_override(self):
        pool = _make_pool(AsyncMock())
        with patch.object(service.angle_gate_service, "fetch_request",
                           new=AsyncMock(return_value=_request(cta=None))):
            with pytest.raises(service.MissingCTAError):
                await service.start_write(TENANT_ID, REQUEST_ID, pool)

    async def test_cta_override_used_when_stored_cta_is_null(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [{"text": "atom text"}, _placeholder_row()]
        pool = _make_pool(conn)

        with patch.object(service.angle_gate_service, "fetch_request",
                           new=AsyncMock(return_value=_request(cta=None))), \
             patch.object(service, "fetch_brand_audience", new=AsyncMock(return_value={})), \
             patch.object(service, "fetch_brand_rubric_text", new=AsyncMock(return_value="rubric")), \
             patch.object(service, "get_goal", return_value=GOAL):
            result = await service.start_write(TENANT_ID, REQUEST_ID, pool, cta_override="Read the guide")

        assert result["context"]["cta"] == "Read the guide"


@pytest.mark.asyncio
class TestRunWriteBackground:
    """The write/rewrite + T10-check loop — body unchanged from pre-AA-466, now updating the
    placeholder in place. _finalize_piece() is patched directly so these tests don't need to
    fake the UPDATE's conn/pool machinery — same isolation level start_write()'s tests use for
    the INSERT side."""

    async def test_happy_path_first_attempt_approved(self):
        with patch.object(service, "write_content", return_value=("final piece text", 0.02)) as mock_write, \
             patch.object(service, "rewrite_with_feedback") as mock_rewrite, \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()), \
             patch.object(service, "_finalize_piece", new=AsyncMock(return_value=_finalized_row())) as mock_finalize:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(), pool=MagicMock())

        mock_write.assert_called_once()
        mock_rewrite.assert_not_called()
        assert mock_finalize.call_args.kwargs["status"] == "approved"
        assert mock_finalize.call_args.kwargs["attempt_number"] == 1
        assert mock_finalize.call_args.kwargs["held_reason"] is None

    async def test_retry_once_then_approved(self):
        with patch.object(service, "write_content", return_value=("draft 1", 0.02)) as mock_write, \
             patch.object(service, "rewrite_with_feedback", return_value=("draft 2", 0.02)) as mock_rewrite, \
             patch.object(service, "run_quality_gates",
                           side_effect=[_failing_outcome(), _passing_outcome()]), \
             patch.object(service, "_finalize_piece",
                           new=AsyncMock(return_value=_finalized_row(attempt_number=2))) as mock_fin:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(), pool=MagicMock())

        mock_write.assert_called_once()
        mock_rewrite.assert_called_once()
        assert mock_rewrite.call_args.kwargs["revision_feedback"] == ["F2_banned_patterns violation"]
        assert mock_fin.call_args.kwargs["status"] == "approved"
        assert mock_fin.call_args.kwargs["attempt_number"] == 2

    async def test_retry_exhausted_still_failing_holds_at_max_two_attempts(self):
        with patch.object(service, "write_content", return_value=("draft 1", 0.02)), \
             patch.object(service, "rewrite_with_feedback", return_value=("draft 2", 0.02)) as mock_rewrite, \
             patch.object(service, "run_quality_gates",
                           side_effect=[_failing_outcome(), _failing_outcome()]), \
             patch.object(service, "_finalize_piece",
                           new=AsyncMock(return_value=_finalized_row(status="held"))) as mock_fin:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(), pool=MagicMock())

        mock_rewrite.assert_called_once()  # exactly 2 attempts total, never a 3rd
        assert mock_fin.call_args.kwargs["status"] == "held"
        assert mock_fin.call_args.kwargs["held_reason"] == "F2_banned_patterns: F2_banned_patterns violation"

    async def test_non_repairable_failure_holds_immediately_no_rewrite(self):
        with patch.object(service, "write_content", return_value=("draft 1", 0.02)) as mock_write, \
             patch.object(service, "rewrite_with_feedback") as mock_rewrite, \
             patch.object(service, "run_quality_gates",
                           return_value=_failing_outcome(gate="F6_cta_present", repairable=False)), \
             patch.object(service, "_finalize_piece",
                           new=AsyncMock(return_value=_finalized_row(status="held"))) as mock_fin:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(), pool=MagicMock())

        mock_write.assert_called_once()
        mock_rewrite.assert_not_called()  # non-repairable — never wastes a second attempt
        assert mock_fin.call_args.kwargs["status"] == "held"
        assert mock_fin.call_args.kwargs["attempt_number"] == 1

    async def test_exception_in_write_content_marks_failed(self):
        """AA-466 — a real system error (not a quality-gate hold) inside the background task
        must land as status='failed', with held_reason carrying the error, never silently lost
        and never conflated with a real 'held' business outcome."""
        with patch.object(service, "write_content", side_effect=RuntimeError("Bedrock throttled")), \
             patch.object(service, "_finalize_piece",
                           new=AsyncMock(return_value=_finalized_row(status="failed"))) as mock_fin:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(), pool=MagicMock())

        assert mock_fin.call_args.kwargs["status"] == "failed"
        assert "Bedrock throttled" in mock_fin.call_args.kwargs["held_reason"]
        assert mock_fin.call_args.kwargs["content_text"] == ""

    async def test_exception_during_gate_check_marks_failed_not_held(self):
        with patch.object(service, "write_content", return_value=("draft 1", 0.02)), \
             patch.object(service, "run_quality_gates", side_effect=ValueError("gate crashed")), \
             patch.object(service, "_finalize_piece",
                           new=AsyncMock(return_value=_finalized_row(status="failed"))) as mock_fin:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(), pool=MagicMock())

        assert mock_fin.call_args.kwargs["status"] == "failed"
        assert "gate crashed" in mock_fin.call_args.kwargs["held_reason"]

    async def test_finalize_write_failure_itself_is_swallowed_not_raised(self):
        """If even the failed-status UPDATE can't be written (DB blip), run_write_background()
        must not raise out of the background task — there's no caller left to catch it."""
        with patch.object(service, "write_content", side_effect=RuntimeError("boom")), \
             patch.object(service, "_finalize_piece", new=AsyncMock(side_effect=RuntimeError("db down"))):
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(), pool=MagicMock())  # no raise


@pytest.mark.asyncio
class TestFetchPiece:
    async def test_returns_piece(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _finalized_row()
        pool = _make_pool(conn)
        result = await service.fetch_piece(TENANT_ID, uuid.uuid4(), pool)
        assert result["status"] == "approved"

    async def test_not_found_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = _make_pool(conn)
        with pytest.raises(service.ContentWritingError):
            await service.fetch_piece(TENANT_ID, uuid.uuid4(), pool)
