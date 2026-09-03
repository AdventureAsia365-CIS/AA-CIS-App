"""AA-514 — services/acp_content_writing/generate.py's blog-channel JSON envelope
(seo_title/meta_description/slug/body instead of plain text). Non-blog channels are covered by
test_aa450_content_writing_generate.py (unchanged plain-text path, seo_meta all-None)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from services.acp_angle_gate.channel_style import get_channel_style
from services.acp_angle_gate.goals import get_goal
from services.acp_content_writing import generate as gen_mod
from services.acp_content_writing.generate import SeoEnvelopeError, write_content
from shared.llm_client.models import LLMResponse

GOAL = get_goal("promotion")
BLOG_CHANNEL_STYLE = get_channel_style("blog")
ANGLE = {"name": "A", "why_it_works": "wa", "formula_fit": "AIDA", "best_final_style": "warm"}
BRAND_AUDIENCE = {"customer_segment": "Senior execs", "customer_mindset": "seek depth"}

_VALID_ENVELOPE = {
    "seo_title": "Wat Sisaket Travel Guide",
    "meta_description": "x" * 130 + " for your Laos trip.",
    "slug": "wat-sisaket-guide",
    "body": "## Intro\nThe temple stands today. [R:atom_abc123]",
}


def _resp(content: str) -> LLMResponse:
    return LLMResponse(content=content, model_used="sonnet", provider="bedrock", cost_usd=0.02)


def _client_returning(content: str):
    client = MagicMock()
    client.generate.return_value = _resp(content)
    return client


class TestBlogJsonEnvelope:
    def test_valid_envelope_parsed_into_body_and_seo_meta(self):
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(json.dumps(_VALID_ENVELOPE))):
            content, cost, seo_meta, _summary = write_content(
                content_seed="seed", goal=GOAL, channel_style=BLOG_CHANNEL_STYLE,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now", atom_id="atom_abc123",
            )
        assert content == _VALID_ENVELOPE["body"]
        assert cost == 0.02
        assert seo_meta == {
            "seo_title": _VALID_ENVELOPE["seo_title"],
            "meta_description": _VALID_ENVELOPE["meta_description"],
            "slug": _VALID_ENVELOPE["slug"],
        }

    def test_markdown_fenced_json_still_parses(self):
        fenced = "```json\n" + json.dumps(_VALID_ENVELOPE) + "\n```"
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(fenced)):
            content, _cost, seo_meta, _summary = write_content(
                content_seed="seed", goal=GOAL, channel_style=BLOG_CHANNEL_STYLE,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            )
        assert content == _VALID_ENVELOPE["body"]
        assert seo_meta["seo_title"] == _VALID_ENVELOPE["seo_title"]

    def test_malformed_json_salvaged_via_repair(self):
        broken = json.dumps(_VALID_ENVELOPE).rstrip("}") + ",}"  # trailing comma
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(broken)):
            content, _cost, seo_meta, _summary = write_content(
                content_seed="seed", goal=GOAL, channel_style=BLOG_CHANNEL_STYLE,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            )
        assert content == _VALID_ENVELOPE["body"]

    def test_missing_body_key_raises_not_silently_falls_back(self):
        bad = {"seo_title": "T", "meta_description": "d", "slug": "s"}  # no "body"
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(json.dumps(bad))):
            with pytest.raises(SeoEnvelopeError):
                write_content(
                    content_seed="seed", goal=GOAL, channel_style=BLOG_CHANNEL_STYLE,
                    brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
                )

    def test_missing_seo_fields_become_none_not_a_crash(self):
        partial = {"body": "just the body text"}  # no seo_title/meta_description/slug at all
        with patch.object(gen_mod, "LLMClient", return_value=_client_returning(json.dumps(partial))):
            content, _cost, seo_meta, _summary = write_content(
                content_seed="seed", goal=GOAL, channel_style=BLOG_CHANNEL_STYLE,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            )
        assert content == "just the body text"
        assert seo_meta == {"seo_title": None, "meta_description": None, "slug": None}

    def test_keyword_reaches_the_prompt(self):
        client = _client_returning(json.dumps(_VALID_ENVELOPE))
        with patch.object(gen_mod, "LLMClient", return_value=client):
            write_content(
                content_seed="seed", goal=GOAL, channel_style=BLOG_CHANNEL_STYLE,
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now", keyword="laos temples",
            )
        assert "laos temples" in client.generate.call_args[0][0].user_prompt

    def test_non_blog_channel_never_gets_json_envelope_instructions(self):
        client = _client_returning("Plain text post.")
        with patch.object(gen_mod, "LLMClient", return_value=client):
            content, _cost, seo_meta, _summary = write_content(
                content_seed="seed", goal=GOAL, channel_style=get_channel_style("facebook"),
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            )
        assert content == "Plain text post."
        assert seo_meta == {"seo_title": None, "meta_description": None, "slug": None}
        assert "OUTPUT FORMAT" not in client.generate.call_args[0][0].user_prompt
