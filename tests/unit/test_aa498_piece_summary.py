"""AA-498 (AA-494 Decision 4) — content_summary generation, same LLM call as the write itself.
Covers generate.py's two extraction paths (plain-text trailing marker for the 7 non-blog
channels, "summary" JSON key for blog) and the soft-fail contract (a missing/unparseable summary
never fails the write)."""
import json
from unittest.mock import MagicMock, patch

from services.acp_angle_gate.channel_style import get_channel_style
from services.acp_angle_gate.goals import get_goal
from services.acp_content_writing import generate as gen_mod
from services.acp_content_writing.generate import _extract_summary, write_content
from shared.llm_client.models import LLMResponse

GOAL = get_goal("promotion")
FACEBOOK = get_channel_style("facebook")
BLOG = get_channel_style("blog")
ANGLE = {"name": "A", "why_it_works": "wa", "formula_fit": "AIDA", "best_final_style": "warm"}
BRAND_AUDIENCE = {"customer_segment": "Senior execs", "customer_mindset": "seek depth"}


def _resp(content: str) -> LLMResponse:
    return LLMResponse(content=content, model_used="sonnet", provider="bedrock", cost_usd=0.02)


def _client_returning(content: str):
    client = MagicMock()
    client.generate.return_value = _resp(content)
    return client


class TestExtractSummaryHelper:
    def test_splits_marker_and_strips_both_sides(self):
        content, summary = _extract_summary(
            "The final post.\n\n===SUMMARY===\nCovers the temple visit from a slow-travel angle."
        )
        assert content == "The final post."
        assert summary == "Covers the temple visit from a slow-travel angle."

    def test_no_marker_returns_text_unchanged_and_none(self):
        content, summary = _extract_summary("Just the post, no marker at all.")
        assert content == "Just the post, no marker at all."
        assert summary is None

    def test_marker_present_but_empty_tail_is_none_not_empty_string(self):
        content, summary = _extract_summary("The post.\n===SUMMARY===\n   ")
        assert content == "The post."
        assert summary is None


class TestNonBlogChannelSummaryReachesWriteContent:
    def test_summary_extracted_and_stripped_from_content(self):
        raw = "Final Facebook post text.\n===SUMMARY===\nA reflective angle on the market visit."
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(raw)):
            content, _cost, _seo_meta, summary = write_content(
                content_seed="seed", goal=GOAL, channel_style=FACEBOOK,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            )
        assert content == "Final Facebook post text."
        assert "===SUMMARY===" not in content
        assert summary == "A reflective angle on the market visit."

    def test_missing_summary_marker_is_soft_fail_not_an_error(self):
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning("Just a post.")):
            content, _cost, _seo_meta, summary = write_content(
                content_seed="seed", goal=GOAL, channel_style=FACEBOOK,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            )
        assert content == "Just a post."
        assert summary is None

    def test_summary_instructions_reach_the_prompt_for_every_channel(self):
        client = _client_returning("piece")
        with patch.object(gen_mod, "LLMClient", return_value=client):
            write_content(
                content_seed="seed", goal=GOAL, channel_style=FACEBOOK,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            )
        # SYSTEM_PROMPT (not the per-channel user prompt) carries the instruction — same call arg
        # LLMRequest exposes it on.
        request = client.generate.call_args[0][0]
        assert "===SUMMARY===" in request.system_prompt


class TestBlogChannelSummaryInEnvelope:
    def test_summary_key_parsed_out_of_json_envelope(self):
        envelope = {
            "seo_title": "T", "meta_description": "d" * 130 + ".", "slug": "s",
            "body": "## Intro\nReal body text.",
            "summary": "Covers the route from a slow-travel angle.",
        }
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(json.dumps(envelope))):
            content, _cost, _seo_meta, summary = write_content(
                content_seed="seed", goal=GOAL, channel_style=BLOG,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now", atom_id="atom_x",
            )
        assert content == envelope["body"]
        assert summary == "Covers the route from a slow-travel angle."

    def test_missing_summary_key_is_none_not_a_parse_error(self):
        envelope = {
            "seo_title": "T", "meta_description": "d" * 130 + ".", "slug": "s",
            "body": "## Intro\nReal body text.",
        }  # no "summary" key at all
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(json.dumps(envelope))):
            content, _cost, _seo_meta, summary = write_content(
                content_seed="seed", goal=GOAL, channel_style=BLOG,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            )
        assert content == envelope["body"]
        assert summary is None
