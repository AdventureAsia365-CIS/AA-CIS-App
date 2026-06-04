"""Tests for S4.2 v2 handler rebuild (AA-145-B).

Covers: goal_key routing, angles_json storage, quality evaluator wiring,
backward compat without goal_key, checkpoint calls, and failure resilience.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_s4_social.brief import ContentBrief
from services.acp_s4_social.handler import run_auto, run_guided_write


def _make_brief(goal_key=None):
    return ContentBrief(
        brand="AdventureAsia",
        audience="affluent travelers 40-60",
        channel="facebook",
        goal="awareness",
        topic="Vietnam highlands trek",
        tone="aspirational",
        cta="Design This Journey",
        goal_key=goal_key,
        goal_name="Introduction / Awareness" if goal_key else "",
    )


def _make_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetchrow = AsyncMock(return_value={"social_id": "fake-uuid-social"})
    return db


_ANGLES_JSON = (
    '[{"name":"Bold","why_it_works":"x","length_signal":"200","style_signal":"conv"},'
    '{"name":"Angle2","why_it_works":"y","length_signal":"150","style_signal":"auth"},'
    '{"name":"Angle3","why_it_works":"z","length_signal":"100","style_signal":"narr"}]'
)


def _make_llm():
    return MagicMock(return_value=_ANGLES_JSON)


PASSING_QUALITY = MagicMock(passed=True, average=4.0)
FAILING_QUALITY = MagicMock(passed=False, average=2.0)
_QP_OK = {"revised_content": "final text", "warnings": []}


@pytest.mark.asyncio
@patch("services.acp_s4_social.handler.save_to_db", new_callable=AsyncMock)
@patch("services.acp_s4_social.handler.evaluate_quality", return_value=PASSING_QUALITY)
@patch("services.acp_s4_social.handler.quality_pass", return_value=_QP_OK)
@patch("services.acp_s4_social.handler.write_content", return_value="draft text")
@patch("services.acp_s4_social.handler.load_goal_references", return_value="goal refs")
@patch("services.acp_s4_social.handler.load_formula_file")
async def test_run_auto_uses_goal_references(
    mock_load_formula_file, mock_load_goal_refs, mock_write, mock_quality,
    mock_eval, mock_save,
):
    mock_save.return_value = "fake-uuid-social"
    brief = _make_brief(goal_key="4")
    db = _make_db()
    llm = _make_llm()

    await run_auto(brief, {"run_id": "r1", "tour_id": "t1"}, db, llm)

    mock_load_goal_refs.assert_called_once_with("4")
    mock_load_formula_file.assert_not_called()


@pytest.mark.asyncio
@patch("services.acp_s4_social.handler.save_to_db", new_callable=AsyncMock)
@patch("services.acp_s4_social.handler.evaluate_quality", return_value=PASSING_QUALITY)
@patch("services.acp_s4_social.handler.quality_pass", return_value=_QP_OK)
@patch("services.acp_s4_social.handler.write_content", return_value="draft text")
async def test_run_auto_stores_angles_json(mock_write, mock_quality, mock_eval, mock_save):
    mock_save.return_value = "fake-uuid-social"
    brief = _make_brief(goal_key="4")
    db = _make_db()
    llm = _make_llm()

    await run_auto(brief, {"run_id": "r1", "tour_id": "t1"}, db, llm)

    call_args = mock_save.call_args
    saved_meta = call_args[0][2]
    assert "angles_json" in saved_meta
    import json
    angles = json.loads(saved_meta["angles_json"])
    assert "angle_1" in angles
    assert "angle_2" in angles
    assert "angle_3" in angles
    assert angles["selected_index"] == 1


@pytest.mark.asyncio
@patch("services.acp_s4_social.handler.save_to_db", new_callable=AsyncMock)
@patch("services.acp_s4_social.handler.evaluate_quality", return_value=PASSING_QUALITY)
@patch("services.acp_s4_social.handler.quality_pass", return_value=_QP_OK)
@patch("services.acp_s4_social.handler.write_content", return_value="draft text")
async def test_run_auto_calls_quality_evaluator(mock_write, mock_quality, mock_eval, mock_save):
    mock_save.return_value = "fake-uuid-social"
    brief = _make_brief()
    db = _make_db()
    llm = _make_llm()

    await run_auto(brief, {}, db, llm)

    mock_eval.assert_called_once()
    call_args = mock_eval.call_args[0]
    assert call_args[1] == "facebook"


@pytest.mark.asyncio
@patch("services.acp_s4_social.handler.save_to_db", new_callable=AsyncMock)
@patch("services.acp_s4_social.handler.evaluate_quality", return_value=PASSING_QUALITY)
@patch("services.acp_s4_social.handler.quality_pass", return_value=_QP_OK)
@patch("services.acp_s4_social.handler.write_content", return_value="draft text")
@patch("services.acp_s4_social.handler.load_goal_references")
@patch("services.acp_s4_social.handler.load_formula_file", return_value="formula text")
async def test_run_auto_backward_compat_no_goal_key(
    mock_load_formula_file, mock_load_goal_refs, mock_write,
    mock_quality, mock_eval, mock_save,
):
    mock_save.return_value = "fake-uuid-social"
    brief = _make_brief(goal_key=None)
    db = _make_db()
    llm = _make_llm()

    await run_auto(brief, {}, db, llm)

    mock_load_formula_file.assert_called_once()
    mock_load_goal_refs.assert_not_called()


@pytest.mark.asyncio
@patch("services.acp_s4_social.handler.save_to_db", new_callable=AsyncMock)
@patch("services.acp_s4_social.handler.evaluate_quality", return_value=PASSING_QUALITY)
@patch("services.acp_s4_social.handler.quality_pass", return_value=_QP_OK)
@patch("services.acp_s4_social.handler.write_content", return_value="draft text")
async def test_run_guided_write_calls_evaluator(mock_write, mock_quality, mock_eval, mock_save):
    mock_save.return_value = "fake-uuid-social"
    brief = _make_brief()
    db = _make_db()
    llm = _make_llm()
    angle = {"name": "Bold", "why_it_works": "x", "length_signal": "200", "style_signal": "conv"}

    await run_guided_write(brief, angle, {}, db, llm)

    mock_eval.assert_called_once()


@pytest.mark.asyncio
@patch("services.acp_s4_social.handler.checkpoint_complete", new_callable=AsyncMock)
@patch("services.acp_s4_social.handler.save_to_db", new_callable=AsyncMock)
@patch("services.acp_s4_social.handler.evaluate_quality", return_value=PASSING_QUALITY)
@patch("services.acp_s4_social.handler.quality_pass", return_value=_QP_OK)
@patch("services.acp_s4_social.handler.write_content", return_value="draft text")
async def test_checkpoint_called_on_success(
    mock_write, mock_quality, mock_eval, mock_save, mock_checkpoint,
):
    mock_save.return_value = "fake-uuid-social"
    brief = _make_brief()
    db = _make_db()
    llm = _make_llm()
    meta = {"run_id": "run-abc", "tour_id": "tour-xyz"}

    await run_auto(brief, meta, db, llm)

    mock_checkpoint.assert_called_once_with(db, "run-abc", "social_tour", "tour-xyz")


@pytest.mark.asyncio
@patch("services.acp_s4_social.handler.checkpoint_failed", new_callable=AsyncMock)
@patch("services.acp_s4_social.handler.write_content", side_effect=RuntimeError("boom"))
async def test_checkpoint_failure_best_effort(mock_write, mock_checkpoint_failed):
    brief = _make_brief()
    db = _make_db()
    llm = _make_llm()
    meta = {"run_id": "run-abc", "tour_id": "tour-xyz"}

    with pytest.raises(RuntimeError, match="boom"):
        await run_auto(brief, meta, db, llm)

    mock_checkpoint_failed.assert_called_once_with(
        db, "run-abc", "social_tour", "tour-xyz", "boom"
    )
