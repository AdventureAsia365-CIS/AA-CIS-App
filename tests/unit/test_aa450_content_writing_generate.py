"""AA-450 — services/acp_content_writing/generate.py. LLMClient is patched, same convention
test_aa449_angle_gate_generate.py already uses. Non-blog channels' output is still plain final
content, not structured JSON (per SKILL_v2.md) — AA-514 added a 3rd return value (seo_meta,
all-None for non-blog) to both functions; AA-498 added a 4th (summary, extracted from a trailing
===SUMMARY=== marker, None when absent — see test_aa498_piece_summary.py for the dedicated
summary-extraction tests) — see test_aa514_content_writing_seo_envelope.py for the blog-channel
JSON-envelope path."""
from unittest.mock import MagicMock, patch

import pytest

from services.acp_content_writing import generate as gen_mod
from services.acp_content_writing.generate import rewrite_with_feedback, write_content
from services.acp_angle_gate.goals import get_goal
from services.acp_angle_gate.channel_style import get_channel_style
from shared.llm_client.models import LLMResponse

GOAL = get_goal("promotion")
CHANNEL_STYLE = get_channel_style("facebook")
ANGLE = {"name": "A", "why_it_works": "wa", "formula_fit": "AIDA", "best_final_style": "warm"}
BRAND_AUDIENCE = {"customer_segment": "Senior execs", "customer_mindset": "seek depth"}


def _resp(content: str, cost=0.01) -> LLMResponse:
    return LLMResponse(content=content, model_used="sonnet", provider="bedrock", cost_usd=cost)


def _client_returning(content: str):
    client = MagicMock()
    client.generate.return_value = _resp(content)
    return client


class TestWriteContent:
    def test_returns_content_and_cost(self):
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning("Final piece text.")):
            content, cost, seo_meta, _summary = write_content(
                content_seed="Cross the bamboo bridge at dawn", goal=GOAL,
                channel_style=CHANNEL_STYLE, brand_audience=BRAND_AUDIENCE, angle=ANGLE,
                cta="Book a consultation",
            )
        assert content == "Final piece text."
        assert cost == 0.01
        assert seo_meta == {"seo_title": None, "meta_description": None, "slug": None}

    def test_strips_markdown_fence(self):
        fenced = "```text\nFinal piece text.\n```"
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(fenced)):
            content, _cost, _seo_meta, _summary = write_content(
                content_seed="seed", goal=GOAL, channel_style=CHANNEL_STYLE,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            )
        assert content == "Final piece text."
        assert "```" not in content

    def test_prompt_carries_cta_angle_and_channel_style(self):
        client = _client_returning("piece")
        with patch.object(gen_mod, "LLMClient", return_value=client):
            write_content(
                content_seed="Cross the bamboo bridge", goal=GOAL, channel_style=CHANNEL_STYLE,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book a consultation",
                destination="Sapa", trip_name="Ha Giang Loop",
            )
        request = client.generate.call_args[0][0]
        assert "Book a consultation" in request.user_prompt
        assert ANGLE["name"] in request.user_prompt
        assert CHANNEL_STYLE["display_name"] in request.user_prompt
        assert "Ha Giang Loop" in request.user_prompt
        # AA-518: model comes from the "t9_write" stage config now (seeded to sonnet, matching
        # this test's prior literal exactly) — model_tier itself is no longer set explicitly
        # here, that's the whole point of making it admin-configurable.
        assert request.stage == "t9_write"

    def test_no_revision_feedback_on_first_attempt(self):
        client = _client_returning("piece")
        with patch.object(gen_mod, "LLMClient", return_value=client):
            write_content(
                content_seed="seed", goal=GOAL, channel_style=CHANNEL_STYLE,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            )
        assert "PREVIOUS ATTEMPT FAILED" not in client.generate.call_args[0][0].user_prompt


class TestRewriteWithFeedback:
    def test_feedback_reaches_the_prompt(self):
        client = _client_returning("revised piece")
        with patch.object(gen_mod, "LLMClient", return_value=client):
            content, _cost, _seo_meta, _summary = rewrite_with_feedback(
                content_seed="seed", goal=GOAL, channel_style=CHANNEL_STYLE,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
                revision_feedback=["banned pattern -> 'breathtaking'", "no CTA present"],
            )
        assert content == "revised piece"
        prompt = client.generate.call_args[0][0].user_prompt
        assert "PREVIOUS ATTEMPT FAILED" in prompt
        assert "breathtaking" in prompt
        assert "no CTA present" in prompt
