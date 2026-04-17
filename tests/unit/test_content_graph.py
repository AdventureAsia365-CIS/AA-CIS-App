import pytest
import json
from unittest.mock import patch, MagicMock
from services.content_generation.graph import (
    validate_node, should_retry, increment_retry, ContentState
)

def make_state(**kwargs) -> ContentState:
    base = {
        "tour":          {"name": "Halong Bay", "country": "Vietnam"},
        "seo":           {},
        "few_shots":     [],
        "generated":     {},
        "quality_score": 0.0,
        "retry_count":   0,
        "feedback":      "",
        "error":         "",
        "cost_usd":      0.0,
        "model_used":    "",
    }
    base.update(kwargs)
    return base

# --- validate_node tests ---

def test_validate_perfect_content():
    state = make_state(generated={
        "name":      "Halong Bay Private Cruise",
        "subtitle":  "A curated journey through karst landscapes",
        "summary":   "Discover the timeless beauty of Halong Bay on a refined private cruise.",
        "highlights": ["Private sundeck", "Chef-prepared meals", "Kayaking excursion"],
        "seo_title": "Halong Bay Private Cruise | Adventure Asia",
        "seo_meta":  "Experience Halong Bay on a curated private cruise with Adventure Asia.",
        "trip_type": "cultural",
    })
    result = validate_node(state)
    assert result["quality_score"] == 10.0
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
    state = make_state(generated={
        "name":      "Tour",
        "subtitle":  "Sub",
        "summary":   "Summary text here",
        "highlights": ["h1"],
        "seo_title": "A" * 61,
        "seo_meta":  "Meta description",
        "trip_type": "cultural",
    })
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
