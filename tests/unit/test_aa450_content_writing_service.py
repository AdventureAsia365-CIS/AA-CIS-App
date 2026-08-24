"""AA-450 — services/acp_content_writing/service.py (the single write-and-check endpoint's whole
orchestration). Mocked asyncpg pool + every collaborator module, same convention
test_aa449_angle_gate_service.py already uses. Covers Phase 1's confirmed architecture (single
endpoint, max 2 attempts, non-repairable = immediate hold) and STEP0's CTA-fallback decision."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_content_writing import service

TENANT_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()

GOAL = {"key": "promotion", "name": "Promotion", "description": "d", "logic": "AIDA", "marketing_term": "AIDA"}
ANGLE = {"idx": 0, "name": "A", "why_it_works": "wa", "formula_fit": "AIDA",
         "best_final_style": "warm", "recommended": True, "chosen": True}


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


def _piece_row(**over):
    base = {
        "piece_id": uuid.uuid4(), "tenant_id": TENANT_ID, "angle_gate_request_id": REQUEST_ID,
        "attempt_number": 1, "content_text": "final piece text", "status": "approved",
        "held_reason": None, "gate_ledger": [], "repair_log": [],
        "created_at": datetime.now(timezone.utc),
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
class TestWriteAndCheck:
    async def test_happy_path_first_attempt_approved(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [{"text": "atom text"}, _piece_row(attempt_number=1, status="approved")]
        pool = _make_pool(conn)

        with patch.object(service.angle_gate_service, "fetch_request", new=AsyncMock(return_value=_request())), \
             patch.object(service, "fetch_brand_audience", new=AsyncMock(return_value={})), \
             patch.object(service, "fetch_brand_rubric_text", new=AsyncMock(return_value="rubric")), \
             patch.object(service, "get_goal", return_value=GOAL), \
             patch.object(service, "write_content", return_value=("final piece text", 0.02)) as mock_write, \
             patch.object(service, "rewrite_with_feedback") as mock_rewrite, \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()):
            result = await service.write_and_check(TENANT_ID, REQUEST_ID, pool)

        assert result["status"] == "approved"
        assert result["attempt_number"] == 1
        mock_write.assert_called_once()
        mock_rewrite.assert_not_called()

    async def test_request_not_approved_raises(self):
        pool = _make_pool(AsyncMock())
        with patch.object(service.angle_gate_service, "fetch_request",
                           new=AsyncMock(return_value=_request(status="pending_choice"))):
            with pytest.raises(service.RequestNotReadyError):
                await service.write_and_check(TENANT_ID, REQUEST_ID, pool)

    async def test_missing_cta_raises_without_override(self):
        pool = _make_pool(AsyncMock())
        with patch.object(service.angle_gate_service, "fetch_request",
                           new=AsyncMock(return_value=_request(cta=None))):
            with pytest.raises(service.MissingCTAError):
                await service.write_and_check(TENANT_ID, REQUEST_ID, pool)

    async def test_cta_override_used_when_stored_cta_is_null(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [{"text": "atom text"}, _piece_row()]
        pool = _make_pool(conn)

        with patch.object(service.angle_gate_service, "fetch_request",
                           new=AsyncMock(return_value=_request(cta=None))), \
             patch.object(service, "fetch_brand_audience", new=AsyncMock(return_value={})), \
             patch.object(service, "fetch_brand_rubric_text", new=AsyncMock(return_value="rubric")), \
             patch.object(service, "get_goal", return_value=GOAL), \
             patch.object(service, "write_content", return_value=("final piece text", 0.02)) as mock_write, \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()):
            await service.write_and_check(TENANT_ID, REQUEST_ID, pool, cta_override="Read the guide")

        assert mock_write.call_args.kwargs["cta"] == "Read the guide"

    async def test_retry_once_then_approved(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [{"text": "atom text"}, _piece_row(attempt_number=2, status="approved")]
        pool = _make_pool(conn)

        with patch.object(service.angle_gate_service, "fetch_request", new=AsyncMock(return_value=_request())), \
             patch.object(service, "fetch_brand_audience", new=AsyncMock(return_value={})), \
             patch.object(service, "fetch_brand_rubric_text", new=AsyncMock(return_value="rubric")), \
             patch.object(service, "get_goal", return_value=GOAL), \
             patch.object(service, "write_content", return_value=("draft 1", 0.02)) as mock_write, \
             patch.object(service, "rewrite_with_feedback", return_value=("draft 2", 0.02)) as mock_rewrite, \
             patch.object(service, "run_quality_gates",
                           side_effect=[_failing_outcome(), _passing_outcome()]):
            result = await service.write_and_check(TENANT_ID, REQUEST_ID, pool)

        assert result["status"] == "approved"
        mock_write.assert_called_once()
        mock_rewrite.assert_called_once()
        assert mock_rewrite.call_args.kwargs["revision_feedback"] == ["F2_banned_patterns violation"]
        persist_args = conn.fetchrow.call_args_list[1][0]
        assert persist_args[3] == 2  # real attempt_number sent to the INSERT, not just the mock row

    async def test_retry_exhausted_still_failing_holds_at_max_two_attempts(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            {"text": "atom text"},
            _piece_row(attempt_number=2, status="held", held_reason="F2_banned_patterns: F2_banned_patterns violation"),
        ]
        pool = _make_pool(conn)

        with patch.object(service.angle_gate_service, "fetch_request", new=AsyncMock(return_value=_request())), \
             patch.object(service, "fetch_brand_audience", new=AsyncMock(return_value={})), \
             patch.object(service, "fetch_brand_rubric_text", new=AsyncMock(return_value="rubric")), \
             patch.object(service, "get_goal", return_value=GOAL), \
             patch.object(service, "write_content", return_value=("draft 1", 0.02)), \
             patch.object(service, "rewrite_with_feedback", return_value=("draft 2", 0.02)) as mock_rewrite, \
             patch.object(service, "run_quality_gates",
                           side_effect=[_failing_outcome(), _failing_outcome()]):
            result = await service.write_and_check(TENANT_ID, REQUEST_ID, pool)

        assert result["status"] == "held"
        mock_rewrite.assert_called_once()  # exactly 2 attempts total, never a 3rd

    async def test_non_repairable_failure_holds_immediately_no_rewrite(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            {"text": "atom text"},
            _piece_row(attempt_number=1, status="held", held_reason="F6_cta_present: no CTA available"),
        ]
        pool = _make_pool(conn)

        with patch.object(service.angle_gate_service, "fetch_request", new=AsyncMock(return_value=_request())), \
             patch.object(service, "fetch_brand_audience", new=AsyncMock(return_value={})), \
             patch.object(service, "fetch_brand_rubric_text", new=AsyncMock(return_value="rubric")), \
             patch.object(service, "get_goal", return_value=GOAL), \
             patch.object(service, "write_content", return_value=("draft 1", 0.02)) as mock_write, \
             patch.object(service, "rewrite_with_feedback") as mock_rewrite, \
             patch.object(service, "run_quality_gates",
                           return_value=_failing_outcome(gate="F6_cta_present", repairable=False)):
            result = await service.write_and_check(TENANT_ID, REQUEST_ID, pool)

        assert result["status"] == "held"
        assert result["attempt_number"] == 1
        mock_write.assert_called_once()
        mock_rewrite.assert_not_called()  # non-repairable — never wastes a second attempt
        persist_args = conn.fetchrow.call_args_list[1][0]
        assert persist_args[3] == 1  # real attempt_number sent to the INSERT — held on attempt 1


@pytest.mark.asyncio
class TestFetchPiece:
    async def test_returns_piece(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _piece_row()
        pool = _make_pool(conn)
        result = await service.fetch_piece(TENANT_ID, uuid.uuid4(), pool)
        assert result["status"] == "approved"

    async def test_not_found_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = _make_pool(conn)
        with pytest.raises(service.ContentWritingError):
            await service.fetch_piece(TENANT_ID, uuid.uuid4(), pool)
