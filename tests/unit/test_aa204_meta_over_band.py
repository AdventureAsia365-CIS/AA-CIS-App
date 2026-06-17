"""AA-204 [F5-over-band]: over-length seo_meta is repaired in-graph (not just blunt-trimmed),
deterministic SEO length/sentence codes route into flag_fix independently of brand_audit status,
and the DB-write backstop trims to a complete sentence with an under-140 floor fallback.

Root cause (S64 diagnostic): validate_node fires SEO_META_TOO_LONG into state["failure_codes"],
but flag_fix built fix_keys only from state["brand_audit_codes"] (gated on status=="flagged"),
and SEO_META_TOO_LONG was absent from STAGE2_FIX_MAPPING — so over-length never reached repair.
"""

from services.content_generation.flag_fix_node import (
    STAGE2_FIX_MAPPING,
    _DETERMINISTIC_SEO_CODES,
    _should_fix,
    _build_fix_keys,
)
from api.routers.admin_pipeline import _trim_to_word_boundary


# ── 1. mapping: over-length code now maps to seo_meta ──────────────────────────
def test_over_length_code_mapped_to_seo_meta():
    assert STAGE2_FIX_MAPPING.get("SEO_META_TOO_LONG") == "seo_meta"
    assert "SEO_META_TOO_LONG" in _DETERMINISTIC_SEO_CODES


# ── 2. routing: deterministic SEO code drives fix even when audit is "pass" ─────
def test_deterministic_seo_code_routes_to_fix_when_audit_pass():
    state = {
        "brand_audit_status": "pass",
        "brand_audit_codes": [],
        "brand_audit_fields": [],
        "failure_codes": ["SEO_META_TOO_LONG"],
    }
    assert _should_fix(state) is True
    assert "seo_meta" in _build_fix_keys(state)


def test_under_short_and_incomplete_also_route():
    for code in ("META_TOO_SHORT", "META_INCOMPLETE_SENTENCE"):
        state = {"brand_audit_status": "pass", "failure_codes": [code]}
        assert _should_fix(state) is True
        assert "seo_meta" in _build_fix_keys(state)


# ── 3. clean pass: neither flagged nor det SEO code → skip (no wasted fix) ──────
def test_clean_pass_skips_fix():
    state = {
        "brand_audit_status": "pass",
        "brand_audit_codes": [],
        "brand_audit_fields": [],
        "failure_codes": [],
    }
    assert _should_fix(state) is False
    assert _build_fix_keys(state) == set()


def test_flagged_still_runs_and_merges_brand_keys():
    state = {
        "brand_audit_status": "flagged",
        "brand_audit_codes": ["SUMMARY_OFF_BRAND"],
        "brand_audit_fields": [],
        "failure_codes": ["SEO_META_TOO_LONG"],
    }
    assert _should_fix(state) is True
    keys = _build_fix_keys(state)
    assert "summary" in keys and "seo_meta" in keys


# ── 4. backstop: sentence-aware trim ends on a period within band ──────────────
def test_sentence_aware_trim_ends_on_period():
    # first sentence ends with a period that lands within [140,155]
    meta = (
        "This private fourteen-day Sri Lanka journey covers Sigiriya, the Kandy hill country, "
        "Yala leopard safaris and the warm southern coastline at ease. Guides included."
    )
    assert len(meta) > 155
    trimmed = _trim_to_word_boundary(meta, 155, sentence=True)
    assert 140 <= len(trimmed) <= 155
    assert trimmed.endswith(".")


# ── 5. backstop floor fallback: if sentence-cut < 140, use word-boundary cut ────
def test_backstop_floor_fallback_when_sentence_cut_too_short():
    # First sentence ends at char ~60 (well under 140); sentence=True would drop under floor.
    meta = (
        "A short opener ends here. and the journey then continues across the island for "
        "fourteen unhurried days from the central plains to the southern coastline with guides"
    )
    assert len(meta) > 155
    m_sent = _trim_to_word_boundary(meta, 155, sentence=True)
    m_word = _trim_to_word_boundary(meta, 155)
    # the 3-line backstop rule (admin_pipeline.py): prefer sentence cut unless it falls < 140
    m_final = m_sent if len(m_sent) >= 140 else m_word
    assert len(m_sent) < 140          # sentence cut underflows
    assert m_final == m_word          # fallback chose the longer word-boundary cut
    assert 140 <= len(m_final) <= 155
