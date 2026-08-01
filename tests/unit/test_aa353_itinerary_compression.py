"""AA-353 — per-day source word counts (prompts.py) + structured itineraries array clamp/nudge/
serialize (graph.py generate_node). No live Bedrock — LLMClient is mocked, same convention as
test_content_graph.py.
"""
import json
from unittest.mock import patch

from services.content_generation.graph import (
    ITINERARY_CLAMP_MAX, ITINERARY_CLAMP_MIN, generate_node,
)
from services.content_generation.prompts import parse_source_day_word_counts
from shared.llm_client.models import LLMResponse


# ── parse_source_day_word_counts ─────────────────────────────────────────────

_LAOS_STYLE_SOURCE = """Day 1: Arrival in Luang Prabang
Transfer to hotel, welcome dinner by the Mekong.

Day 2 - Temple Circuit
Visit Wat Xieng Thong, climb Mount Phousi for sunset, browse the night market with a private
guide who explains the history of each temple along the way, then dinner at a riverside restaurant.

Day 3: Free Day
Free morning, transfer to airport in the afternoon."""


def test_parse_source_day_word_counts_normal_case():
    result = parse_source_day_word_counts(_LAOS_STYLE_SOURCE, "3 Days")
    assert result["used_fallback"] is False
    assert set(result["day_word_counts"].keys()) == {1, 2, 3}
    # day 2 has clearly the most source detail
    assert result["day_word_counts"][2] > result["day_word_counts"][1]
    assert result["day_word_counts"][2] > result["day_word_counts"][3]


def test_parse_source_day_word_counts_fallback_when_no_markers():
    result = parse_source_day_word_counts(
        "Unstructured prose describing the whole trip with no day labels at all.", "5 Days",
    )
    assert result["used_fallback"] is True
    assert set(result["day_word_counts"].keys()) == {1, 2, 3, 4, 5}
    # fallback is a flat even split — every day gets the same count
    assert len(set(result["day_word_counts"].values())) == 1


def test_parse_source_day_word_counts_ignores_mid_line_day_number():
    """AA-346's own regression case: 'Day 82 km' as a day's OWN title text (not a day-boundary
    marker) must not be misread as day 82 — a real Day 5 marker followed later in the same line
    by an unrelated number must still resolve to day=5."""
    source = """Day 4: Cycling to Pakse
Ride through villages along the river.

Day 5: Easy Day 82 km Tarmac Road
Relaxed cycling day along smooth roads with several village stops.

Day 6: Rest day
Free time by the river."""
    result = parse_source_day_word_counts(source, "6 Days")
    assert result["used_fallback"] is False
    assert set(result["day_word_counts"].keys()) == {4, 5, 6}  # not 82


# ── generate_node: structured itineraries array ──────────────────────────────

def make_state(**kwargs):
    base = {
        "tour": {
            "name": "Laos Explorer", "country": "Laos", "duration": "3 Days",
            "itineraries": _LAOS_STYLE_SOURCE,
        },
        "seo": {},
        "few_shots": [],
        "generated": {},
        "quality_score": 0.0,
        "retry_count": 0,
        "feedback": "",
        "error": "",
        "cost_usd": 0.0,
        "model_used": "",
        "brand_system_prompt": "",
        "brand_style_guide": "",
        "brand_forbidden_words": [],
        "rewrite_language": "en-US",
        "model_tier": "haiku",
        "subtitle_focus": "standard",
        "is_tenant_rewrite": False,
        "is_branded": True,
        "failure_codes": [],
        "sub_scores": {},
        "passed_count": 0,
        "failed_count": 0,
    }
    base.update(kwargs)
    return base


def _array_llm_output(day_bodies: dict) -> str:
    return json.dumps({
        "name": "Laos Explorer", "subtitle": "3 days", "summary": "A short Laos trip.",
        "highlights": ["Mekong sunset", "Temple circuit", "Night market"],
        "itineraries": [
            {"day": d, "title": f"Day {d} title", "body": body}
            for d, body in sorted(day_bodies.items())
        ],
        "seo_title": "Laos Explorer", "seo_meta": "x" * 145,
        "trip_type": "cultural",
    })


def _resp(content: str, cache_read=0, cache_write=0) -> LLMResponse:
    return LLMResponse(
        content=content, model_used="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        provider="bedrock", input_tokens=100, output_tokens=50, cost_usd=0.0002,
        cache_read_tokens=cache_read, cache_write_tokens=cache_write,
    )


def test_generate_node_serializes_array_to_canonical_string_when_within_clamp():
    """All days within [0.6, 1.5] of source -> no nudge call, itineraries becomes a plain
    "Day N — Title\\nBody" string (downstream compat), day_ratios recorded with nudged=False."""
    source_counts = parse_source_day_word_counts(_LAOS_STYLE_SOURCE, "3 Days")["day_word_counts"]
    # write each day at ~1.0x its source word count
    bodies = {d: " ".join(["word"] * w) for d, w in source_counts.items()}
    state = make_state()

    with patch("services.content_generation.graph.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate.side_effect = [_resp(_array_llm_output(bodies))]
        result = generate_node(state)

    assert instance.generate.call_count == 1, "no nudge call expected when every day is in-clamp"
    assert isinstance(result["generated"]["itineraries"], str)
    assert "Day 1 — Day 1 title" in result["generated"]["itineraries"]
    assert "Day 2 — Day 2 title" in result["generated"]["itineraries"]
    ratios = result["itinerary_day_ratios"]
    assert len(ratios) == 3
    assert all(r["nudged"] is False for r in ratios)
    assert all(ITINERARY_CLAMP_MIN <= r["ratio"] <= ITINERARY_CLAMP_MAX for r in ratios)


def test_generate_node_nudges_day_outside_clamp_exactly_once():
    """One day written far too short (ratio < 0.6) triggers exactly one extra LLMClient.generate
    call (the nudge), and the nudged body replaces the original in the serialized output."""
    source_counts = parse_source_day_word_counts(_LAOS_STYLE_SOURCE, "3 Days")["day_word_counts"]
    bodies = {d: " ".join(["word"] * w) for d, w in source_counts.items()}
    # day 2 has the most source detail — write it drastically short to force a clamp violation
    bodies[2] = "Too short."

    nudge_reply = _resp(json.dumps({
        "title": "Temple Circuit, Fixed",
        "body": " ".join(["fixed"] * source_counts[2]),
    }))
    state = make_state()

    with patch("services.content_generation.graph.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate.side_effect = [_resp(_array_llm_output(bodies)), nudge_reply]
        result = generate_node(state)

    assert instance.generate.call_count == 2, "exactly one main call + one nudge call"
    nudge_request = instance.generate.call_args_list[1].args[0]
    assert "TARGET LENGTH" in nudge_request.user_prompt
    assert nudge_request.model_tier == "haiku"

    ratios = {r["day"]: r for r in result["itinerary_day_ratios"]}
    assert ratios[2]["nudged"] is True
    assert ratios[2]["ratio"] < ITINERARY_CLAMP_MIN
    assert ITINERARY_CLAMP_MIN <= ratios[2]["ratio_after_nudge"] <= ITINERARY_CLAMP_MAX
    assert "Temple Circuit, Fixed" in result["generated"]["itineraries"]
    assert "Too short." not in result["generated"]["itineraries"]


def test_generate_node_nudge_only_attempted_once_even_if_still_out_of_clamp():
    """If the nudge result is STILL outside clamp, generate_node does not retry — it flags and
    moves on. Exactly 2 LLM calls total (main + one nudge), never 3+."""
    source_counts = parse_source_day_word_counts(_LAOS_STYLE_SOURCE, "3 Days")["day_word_counts"]
    bodies = {d: " ".join(["word"] * w) for d, w in source_counts.items()}
    bodies[2] = "Too short."
    # nudge reply is STILL too short relative to source
    nudge_reply = _resp(json.dumps({"title": "Still short", "body": "Still too short."}))
    state = make_state()

    with patch("services.content_generation.graph.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate.side_effect = [_resp(_array_llm_output(bodies)), nudge_reply]
        result = generate_node(state)

    assert instance.generate.call_count == 2
    ratios = {r["day"]: r for r in result["itinerary_day_ratios"]}
    assert ratios[2]["nudged"] is True
    assert ratios[2]["ratio_after_nudge"] < ITINERARY_CLAMP_MIN, (
        "test setup: nudge reply must still violate clamp to exercise the no-retry path"
    )


def test_generate_node_nudge_cost_and_tokens_folded_into_totals():
    source_counts = parse_source_day_word_counts(_LAOS_STYLE_SOURCE, "3 Days")["day_word_counts"]
    bodies = {d: " ".join(["word"] * w) for d, w in source_counts.items()}
    bodies[2] = "Too short."
    main_resp = _resp(_array_llm_output(bodies), cache_read=10, cache_write=5)
    nudge_resp = _resp(
        json.dumps({"title": "Fixed", "body": " ".join(["fixed"] * source_counts[2])}),
        cache_read=3, cache_write=1,
    )
    state = make_state(cost_usd=0.01, cache_read_tokens=100, cache_write_tokens=50)

    with patch("services.content_generation.graph.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate.side_effect = [main_resp, nudge_resp]
        result = generate_node(state)

    assert result["cost_usd"] == 0.01 + main_resp.cost_usd + nudge_resp.cost_usd
    assert result["cache_read_tokens"] == 100 + 10 + 3
    assert result["cache_write_tokens"] == 50 + 5 + 1


def test_generate_node_legacy_string_itineraries_is_unaffected():
    """Old-contract behavior: a plain string itineraries value (model ignored the array contract,
    or a pre-AA-353 fixture) must pass through unchanged — no crash, no nudge call, empty ratios."""
    state = make_state()
    legacy_output = json.dumps({
        "name": "Laos Explorer", "subtitle": "3 days", "summary": "s",
        "highlights": ["a", "b", "c"],
        "itineraries": "Day 1: board. Day 2: temples. Day 3: departure.",
        "seo_title": "t", "seo_meta": "x" * 145, "trip_type": "cultural",
    })

    with patch("services.content_generation.graph.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate.side_effect = [_resp(legacy_output)]
        result = generate_node(state)

    assert instance.generate.call_count == 1
    assert result["generated"]["itineraries"] == "Day 1: board. Day 2: temples. Day 3: departure."
    assert result["itinerary_day_ratios"] == []
