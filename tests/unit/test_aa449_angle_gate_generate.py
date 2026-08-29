"""AA-449 — services/acp_angle_gate/generate.py. LLMClient is patched, same convention
test_aa217_malformed_json_cost.py already uses for graph.py's generate_node()."""
import json
from unittest.mock import MagicMock, patch

import pytest

from services.acp_angle_gate import generate as gen_mod
from services.acp_angle_gate.generate import AngleGenerationError, generate_angles
from services.acp_angle_gate.goals import get_goal
from services.acp_shared.dfs_relevance import SearchDemandSignal
from shared.llm_client.models import LLMResponse

GOAL = get_goal("promotion")

_VALID_ANGLES = {
    "angles": [
        {"name": "A", "why_it_works": "wa", "formula_fit": "fa", "best_final_style": "sa"},
        {"name": "B", "why_it_works": "wb", "formula_fit": "fb", "best_final_style": "sb"},
        {"name": "C", "why_it_works": "wc", "formula_fit": "fc", "best_final_style": "sc"},
    ],
    "recommended_index": 1,
    "recommendation_reason": "B is strongest",
}


def _resp(content: str, cost=0.01) -> LLMResponse:
    return LLMResponse(content=content, model_used="sonnet", provider="bedrock", cost_usd=cost)


def _client_returning(content: str):
    client = MagicMock()
    client.generate.return_value = _resp(content)
    return client


@pytest.mark.asyncio
class TestGenerateAngles:
    async def test_valid_json_parsed(self):
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(json.dumps(_VALID_ANGLES))):
            angles, rec_idx, reason, cost = await generate_angles(
                content_seed="Cross the bamboo bridge at dawn", goal=GOAL, channel="facebook",
                brand_audience={"customer_segment": "Senior execs", "customer_mindset": "seek depth"},
            )
        assert len(angles) == 3
        assert rec_idx == 1
        assert reason == "B is strongest"
        assert cost == 0.01

    async def test_markdown_fenced_json_stripped(self):
        fenced = "```json\n" + json.dumps(_VALID_ANGLES) + "\n```"
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(fenced)):
            angles, rec_idx, _reason, _cost = await generate_angles(
                content_seed="seed", goal=GOAL, channel="tiktok", brand_audience={},
            )
        assert len(angles) == 3

    async def test_malformed_json_salvaged_via_repair(self):
        # trailing comma — invalid strict JSON but json_repair can fix it
        broken = json.dumps(_VALID_ANGLES).rstrip("}") + ",}"
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(broken)):
            angles, *_ = await generate_angles(
                content_seed="seed", goal=GOAL, channel="email", brand_audience={},
            )
        assert len(angles) == 3

    async def test_wrong_angle_count_raises(self):
        bad = {"angles": [_VALID_ANGLES["angles"][0]], "recommended_index": 0}
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(json.dumps(bad))):
            with pytest.raises(AngleGenerationError):
                await generate_angles(content_seed="seed", goal=GOAL, channel="blog", brand_audience={})

    async def test_missing_field_raises(self):
        bad = {
            "angles": [
                {"name": "A", "why_it_works": "wa", "formula_fit": "fa"},  # missing best_final_style
                _VALID_ANGLES["angles"][1], _VALID_ANGLES["angles"][2],
            ],
            "recommended_index": 0,
        }
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(json.dumps(bad))):
            with pytest.raises(AngleGenerationError):
                await generate_angles(content_seed="seed", goal=GOAL, channel="blog", brand_audience={})

    async def test_bad_recommended_index_defaults_to_zero(self):
        bad_idx = dict(_VALID_ANGLES, recommended_index=99)
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(json.dumps(bad_idx))):
            _angles, rec_idx, _reason, _cost = await generate_angles(
                content_seed="seed", goal=GOAL, channel="blog", brand_audience={},
            )
        assert rec_idx == 0

    async def test_unknown_channel_raises_before_any_llm_call(self):
        client = MagicMock()
        with patch.object(gen_mod, "LLMClient", return_value=client):
            with pytest.raises(AngleGenerationError):
                await generate_angles(
                    content_seed="seed", goal=GOAL, channel="not_a_real_channel", brand_audience={},
                )
        client.generate.assert_not_called()

    async def test_brand_audience_and_goal_reach_the_prompt(self):
        """The LLM call must actually receive the fixed brand audience (STEP0 §6) and the
        chosen goal's formula — not silently dropped."""
        client = _client_returning(json.dumps(_VALID_ANGLES))
        with patch.object(gen_mod, "LLMClient", return_value=client):
            await generate_angles(
                content_seed="Cross the bamboo bridge", goal=GOAL, channel="linkedin",
                brand_audience={"customer_segment": "Senior executives", "customer_mindset": "seek depth"},
                destination="Sapa", trip_name="Ha Giang Loop",
            )
        request = client.generate.call_args[0][0]
        assert "Senior executives" in request.user_prompt
        assert "seek depth" in request.user_prompt
        assert GOAL["marketing_term"] in request.user_prompt
        assert "Ha Giang Loop" in request.user_prompt
        assert request.model_tier == "sonnet"

    async def test_search_demand_signal_reaches_the_prompt(self):
        """AA-469 Việc 4 — the confirmed real gap (DFS/PAA never fed angle generation) is fixed:
        when a SearchDemandSignal is passed, its PAA/related-keyword text must actually reach
        the LLM call, same "reaches the prompt" assertion style as
        test_brand_audience_and_goal_reach_the_prompt above."""
        client = _client_returning(json.dumps(_VALID_ANGLES))
        signal = SearchDemandSignal(
            relevance="HIGH",
            people_also_ask=["is sapa safe to trek?"],
            related_keywords=["sapa trekking tour"],
        )
        with patch.object(gen_mod, "LLMClient", return_value=client):
            await generate_angles(
                content_seed="seed", goal=GOAL, channel="blog", brand_audience={},
                search_demand=signal,
            )
        request = client.generate.call_args[0][0]
        assert "is sapa safe to trek?" in request.user_prompt
        assert "sapa trekking tour" in request.user_prompt
        assert "HIGH" in request.user_prompt

    async def test_search_demand_signal_omitted_when_none(self):
        """No seo_context row for this tour -> no SEARCH DEMAND block at all, not an empty one —
        the prompt for a request with no signal stays exactly as it was before this change."""
        client = _client_returning(json.dumps(_VALID_ANGLES))
        with patch.object(gen_mod, "LLMClient", return_value=client):
            await generate_angles(
                content_seed="seed", goal=GOAL, channel="blog", brand_audience={},
                search_demand=None,
            )
        request = client.generate.call_args[0][0]
        assert "SEARCH DEMAND SIGNAL" not in request.user_prompt

    async def test_search_demand_signal_with_no_paa_or_keywords_omitted(self):
        """A signal object can exist (a seo_context row was found) but carry neither PAA nor
        related keywords — must still omit the block, not render an empty one."""
        client = _client_returning(json.dumps(_VALID_ANGLES))
        signal = SearchDemandSignal(relevance="MED", people_also_ask=[], related_keywords=[])
        with patch.object(gen_mod, "LLMClient", return_value=client):
            await generate_angles(
                content_seed="seed", goal=GOAL, channel="blog", brand_audience={},
                search_demand=signal,
            )
        request = client.generate.call_args[0][0]
        assert "SEARCH DEMAND SIGNAL" not in request.user_prompt
