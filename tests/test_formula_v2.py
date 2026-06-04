"""Tests for S4.2 v2 GOALS dict and brief.py goal_key field (AA-145-A)."""
from services.acp_s4_social.formula import (
    GOALS,
    normalize_goal_key,
    get_goal_primary_formula,
    load_goal_references,
    get_formula_name,
)
from services.acp_s4_social.brief import ContentBrief


def test_goals_dict_has_9_entries():
    assert len(GOALS) == 9


def test_normalize_goal_key_by_number():
    assert normalize_goal_key("1") == "1"


def test_normalize_goal_key_by_name():
    assert normalize_goal_key("promotion") == "1"


def test_normalize_goal_key_unknown():
    assert normalize_goal_key("xyz") is None


def test_get_goal_primary_formula():
    assert get_goal_primary_formula("1") == "aida"


def test_load_goal_references_returns_content():
    content = load_goal_references("1")
    assert "aida" in content.lower()


def test_load_goal_references_multi():
    content = load_goal_references("2")
    assert "---" in content


def test_backward_compat_get_formula_name():
    assert get_formula_name("facebook", "awareness") == "aida"


def test_brief_goal_key_optional():
    brief = ContentBrief(
        brand="x",
        audience="y",
        channel="facebook",
        goal="engagement",
        topic="t",
        tone="calm",
        cta="click",
    )
    assert brief.goal_key is None


def test_brief_goal_key_set():
    brief = ContentBrief(
        brand="x",
        audience="y",
        channel="facebook",
        goal="engagement",
        topic="t",
        tone="calm",
        cta="click",
        goal_key="1",
        goal_name="Promotion",
    )
    d = brief.to_dict()
    assert d["goal_key"] == "1"
    assert d["goal_name"] == "Promotion"
