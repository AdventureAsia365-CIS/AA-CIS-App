"""AA-498 (AA-494 Decision 4) — services/acp_shared/piece_history.py (fetch) and its wiring into
T8's angle-generation prompt (services/acp_angle_gate/prompts.py, generate.py)."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_angle_gate.prompts import build_user_prompt
from services.acp_angle_gate.goals import get_goal
from services.acp_shared.piece_history import PriorPiece, fetch_piece_history

TENANT_ID = uuid.uuid4()
GOAL = get_goal("promotion")
BRAND_AUDIENCE = {"customer_segment": "Senior execs", "customer_mindset": "seek depth"}


def _make_pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


@pytest.mark.asyncio
class TestFetchPieceHistory:
    async def test_maps_rows_into_prior_pieces(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"content_summary": "Covers the temple from a visual angle.", "channel": "blog",
             "angle_name": "The Visual Paradox", "created_at": None},
        ]
        pool = _make_pool(conn)
        result = await fetch_piece_history(TENANT_ID, "atom_abc", pool)
        assert result == [
            PriorPiece(channel="blog", angle_name="The Visual Paradox",
                       summary="Covers the temple from a visual angle.")
        ]

    async def test_empty_is_not_an_error(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        result = await fetch_piece_history(TENANT_ID, "atom_abc", pool)
        assert result == []

    async def test_scoped_by_tenant_and_atom_and_excludes_current_request(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        exclude = uuid.uuid4()
        await fetch_piece_history(TENANT_ID, "atom_abc", pool, exclude_request_id=exclude)
        args = conn.fetch.call_args[0]
        assert args[1] == TENANT_ID
        assert args[2] == "atom_abc"
        assert args[3] == str(exclude)


class TestPromptRendersPieceHistory:
    def test_block_present_when_history_given(self):
        history = [PriorPiece(channel="blog", angle_name="Visual Paradox", summary="Covers X.")]
        prompt = build_user_prompt(
            content_seed="seed", goal=GOAL, brand_audience=BRAND_AUDIENCE,
            destination=None, trip_name=None, piece_history=history,
        )
        assert "PRIOR PIECES" in prompt
        assert "Visual Paradox" in prompt
        assert "Covers X." in prompt
        assert "blog" in prompt

    def test_block_omitted_when_no_history(self):
        prompt = build_user_prompt(
            content_seed="seed", goal=GOAL, brand_audience=BRAND_AUDIENCE,
            destination=None, trip_name=None, piece_history=None,
        )
        assert "PRIOR PIECES" not in prompt

    def test_block_omitted_when_empty_list(self):
        prompt = build_user_prompt(
            content_seed="seed", goal=GOAL, brand_audience=BRAND_AUDIENCE,
            destination=None, trip_name=None, piece_history=[],
        )
        assert "PRIOR PIECES" not in prompt


class _TxnCM:
    """Same fix test_aa449_angle_gate_service.py uses — conn.transaction() is a sync method
    returning an async context manager."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _pool_with_txn(conn):
    conn.transaction = MagicMock(return_value=_TxnCM())
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


class TestSetGoalAndGenerateFetchesPieceHistory:
    """services/acp_angle_gate/service.py::set_goal_and_generate() — piece_history must reach
    generate_angles(), the same wiring already proven for search_demand (AA-469 Việc 4). Mirrors
    test_aa449_angle_gate_service.py::TestSetGoalAndGenerate's own happy-path mocking shape."""

    @pytest.mark.asyncio
    async def test_piece_history_passed_through_to_generate_angles(self):
        from services.acp_angle_gate import service as angle_gate_service

        req_id = uuid.uuid4()
        req_row = {
            "request_id": req_id, "tenant_id": TENANT_ID, "atom_id": "atom_abc123",
            "trip_id": None, "channel": "facebook", "goal": None, "cta": None,
            "status": "pending_goal", "dfs_paa_snapshot": None, "route_segment_ids": None,
            "subject_id": None,
        }
        atom_row = {"atom_id": "atom_abc123", "tour_id": None, "text": "atom text"}
        history = [PriorPiece(channel="facebook", angle_name="Old Angle", summary="Covered Y.")]
        angles = [
            {"name": "A", "why_it_works": "wa", "formula_fit": "fa", "best_final_style": "sa"},
            {"name": "B", "why_it_works": "wb", "formula_fit": "fb", "best_final_style": "sb"},
            {"name": "C", "why_it_works": "wc", "formula_fit": "fc", "best_final_style": "sc"},
        ]

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            req_row,  # _fetch_request_row (status check)
            atom_row,  # _fetch_atom_for_tenant
            {"customer_segment": "x", "customer_mindset": "y"},  # brand audience
        ]
        # No trip_id -> fetch_search_demand_signal/fetch_tenant_trips are never reached.
        pool = _pool_with_txn(conn)

        with patch.object(angle_gate_service, "fetch_piece_history",
                           new=AsyncMock(return_value=history)) as mock_history, \
             patch.object(angle_gate_service, "generate_angles",
                           new=AsyncMock(return_value=(angles, 1, "B is best", 0.02))) as mock_gen, \
             patch.object(angle_gate_service, "fetch_request", new=AsyncMock(return_value=req_row)):
            await angle_gate_service.set_goal_and_generate(TENANT_ID, req_id, "promotion", pool)

        mock_history.assert_awaited_once()
        assert mock_history.call_args.kwargs["exclude_request_id"] == req_id
        assert mock_gen.call_args.kwargs["piece_history"] == history
