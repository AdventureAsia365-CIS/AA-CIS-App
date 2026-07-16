"""AA-225: generate_node must persist seo_keywords_used = keywords actually
injected into the prompt (top_keywords[:5], normalized to list[str]).
Pure unit test — LLMClient patched, no AWS/network. Verifies the success path
sets generated["seo_keywords_used"] and the fail-safe path leaves it untouched.
"""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import json
from services.content_generation import graph
from services.content_generation.graph import generate_node

BASE_TOUR = {
    "tour_id": "t-225", "name": "Jeju Hiking", "country": "South Korea",
    "duration": "5 days", "summary": "s", "description": "d",
    "highlights": [], "itineraries": "",
}
VALID_CONTENT = json.dumps({
    "name": "Jeju Volcanic Trails",
    "subtitle": "Five days on Hallasan",
    "summary": "A factual editorial summary specific to this tour.",
    "highlights": ["Hike Hallasan summit"],
    "seo_title": "Jeju Hiking Tour",
    "seo_meta": "Explore Jeju on foot.",
})

def _state(seo, **over):
    s = {
        "tour": BASE_TOUR, "tour_id": "t-225", "seo": seo,
        "few_shots": [], "retry_count": 0, "cost_usd": 0.0, "model_tier": "haiku",
    }
    s.update(over)
    return s

def _fake_resp(content, cost_usd=0.006,
               model="us.anthropic.claude-haiku-4-5-20251001-v1:0", fallback=False):
    return SimpleNamespace(content=content, cost_usd=cost_usd,
                           model_used=model, fallback_used=fallback,
                           satellite_used=False)

def _run(seo, content=VALID_CONTENT):
    client = MagicMock()
    client.generate.return_value = _fake_resp(content)
    with patch.object(graph, "LLMClient", return_value=client):
        return generate_node(_state(seo))

def test_flat_keyword_dicts_normalized_to_strings():
    """flat seo.top_keywords as list[dict] (defensive shape) -> kw['keyword'],
    capped at 5. prompts.py reads nested key only, so flat dicts never reach the
    join() at prompts.py:80 — exercises the AA-225 dict->str branch safely."""
    seo = {"top_keywords": [
        {"keyword": "jeju hiking", "search_volume": 1200},
        {"keyword": "hallasan trek", "search_volume": 800},
        {"keyword": "korea trekking", "search_volume": 600},
        {"keyword": "jeju volcano tour", "search_volume": 400},
        {"keyword": "olle trail", "search_volume": 300},
        {"keyword": "sixth keyword should be dropped", "search_volume": 100},
    ]}
    out = _run(seo)
    assert out["generated"]["seo_keywords_used"] == [
        "jeju hiking", "hallasan trek", "korea trekking",
        "jeju volcano tour", "olle trail",
    ]

def test_flat_top_keywords_strings_persisted():
    """flat seo.top_keywords (list[str]) -> persisted as-is, capped at 5."""
    seo = {"top_keywords": ["a", "b", "c", "d", "e", "f"]}
    out = _run(seo)
    assert out["generated"]["seo_keywords_used"] == ["a", "b", "c", "d", "e"]

def test_empty_seo_yields_empty_list():
    """no keywords -> empty list, not missing key."""
    out = _run({"keywords": {"top_keywords": []}})
    assert out["generated"]["seo_keywords_used"] == []

def test_failsafe_empty_generated_has_no_keywords_key():
    """JSON parse fail -> generated={} fail-safe, seo_keywords_used NOT injected."""
    out = _run({"top_keywords": ["x"]}, content="<<< not json >>>")
    assert out["generated"] == {}
    assert "seo_keywords_used" not in out["generated"]
