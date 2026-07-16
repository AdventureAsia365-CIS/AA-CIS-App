"""AA-217: deterministic json-repair salvage + cost-carry on malformed generation.

Pure unit tests for generate_node — no AWS, no network. LLMClient is patched so
client.generate() returns a fake response (or raises), exercising only the
parse/salvage/cost-accounting logic added in AA-217.
"""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from services.content_generation import graph
from services.content_generation.graph import generate_node


BASE_TOUR = {
    "tour_id": "t-123",
    "name": "Sri Lanka Rail Journey",
    "country": "Sri Lanka",
    "duration": "10 days",
    "summary": "s",
    "description": "d",
    "highlights": [],
    "itineraries": "",
}
BASE_SEO = {"keywords": {"top_keywords": []}, "people_also_ask": []}

# loads() fails (missing comma between two string values) -> repair_json salvages to a named dict.
MALFORMED = (
    '{"name": "Sri Lanka by Rail", "subtitle": "Ten days" '
    '"summary": "Lorem ipsum long descriptive string."}'
)
# Same defect, wrapped in a ```json fence -> salvage must run AFTER the fence strip.
FENCED_MALFORMED = (
    '```json\n{"name": "Vietnam Rail", "subtitle": "x" '
    '"summary": "long enough text here"}\n```'
)
# Unsalvageable: repair_json returns a str, not a named dict -> fail branch.
GARBAGE = "<<< not json at all >>>"


def _state(**over):
    s = {
        "tour": BASE_TOUR,
        "tour_id": "t-123",
        "seo": BASE_SEO,
        "few_shots": [],
        "retry_count": 1,
        "cost_usd": 0.0,
        "model_tier": "haiku",
    }
    s.update(over)
    return s


def _fake_resp(content, cost_usd=0.006,
               model="us.anthropic.claude-haiku-4-5-20251001-v1:0", fallback=False):
    return SimpleNamespace(content=content, cost_usd=cost_usd,
                           model_used=model, fallback_used=fallback,
                           satellite_used=False)


def _run(content=None, *, resp=None, raise_exc=None, state=None):
    """Run generate_node with LLMClient patched. resp/raise_exc control client.generate()."""
    if state is None:
        state = _state()
    client = MagicMock()
    if raise_exc is not None:
        client.generate.side_effect = raise_exc
    else:
        client.generate.return_value = resp if resp is not None else _fake_resp(content)
    with patch.object(graph, "LLMClient", return_value=client):
        return generate_node(state)


def test_malformed_json_salvaged_by_repair():
    """1. Missing-comma JSON -> repair_json salvage -> generated has a truthy name (not empty)."""
    out = _run(MALFORMED)
    assert out["generated"] != {}
    assert out["generated"].get("name") == "Sri Lanka by Rail"
    assert out["error"] == ""


def test_unsalvageable_garbage_returns_empty_and_logs_and_carries_cost():
    """2. Garbage repair can't fix -> generated={} + json_parse_failed logged + cost carried."""
    state = _state(cost_usd=0.5)
    resp = _fake_resp(GARBAGE, cost_usd=0.006)
    client = MagicMock()
    client.generate.return_value = resp
    with patch.object(graph, "LLMClient", return_value=client), \
            patch.object(graph, "logger") as mlog:
        out = generate_node(state)
    assert out["generated"] == {}
    assert any(
        call.args and call.args[0] == "json_parse_failed"
        for call in mlog.warning.call_args_list
    )
    assert out["cost_usd"] == pytest.approx(0.5 + 0.006)


def test_jsondecode_path_carries_cost_state_plus_resp():
    """3. Salvage-fail JSONDecodeError path: cost_usd == state cost + resp cost (resp bound)."""
    state = _state(cost_usd=0.5)
    resp = _fake_resp(GARBAGE, cost_usd=0.02)
    out = _run(resp=resp, state=state)
    assert out["generated"] == {}
    assert out["cost_usd"] == pytest.approx(0.52)


def test_exception_path_resp_none_no_unbound_cost_state_only():
    """4. client.generate raises (resp never bound) -> Exception branch, no UnboundLocalError,
    cost_usd == state cost only."""
    state = _state(cost_usd=0.5)
    out = _run(raise_exc=RuntimeError("All LLM providers failed"), state=state)
    assert out["generated"] == {}
    assert out["cost_usd"] == pytest.approx(0.5)
    assert "All LLM providers failed" in out["error"]


def test_fence_wrapped_internally_malformed_salvaged_after_strip():
    """5. ```json fence + internal malformed -> salvage runs after fence strip -> named dict."""
    out = _run(FENCED_MALFORMED)
    assert out["generated"].get("name") == "Vietnam Rail"
    assert out["error"] == ""
