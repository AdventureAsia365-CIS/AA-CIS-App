"""
tests/unit/test_aa375_slot_runner.py — services/acp_produce/slot_runner.py
(AA-375: real slot-runner glue, C1-C3 -> E1 -> E2 -> E3 -> E4 -> F1-F9).

Every chained function (research/generation/adapt/faq/pipeline) already has
its own dedicated unit test file with real coverage of its own logic —
these tests mock ALL of them and exercise ONLY slot_runner.py's own
orchestration: call order, TOPIC REJECTED short-circuit, E2/E4 failure ->
unknown_ledger + empty-list, and Piece fan-out (blog + channel pieces) into
run_piece_through_produce_gates(). Same "mock the DB, exercise the
orchestrator" convention as test_aa364_pipeline.py / test_aa367_packets.py.
"""
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from services.acp_planning.models import Slot
from services.acp_produce.faq import FAQAnswerFailed
from services.acp_produce.generation import DraftGenerationFailed
from services.acp_produce.models import Brief, KeywordRecord, Piece
from services.acp_produce.slot_runner import run_slot_production

TENANT = "00000000-0000-0000-0000-000000000001"
RUN_ID = "11111111-1111-1111-1111-111111111111"
TRIP_ID = UUID("22222222-2222-2222-2222-222222222222")


def _slot(trip_id=TRIP_ID):
    return Slot(
        slot_id="slot-1", week=1, channel="blog", kind="evergreen",
        trip_id=trip_id, atom_ids=["atom_1", "atom_2"], funnel_stage="TOFU",
        keyword_seed="rickshaw tours", cta_target="https://example.com/trip",
    )


def _brief():
    return Brief(
        brief_id="brief-1", slot_id="slot-1", keyword="rickshaw",
        demand=KeywordRecord(keyword="rickshaw", location="US"),
        required_h2s=["Rickshaw tours: what it's actually like"],
        word_range=(1, 100), cta_target="https://example.com/trip",
        framework="hub",
    )


def _held_piece(piece_id, channel="blog"):
    return Piece(piece_id=piece_id, body_tagged="body", channel=channel, status="held", held_reason="F1: nope")


@pytest.mark.asyncio
@patch("services.acp_produce.slot_runner.run_slot_research", new_callable=AsyncMock)
async def test_topic_rejected_returns_empty_no_further_calls(mock_research):
    mock_research.return_value = None
    db = AsyncMock()

    result = await run_slot_production(db, pool=None, tenant_id=TENANT, slot=_slot(), run_id=RUN_ID, market="US")

    assert result == []
    mock_research.assert_awaited_once()


@pytest.mark.asyncio
@patch("services.acp_produce.slot_runner.log_unknown", new_callable=AsyncMock)
@patch("services.acp_produce.slot_runner.generate_draft")
@patch("services.acp_produce.slot_runner.build_outline", return_value=[])
@patch("services.acp_produce.slot_runner.fetch_slot_atoms", new_callable=AsyncMock)
@patch("services.acp_produce.slot_runner.run_slot_research", new_callable=AsyncMock)
async def test_draft_generation_failed_logs_unknown_and_returns_empty(
    mock_research, mock_atoms, mock_outline, mock_draft, mock_log,
):
    mock_research.return_value = _brief()
    mock_atoms.return_value = [{"atom_id": "atom_1", "text": "fact one"}]
    mock_draft.side_effect = DraftGenerationFailed("sonnet exhausted retries")
    db = AsyncMock()

    result = await run_slot_production(db, pool=None, tenant_id=TENANT, slot=_slot(), run_id=RUN_ID, market="US")

    assert result == []
    mock_log.assert_awaited_once()
    assert mock_log.call_args.args[2] == "other"


@pytest.mark.asyncio
@patch("services.acp_produce.slot_runner.log_unknown", new_callable=AsyncMock)
@patch("services.acp_produce.slot_runner.apply_faq")
@patch("services.acp_produce.slot_runner.adapt_channels", return_value=[])
@patch("services.acp_produce.slot_runner.generate_draft", return_value="draft body")
@patch("services.acp_produce.slot_runner.build_outline", return_value=[])
@patch("services.acp_produce.slot_runner.fetch_slot_atoms", new_callable=AsyncMock)
@patch("services.acp_produce.slot_runner.run_slot_research", new_callable=AsyncMock)
async def test_faq_answer_failed_logs_unknown_and_returns_empty(
    mock_research, mock_atoms, mock_outline, mock_draft, mock_adapt, mock_faq, mock_log,
):
    mock_research.return_value = _brief()
    mock_atoms.return_value = []
    mock_faq.side_effect = FAQAnswerFailed("sonnet exhausted retries")
    db = AsyncMock()

    result = await run_slot_production(db, pool=None, tenant_id=TENANT, slot=_slot(), run_id=RUN_ID, market="US")

    assert result == []
    mock_log.assert_awaited_once()
    assert mock_log.call_args.args[2] == "other"


@pytest.mark.asyncio
@patch("services.acp_produce.slot_runner.fetch_brand_rubric_text", new_callable=AsyncMock)
@patch("services.acp_produce.slot_runner.run_piece_through_produce_gates", new_callable=AsyncMock)
@patch("services.acp_produce.slot_runner.apply_faq")
@patch("services.acp_produce.slot_runner.adapt_channels")
@patch("services.acp_produce.slot_runner.generate_draft", return_value="draft body")
@patch("services.acp_produce.slot_runner.build_outline", return_value=[])
@patch("services.acp_produce.slot_runner.fetch_slot_atoms", new_callable=AsyncMock)
@patch("services.acp_produce.slot_runner.run_slot_research", new_callable=AsyncMock)
async def test_happy_path_fans_out_blog_plus_channel_pieces_through_gates(
    mock_research, mock_atoms, mock_outline, mock_draft, mock_adapt, mock_faq, mock_gates,
    mock_rubric,
):
    brief = _brief()
    mock_research.return_value = brief
    mock_atoms.return_value = [{"atom_id": "atom_1", "text": "fact one"}]
    mock_rubric.return_value = "REAL AA_INTERNAL BRAND RUBRIC"

    fb_piece = Piece(piece_id=f"{RUN_ID}:slot-1:blog#facebook", body_tagged="fb body", channel="facebook")
    tt_piece = Piece(piece_id=f"{RUN_ID}:slot-1:blog#tiktok", body_tagged="tt body", channel="tiktok")
    mock_adapt.return_value = [fb_piece, tt_piece]
    mock_faq.side_effect = lambda piece, brief_, atom_text: piece  # no-op mutate

    mock_gates.side_effect = lambda piece, **kw: _held_piece(piece.piece_id, piece.channel)

    db = AsyncMock()
    result = await run_slot_production(db, pool=None, tenant_id=TENANT, slot=_slot(), run_id=RUN_ID, market="US")

    assert [p.piece_id for p in result] == [
        f"{RUN_ID}:slot-1:blog", f"{RUN_ID}:slot-1:blog#facebook", f"{RUN_ID}:slot-1:blog#tiktok",
    ]
    assert mock_gates.await_count == 3
    # F6's tour_id lookup must resolve from slot.trip_id, not be left None
    for call in mock_gates.await_args_list:
        assert call.kwargs["tour_id"] == str(TRIP_ID)
        assert call.kwargs["run_id"] == RUN_ID
        assert call.kwargs["framework"] == brief.framework
        # AA-404 fix #1 — every piece this slot produces gets the SAME real per-tenant
        # rubric (fetched once), not the old hardcoded AA_BRAND_IDENTITY_PROMPT constant.
        assert call.kwargs["brand_rubric_text"] == "REAL AA_INTERNAL BRAND RUBRIC"
    mock_rubric.assert_awaited_once_with(db, TENANT)


@pytest.mark.asyncio
@patch("services.acp_produce.slot_runner.fetch_brand_rubric_text", new_callable=AsyncMock)
@patch("services.acp_produce.slot_runner.run_piece_through_produce_gates", new_callable=AsyncMock)
@patch("services.acp_produce.slot_runner.apply_faq")
@patch("services.acp_produce.slot_runner.adapt_channels", return_value=[])
@patch("services.acp_produce.slot_runner.generate_draft", return_value="draft body")
@patch("services.acp_produce.slot_runner.build_outline", return_value=[])
@patch("services.acp_produce.slot_runner.fetch_slot_atoms", new_callable=AsyncMock)
@patch("services.acp_produce.slot_runner.run_slot_research", new_callable=AsyncMock)
async def test_no_trip_id_passes_none_tour_id(
    mock_research, mock_atoms, mock_outline, mock_draft, mock_adapt, mock_faq, mock_gates,
    mock_rubric,
):
    mock_research.return_value = _brief()
    mock_atoms.return_value = []
    mock_faq.side_effect = lambda piece, brief_, atom_text: piece
    mock_gates.side_effect = lambda piece, **kw: _held_piece(piece.piece_id, piece.channel)
    mock_rubric.return_value = "REAL AA_INTERNAL BRAND RUBRIC"

    db = AsyncMock()
    slot = _slot(trip_id=None)
    await run_slot_production(db, pool=None, tenant_id=TENANT, slot=slot, run_id=RUN_ID, market="US")

    assert mock_gates.await_args.kwargs["tour_id"] is None
