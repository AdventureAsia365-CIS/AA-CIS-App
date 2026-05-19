import pytest
import json
from unittest.mock import patch, MagicMock, call
from services.content_generation.graph import (
    generate_node, validate_node, should_retry, increment_retry, ContentState
)
from shared.llm_client.models import LLMResponse

def make_state(**kwargs) -> ContentState:
    base = {
        "tour":                  {"name": "Halong Bay", "country": "Vietnam"},
        "seo":                   {},
        "few_shots":             [],
        "generated":             {},
        "quality_score":         0.0,
        "retry_count":           0,
        "feedback":              "",
        "error":                 "",
        "cost_usd":              0.0,
        "model_used":            "",
        "brand_system_prompt":   "",
        "brand_style_guide":     "",
        "brand_forbidden_words": [],
        "rewrite_language":      "en-US",
        "model_tier":            "haiku",
        "is_tenant_rewrite":     False,
        "is_branded":            True,
    }
    base.update(kwargs)
    return base

# --- validate_node tests ---

def test_validate_perfect_content():
    state = make_state(
        tour={"name": "Halong Bay Private Cruise", "country": "Vietnam"},
        generated={
        "name":        "Halong Bay Private Cruise",
        "subtitle":    "A 3-night private cruise through Halong Bay karst islands",
        "summary":     "Three nights aboard a private vessel through Halong Bay, visiting karst caves and fishing villages. Kayaking, cooking class, and sundeck access included.",
        "highlights":  [
            "Kayaking through Luon Cave at low tide with a private guide",
            "Sunrise from the sundeck at Bai Tu Long Bay, 50km from main tourist routes",
            "Chef-prepared seafood dinner sourced from local fishing communities",
        ],
        "itineraries": "Day 1: Board at Tuan Chau, sail to Bai Tu Long. Day 2: Cave visit, kayaking. Day 3: Sunrise, return to port.",
        "seo_title":   "Halong Bay Private Cruise | Adventure Asia",
        "seo_meta":    "A 3-night private cruise through Halong Bay with kayaking, cave visits, and chef-prepared meals. Departing Tuan Chau.",
        "trip_type":   "cultural",
    })
    result = validate_node(state)
    assert result["quality_score"] == 10.0, f"Expected 10.0 got {result['quality_score']}: {result['feedback']}"
    assert result["feedback"] == ""

def test_validate_missing_fields():
    state = make_state(generated={"name": "Halong Bay"})
    result = validate_node(state)
    assert result["quality_score"] < 10.0
    assert "Missing field" in result["feedback"]

def test_validate_forbidden_word():
    state = make_state(generated={
        "name":      "Cheap Vietnam Tour",
        "subtitle":  "Best deal ever",
        "summary":   "Get the cheapest tour now",
        "highlights": ["item1"],
        "seo_title": "Cheap Tour",
        "seo_meta":  "Best deal in Vietnam",
        "trip_type": "cultural",
    })
    result = validate_node(state)
    assert result["quality_score"] < 10.0
    assert "cheap" in result["feedback"].lower() or "deal" in result["feedback"].lower()

def test_validate_seo_title_too_long():
    state = make_state(
        tour={"name": "Halong Bay Cruise", "country": "Vietnam"},
        generated={
            "name":        "Halong Bay Cruise",
            "subtitle":    "3-night private cruise through karst islands",
            "summary":     "Summary text here",
            "highlights":  ["h1", "h2", "h3"],
            "itineraries": "Day 1: board. Day 2: kayak. Day 3: return.",
            "seo_title":   "A" * 71,  # 71 chars — exceeds 70-char limit
            "seo_meta":    "Meta description",
            "trip_type":   "cultural",
        }
    )
    result = validate_node(state)
    assert "seo_title" in result["feedback"]

# --- should_retry tests ---

def test_should_retry_high_score():
    state = make_state(quality_score=8.5, retry_count=0)
    assert should_retry(state) == "done"

def test_should_retry_low_score_first_attempt():
    state = make_state(quality_score=5.0, retry_count=0)
    assert should_retry(state) == "retry"

def test_should_retry_exhausted():
    state = make_state(quality_score=4.0, retry_count=2)
    assert should_retry(state) == "hitl"

def test_should_retry_exact_threshold():
    state = make_state(quality_score=7.0, retry_count=0)
    assert should_retry(state) == "done"

# --- increment_retry tests ---

def test_increment_retry():
    state = make_state(retry_count=0)
    result = increment_retry(state)
    assert result["retry_count"] == 1

def test_increment_retry_twice():
    state = make_state(retry_count=1)
    result = increment_retry(state)
    assert result["retry_count"] == 2


# --- generate_node brand injection tests ---

_FAKE_LLM_OUTPUT = json.dumps({
    "name": "Halong Bay",
    "subtitle": "A private cruise",
    "summary": "Three nights on Halong Bay.",
    "highlights": ["Kayaking", "Cave tour", "Sunrise"],
    "itineraries": "Day 1: board.",
    "seo_title": "Halong Bay Cruise",
    "seo_meta": "Private cruise through Halong Bay karst islands.",
    "seo_keywords_used": [],
})


def _fake_response() -> LLMResponse:
    return LLMResponse(
        content=_FAKE_LLM_OUTPUT,
        model_used="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        provider="bedrock",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0002,
    )


def test_generate_node_injects_brand_system_prompt():
    """brand_system_prompt from state must appear in LLMRequest.system_prompt sent to LLM."""
    brand_text = "You are writing for Atlas & Hearth, a luxury cultural travel brand."
    state = make_state(brand_system_prompt=brand_text)

    captured: list = []

    async def fake_generate(req):
        captured.append(req)
        return _fake_response()

    with patch("services.content_generation.graph.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate.side_effect = fake_generate

        result = generate_node(state)

    assert captured, "LLMClient.generate was never called"
    req = captured[0]
    assert brand_text in req.system_prompt, (
        f"brand_system_prompt not found in LLMRequest.system_prompt:\n{req.system_prompt[:300]}"
    )
    assert result.get("is_branded") is True
    assert result.get("generated") != {}


def test_generate_node_unbranded_flag_when_no_brand():
    """is_branded=False when brand_system_prompt is empty."""
    state = make_state(brand_system_prompt="")

    async def fake_generate(req):
        return _fake_response()

    with patch("services.content_generation.graph.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate.side_effect = fake_generate

        result = generate_node(state)

    assert result.get("is_branded") is False
