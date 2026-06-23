"""AA-220 (H1): tests for _extract_judge_score — judge_score parsing for the
list_tour_versions endpoint.

The jsonb metadata column arrives as a str OR a dict depending on the asyncpg codec path, so the
helper must handle both, plus every missing/malformed level (no metadata, bad JSON, no judge object,
judge not a dict). Pure parsing logic — no DB needed.
"""

import json

from api.routers.admin_pipeline import _extract_judge_score


# ── happy path: judge_score present ───────────────────────────────────────────

def test_dict_metadata_returns_judge_score():
    meta = {"judge": {"judge_score": 7.5, "brand_fit": 8}}
    assert _extract_judge_score(meta) == 7.5


def test_str_metadata_returns_judge_score():
    meta = json.dumps({"judge": {"judge_score": 6.0}})
    assert _extract_judge_score(meta) == 6.0


def test_judge_score_zero_is_preserved():
    # 0.0 is a legitimate score, not "missing" — must not collapse to None.
    assert _extract_judge_score({"judge": {"judge_score": 0.0}}) == 0.0


# ── None / empty inputs ───────────────────────────────────────────────────────

def test_none_metadata_returns_none():
    assert _extract_judge_score(None) is None


def test_empty_string_metadata_returns_none():
    assert _extract_judge_score("") is None


def test_empty_dict_metadata_returns_none():
    assert _extract_judge_score({}) is None


# ── malformed / partial ───────────────────────────────────────────────────────

def test_unparseable_string_returns_none():
    assert _extract_judge_score("{not valid json") is None


def test_metadata_without_judge_returns_none():
    assert _extract_judge_score({"brand_name": "X", "seo_mode": "standard"}) is None


def test_judge_present_but_no_score_returns_none():
    assert _extract_judge_score({"judge": {"brand_fit": 8, "distinct": 7}}) is None


def test_judge_not_a_dict_returns_none():
    assert _extract_judge_score({"judge": "legacy-string"}) is None


def test_judge_null_returns_none():
    assert _extract_judge_score(json.dumps({"judge": None})) is None
