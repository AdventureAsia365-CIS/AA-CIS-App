"""AA-209 follow-up: judge_* must survive the FULL persist path, not just the helper in isolation.

The original PART 2 test called _build_generated_metadata() directly, so it never noticed that
_rewrite_tour (api/routers/v1_pipeline.py) strips the judge_* keys out of the graph state before the
result dict ever reaches _build_generated_metadata — making metadata.judge a prod no-op.

These tests exercise the real wiring:  graph state -> _rewrite_tour result -> _build_generated_metadata
so the propagation gap is caught in CI if it ever regresses.
"""

import pytest
from unittest.mock import MagicMock, patch

from api.routers import v1_pipeline
from api.routers.v1_pipeline import _rewrite_tour
from api.routers.admin_pipeline import _build_generated_metadata


_TOUR = {"name": "Soul of South Korea", "country": "South Korea", "duration": "14 days"}

_META_KW = dict(
    brand_rule_id="rule-1", brand_name="WildKind Travel", seo_mode="dataforseo",
    model_used="haiku", llm_cost_usd=0.001, dataforseo_used=True,
)


def _graph_state(with_judge: bool):
    state = {
        "generated": {
            "name": "Soul of South Korea", "subtitle": "14-day journey",
            "summary": "A fortnight across temples, trails and coast.",
            "highlights": ["Temple stay", "Coastal trail", "Island ferry", "Market morning"],
            "itineraries": "Day 1 -- arrive Seoul. Day 2 -- temple.",
            "seo_title": "South Korea 14-Day Journey", "seo_meta": "Temples, trails and coast.",
        },
        "quality_score": 9.0,
        "sub_scores": {"brand": 10.0, "seo": 9.0, "structure": 10.0, "quality": 10.0},
        "model_used": "haiku", "cost_usd": 0.001,
    }
    if with_judge:
        state.update({
            "judge_brand_fit": 9.0,
            "judge_cross_brand_distinct": 8.0,
            "judge_mission_present": True,
            "judge_feedback": "Strong brand fit; lead the itinerary with the mission hook.",
            "judge_score": 8.0,
        })
    return state


async def _run_rewrite(state):
    # AA-250 B2: _rewrite_tour streams via graph.astream(stream_mode="updates") instead of
    # graph.invoke() — stub astream as an async generator yielding one {node: full_state} event,
    # matching what a real node (which always returns `{**state, ...}`) would emit.
    async def fake_astream(*_args, **_kwargs):
        yield {"judge": state}

    fake_graph = MagicMock()
    fake_graph.astream = fake_astream
    with patch.object(v1_pipeline, "build_graph", return_value=fake_graph):
        return await _rewrite_tour(_TOUR, idx=0, total=1)


@pytest.mark.asyncio
async def test_rewrite_tour_propagates_all_judge_keys():
    """_rewrite_tour must carry every key _build_generated_metadata reads out of graph state."""
    out = await _run_rewrite(_graph_state(with_judge=True))
    assert out["judge_brand_fit"] == 9.0
    assert out["judge_cross_brand_distinct"] == 8.0
    assert out["judge_mission_present"] is True
    assert out["judge_feedback"].startswith("Strong brand fit")
    assert out["judge_score"] == 8.0


@pytest.mark.asyncio
async def test_rewrite_tour_output_feeds_metadata_judge():
    """THE regression guard: the real chain graph -> _rewrite_tour -> _build_generated_metadata
    must now produce metadata.judge. This is the assertion the original PART 2 test lacked."""
    out = await _run_rewrite(_graph_state(with_judge=True))
    meta = _build_generated_metadata(out, **_META_KW)
    assert "judge" in meta, "metadata.judge missing — propagation gap regressed"
    assert meta["judge"]["brand_fit"] == 9.0
    assert meta["judge"]["distinct"] == 8.0
    assert meta["judge"]["mission_present"] is True
    assert meta["judge"]["judge_score"] == 8.0
    assert meta["judge"]["feedback"].startswith("Strong brand fit")


@pytest.mark.asyncio
async def test_rewrite_tour_judge_absent_keeps_metadata_judge_unset():
    """Judge skipped (legacy/no-profile brand): keys propagate as None → guard skips → no metadata.judge."""
    out = await _run_rewrite(_graph_state(with_judge=False))
    assert out["judge_brand_fit"] is None
    meta = _build_generated_metadata(out, **_META_KW)
    assert "judge" not in meta
