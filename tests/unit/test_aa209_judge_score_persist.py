"""AA-209: judge_score must survive the LangGraph TypedDict state filter.

This bug class is invisible to helper-level tests: judge_node returns judge_score, _rewrite_tour
propagates it, _build_generated_metadata reads it — but LangGraph's StateGraph filters returned state
down to the keys DECLARED in ContentState. judge_score was set by the node yet not declared, so it was
stripped from the final state, and metadata.judge.judge_score persisted as null.

The first test runs a real compiled StateGraph(ContentState): if judge_score is not declared, the
graph drops it and the assertion fails. The second test pins the helper-level contract (judge_score
non-null in metadata when the judge ran), exercising the real graph -> _rewrite_tour -> metadata chain.
"""

import pytest
from unittest.mock import MagicMock, patch

from langgraph.graph import StateGraph, END

from services.content_generation.graph import ContentState
from api.routers import v1_pipeline
from api.routers.v1_pipeline import _rewrite_tour
from api.routers.admin_pipeline import _build_generated_metadata


_JUDGE_KEYS = {
    "judge_brand_fit": 9.0,
    "judge_cross_brand_distinct": 8.0,
    "judge_mission_present": True,
    "judge_feedback": "on brand",
    "judge_score": 8.0,
}


def test_contentstate_retains_judge_score_through_langgraph():
    """A real StateGraph(ContentState) must keep judge_score in the final state.

    If judge_score is missing from the ContentState TypedDict, LangGraph strips it here -> None.
    This is the exact filter step the MagicMock-based propagation test cannot reach.
    """
    def node(state):
        return {**state, **_JUDGE_KEYS}

    g = StateGraph(ContentState)
    g.add_node("judge", node)
    g.set_entry_point("judge")
    g.add_edge("judge", END)
    compiled = g.compile()

    out = compiled.invoke({"tour": {}, "generated": {}, "quality_score": 0.0})

    # all 5 judge fields must survive the TypedDict filter
    assert out.get("judge_brand_fit") == 9.0
    assert out.get("judge_cross_brand_distinct") == 8.0
    assert out.get("judge_mission_present") is True
    assert out.get("judge_feedback") == "on brand"
    assert out.get("judge_score") == 8.0, "judge_score stripped by LangGraph — declare it in ContentState"


@pytest.mark.asyncio
async def test_metadata_judge_score_non_null_through_rewrite_chain():
    """graph state (with judge_score) -> _rewrite_tour -> _build_generated_metadata: judge_score persists."""
    state = {
        "generated": {"name": "X", "subtitle": "y", "summary": "z",
                      "highlights": ["a", "b", "c", "d"], "itineraries": "Day 1.",
                      "seo_title": "t", "seo_meta": "m"},
        "quality_score": 8.0,
        "sub_scores": {"brand": 10.0, "seo": 8.5, "structure": 10.0, "quality": 10.0},
        "model_used": "haiku", "cost_usd": 0.001,
        **_JUDGE_KEYS,
    }
    fake_graph = MagicMock()
    fake_graph.invoke.return_value = state
    with patch.object(v1_pipeline, "build_graph", return_value=fake_graph):
        out = await _rewrite_tour({"name": "T", "country": "Korea"}, idx=0, total=1)

    meta = _build_generated_metadata(
        out, brand_rule_id="r", brand_name="Atlas & Hearth", seo_mode="dataforseo",
        model_used="haiku", llm_cost_usd=0.001, dataforseo_used=True,
    )
    assert meta["judge"]["judge_score"] is not None
    assert meta["judge"]["judge_score"] == 8.0
