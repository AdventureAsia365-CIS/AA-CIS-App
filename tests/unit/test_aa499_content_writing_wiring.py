"""AA-499 (AA-494 Decision 5) — services/acp_content_writing/service.py's own wiring:
compute_embedding()/find_similar_pieces() called only for 'approved' pieces, embedding reaches
_finalize_piece(), a within-tenant/different-atom match above threshold becomes a non-blocking
flag. Mirrors test_aa450_content_writing_service.py's own mocking shape (same file's
_context()/_passing_outcome() helpers duplicated locally rather than imported, to keep this
file independently readable — same pattern test_aa452_t10_nine_gates.py already uses)."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_content_writing import service
from services.acp_shared.piece_similarity import SimilarPiece

TENANT_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
PIECE_ID = uuid.uuid4()

GOAL = {"key": "promotion", "name": "Promotion", "description": "d", "logic": "AIDA", "marketing_term": "AIDA"}
ANGLE = {"idx": 0, "name": "A", "why_it_works": "wa", "formula_fit": "AIDA",
         "best_final_style": "warm", "recommended": True, "chosen": True}
CHANNEL_STYLE = {"key": "facebook", "tone": "casual"}
EMBEDDING = [0.1] * 1536


def _context(**over):
    base = {
        "atom_text": "atom text", "goal": GOAL, "channel_style": CHANNEL_STYLE,
        "brand_audience": {}, "chosen": ANGLE, "cta": "Book a consultation",
        "destination": None, "trip_name": None, "brand_rubric_text": "rubric",
        "channel": "facebook", "atom_id": "atom_abc123", "tenant_id": str(TENANT_ID),
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


def _passing_outcome():
    ledger = [{"gate": "F6_cta_present", "passed": True, "violations": [], "repairable": True}]
    return {"passed": True, "gate_ledger": ledger, "first_failure": None, "flags": []}


def _failing_outcome(gate="F2_banned_patterns", repairable=True):
    failure = {"gate": gate, "passed": False, "violations": [f"{gate} violation"], "repairable": repairable}
    return {"passed": False, "gate_ledger": [failure], "first_failure": failure, "flags": []}


@pytest.mark.asyncio
class TestEmbeddingOnlyRunsForApproved:
    async def test_approved_piece_computes_and_persists_embedding(self):
        with patch.object(service, "write_content", return_value=("final piece text", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()), \
             patch.object(service, "compute_embedding", return_value=EMBEDDING) as mock_compute, \
             patch.object(service, "find_similar_pieces", new=AsyncMock(return_value=[])) as mock_find, \
             patch.object(service, "_finalize_piece", new=AsyncMock(return_value=_finalized_row())) as mock_finalize:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(), pool=MagicMock())

        mock_compute.assert_called_once_with("final piece text")
        mock_find.assert_awaited_once()
        assert mock_find.call_args.kwargs["tenant_id"] == TENANT_ID
        assert mock_find.call_args.kwargs["exclude_piece_id"] == PIECE_ID
        assert mock_finalize.call_args.kwargs["content_embedding"] == EMBEDDING

    async def test_held_piece_never_computes_embedding(self):
        with patch.object(service, "write_content", return_value=("draft", 0.02, {}, None)), \
             patch.object(service, "rewrite_with_feedback", return_value=("draft 2", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates",
                           side_effect=[_failing_outcome(repairable=True), _failing_outcome(repairable=False)]), \
             patch.object(service, "compute_embedding") as mock_compute, \
             patch.object(service, "_finalize_piece",
                           new=AsyncMock(return_value=_finalized_row(status="held"))):
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(), pool=MagicMock())

        mock_compute.assert_not_called()

    async def test_embedding_call_failure_soft_fails_no_similarity_query(self):
        """compute_embedding()'s own soft-fail contract (returns None) means find_similar_pieces()
        must never even be called — same "no signal, don't query" precedent this build follows
        throughout."""
        with patch.object(service, "write_content", return_value=("final piece text", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()), \
             patch.object(service, "compute_embedding", return_value=None), \
             patch.object(service, "find_similar_pieces", new=AsyncMock()) as mock_find, \
             patch.object(service, "_finalize_piece", new=AsyncMock(return_value=_finalized_row())) as mock_finalize:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(), pool=MagicMock())

        mock_find.assert_not_awaited()
        assert mock_finalize.call_args.kwargs["content_embedding"] is None


@pytest.mark.asyncio
class TestWithinTenantReuseFlag:
    async def test_match_on_a_different_atom_above_threshold_becomes_a_flag(self):
        match = SimilarPiece(piece_id=str(uuid.uuid4()), tenant_id=str(TENANT_ID),
                              atom_id="atom_OTHER", similarity=0.97)
        with patch.object(service, "write_content", return_value=("final piece text", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()), \
             patch.object(service, "compute_embedding", return_value=EMBEDDING), \
             patch.object(service, "find_similar_pieces", new=AsyncMock(return_value=[match])), \
             patch.object(service, "_finalize_piece", new=AsyncMock(return_value=_finalized_row())) as mock_finalize:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(atom_id="atom_abc123"), pool=MagicMock())

        flags = mock_finalize.call_args.kwargs["flags"]
        assert len(flags) == 1
        assert flags[0]["gate"] == "within_tenant_reuse"
        assert flags[0]["blocking"] is False
        assert flags[0]["similarity"] == 0.97

    async def test_match_on_the_SAME_atom_is_excluded_not_flagged(self):
        """Decision 4's own history block already covers same-atom repetition — this signal is
        specifically about a DIFFERENT atom converging on the same content."""
        match = SimilarPiece(piece_id=str(uuid.uuid4()), tenant_id=str(TENANT_ID),
                              atom_id="atom_abc123", similarity=0.99)
        with patch.object(service, "write_content", return_value=("final piece text", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()), \
             patch.object(service, "compute_embedding", return_value=EMBEDDING), \
             patch.object(service, "find_similar_pieces", new=AsyncMock(return_value=[match])), \
             patch.object(service, "_finalize_piece", new=AsyncMock(return_value=_finalized_row())) as mock_finalize:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(atom_id="atom_abc123"), pool=MagicMock())

        assert mock_finalize.call_args.kwargs["flags"] == []

    async def test_match_below_threshold_is_not_flagged(self):
        match = SimilarPiece(piece_id=str(uuid.uuid4()), tenant_id=str(TENANT_ID),
                              atom_id="atom_OTHER", similarity=0.5)
        with patch.object(service, "write_content", return_value=("final piece text", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()), \
             patch.object(service, "compute_embedding", return_value=EMBEDDING), \
             patch.object(service, "find_similar_pieces", new=AsyncMock(return_value=[match])), \
             patch.object(service, "_finalize_piece", new=AsyncMock(return_value=_finalized_row())) as mock_finalize:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(atom_id="atom_abc123"), pool=MagicMock())

        assert mock_finalize.call_args.kwargs["flags"] == []

    async def test_no_similar_pieces_at_all_is_not_flagged(self):
        with patch.object(service, "write_content", return_value=("final piece text", 0.02, {}, None)), \
             patch.object(service, "run_quality_gates", return_value=_passing_outcome()), \
             patch.object(service, "compute_embedding", return_value=EMBEDDING), \
             patch.object(service, "find_similar_pieces", new=AsyncMock(return_value=[])), \
             patch.object(service, "_finalize_piece", new=AsyncMock(return_value=_finalized_row())) as mock_finalize:
            await service.run_write_background(REQUEST_ID, PIECE_ID, _context(atom_id="atom_abc123"), pool=MagicMock())

        assert mock_finalize.call_args.kwargs["flags"] == []


@pytest.mark.asyncio
class TestFinalizePiecePersistsEmbeddingAsPgvectorLiteral:
    async def test_finalize_piece_casts_embedding_to_vector_literal(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _finalized_row()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        await service._finalize_piece(
            pool, piece_id=PIECE_ID, attempt_number=1, content_text="text", status="approved",
            held_reason=None, gate_ledger=[], repair_log=[], flags=[], content_embedding=[0.1, 0.2],
        )
        query, *params = conn.fetchrow.call_args[0]
        assert "content_embedding = $13::vector" in query
        assert params[-1] == "[0.1,0.2]"

    async def test_finalize_piece_none_embedding_stays_none(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _finalized_row()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        await service._finalize_piece(
            pool, piece_id=PIECE_ID, attempt_number=1, content_text="text", status="held",
            held_reason="x", gate_ledger=[], repair_log=[], flags=[],
        )
        params = conn.fetchrow.call_args[0]
        assert params[-1] is None
