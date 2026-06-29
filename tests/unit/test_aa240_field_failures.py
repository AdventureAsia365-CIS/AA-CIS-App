"""AA-240: unit tests for _derive_field_failures — per-field failure re-derivation.

These import the REAL helper from api.routers.admin_pipeline and the REAL maps/consts from
services.content_generation.graph + seo_meta_utils (no mocking of the logic under test), so a
threshold drift in validate_node would surface here. Pattern follows S79: never assert against a
re-implemented copy of the logic.
"""
import pytest

from api.routers.admin_pipeline import _derive_field_failures


def _codes(*c):
    return list(c)


def test_meta_too_short_surfaced_when_still_short():
    gc = {"seo_meta": "Short meta ends here."}
    out = _derive_field_failures(gc, _codes("META_TOO_SHORT"))
    hit = [f for f in out if f["code"] == "META_TOO_SHORT"]
    assert hit and hit[0]["field"] == "seo_meta"
    assert "<140" in hit[0]["reason"]


def test_meta_fixed_not_surfaced():
    # reviewer fixed meta into the 140-155 band -> code must NOT re-surface (dynamic re-derive)
    fixed = ("Explore the highland trails and quiet valleys on a thoughtfully paced "
             "private guided route that ends on a complete and proper sentence here today.")
    assert 140 <= len(fixed) <= 155
    out = _derive_field_failures({"seo_meta": fixed}, _codes("META_TOO_SHORT"))
    assert not any(f["code"] == "META_TOO_SHORT" for f in out)


def test_meta_too_long_surfaced():
    gc = {"seo_meta": "x" * 200}
    out = _derive_field_failures(gc, _codes("SEO_META_TOO_LONG"))
    assert any(f["code"] == "SEO_META_TOO_LONG" and ">155" in f["reason"] for f in out)


def test_title_too_long_then_short():
    long_t = {"seo_title": "y" * 75}
    long_out = _derive_field_failures(long_t, _codes("SEO_TITLE_TOO_LONG"))
    assert any(f["code"] == "SEO_TITLE_TOO_LONG" for f in long_out)
    short_t = {"seo_title": "Short title"}
    short_out = _derive_field_failures(short_t, _codes("SEO_TITLE_TOO_LONG"))
    assert not any(f["code"] == "SEO_TITLE_TOO_LONG" for f in short_out)


def test_forbidden_word_maps_to_field():
    gc = {"aa_summary": "A truly bespoke journey across the range."}
    out = _derive_field_failures(gc, _codes("FORBIDDEN_WORD"))
    hit = [f for f in out if f["code"] == "FORBIDDEN_WORD"]
    assert hit and hit[0]["field"] == "aa_summary"
    assert "bespoke" in hit[0]["reason"]


def test_missing_field_scans_empty_column():
    gc = {"aa_name": "x", "aa_subtitle": "x", "aa_summary": "x",
          "aa_highlights": ["a", "b", "c"], "aa_itineraries": "",
          "seo_title": "x", "seo_meta": "x"}
    out = _derive_field_failures(gc, _codes("MISSING_FIELD"))
    assert any(f["field"] == "aa_itineraries" and f["code"] == "MISSING_FIELD" for f in out)


def test_highlights_too_few():
    out = _derive_field_failures({"aa_highlights": ["only", "two"]}, _codes("HIGHLIGHTS_TOO_FEW"))
    assert any(f["code"] == "HIGHLIGHTS_TOO_FEW" and "cần" in f["reason"] for f in out)


def test_highlights_too_few_jsonstring_input():
    # asyncpg may hand back jsonb as a string — helper must parse it
    out = _derive_field_failures({"aa_highlights": '["a","b"]'}, _codes("HIGHLIGHTS_TOO_FEW"))
    assert any(f["code"] == "HIGHLIGHTS_TOO_FEW" for f in out)


def test_brand_violation_hyphen_variant():
    gc = {"seo_meta": "Travel by public-transport through the region affordably."}
    out = _derive_field_failures(gc, _codes("BRAND_SEO_META_VIOLATION"))
    assert any(f["code"] == "BRAND_SEO_META_VIOLATION" and f["field"] == "seo_meta" for f in out)


def test_static_code_maps_via_code_field_map():
    out = _derive_field_failures({"aa_itineraries": "Day 1 something"}, _codes("ITINERARY_STRUCTURE_WEAK"))
    assert any(f["code"] == "ITINERARY_STRUCTURE_WEAK" and f["field"] == "aa_itineraries" for f in out)


def test_empty_codes_returns_empty():
    gc = {"seo_meta": "x" * 5, "seo_title": "y" * 80}
    # no codes fired historically -> nothing surfaced even if content looks bad
    assert _derive_field_failures(gc, []) == []


def test_code_present_but_field_clean_not_surfaced():
    # historical SEO_TITLE_TOO_LONG but current title is short -> suppressed
    out = _derive_field_failures({"seo_title": "OK short title"}, _codes("SEO_TITLE_TOO_LONG"))
    assert out == []
