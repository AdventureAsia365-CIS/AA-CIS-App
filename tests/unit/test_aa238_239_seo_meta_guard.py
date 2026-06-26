"""AA-238 + AA-239 — seo_meta band guard: forbidden-word + sentence-completeness.
Pure helper tests (no AWS, no DB, no LLM)."""
from services.content_generation.seo_meta_utils import (
    SEO_META_FORBIDDEN, meta_has_forbidden, meta_in_band, best_meta_candidate,
    _salvage_to_band, SEO_META_MIN, SEO_META_MAX,
)
from services.content_generation.flag_fix_node import (
    _should_fix, _build_fix_keys, _DETERMINISTIC_SEO_CODES, STAGE2_FIX_MAPPING,
)

_HEAD = ("Trek hidden Himalayan valleys with seasoned mountain guides and quiet "
         "lodges across remote alpine ridgelines")


def _mk(n, phrase=None):
    """Complete sentence of EXACTLY n chars ending in a period; optional forbidden phrase."""
    head = _HEAD if phrase is None else (_HEAD + " reached by " + phrase)
    assert n > len(head) + 2
    pad = n - len(head) - 2
    return head + " " + ("o" * pad) + "."


# ---------- AA-238: forbidden-word ----------

def test_forbidden_detects_space_and_hyphen():
    assert meta_has_forbidden("a public transport hop", SEO_META_FORBIDDEN)
    assert meta_has_forbidden("a public-transport hop", SEO_META_FORBIDDEN)
    assert not meta_has_forbidden("a private transfer hop", SEO_META_FORBIDDEN)


def test_in_band_rejects_forbidden_even_if_length_and_sentence_ok():
    m = _mk(150, phrase="public transport")
    assert SEO_META_MIN <= len(m) <= SEO_META_MAX
    assert meta_in_band(m) is True
    assert meta_in_band(m, SEO_META_FORBIDDEN) is False


def test_best_candidate_prefers_clean_pre_over_forbidden_post():
    post = _mk(150, phrase="public transport")
    pre = _mk(150)
    assert meta_in_band(pre, SEO_META_FORBIDDEN)
    out = best_meta_candidate(post, pre, forbidden=SEO_META_FORBIDDEN)
    assert not meta_has_forbidden(out, SEO_META_FORBIDDEN)
    assert out == pre


def test_validate_violation_routes_to_flag_fix():
    assert "BRAND_SEO_META_VIOLATION" in _DETERMINISTIC_SEO_CODES
    assert STAGE2_FIX_MAPPING.get("BRAND_SEO_META_VIOLATION") == "seo_meta"
    st = {"brand_audit_status": "pass", "failure_codes": ["BRAND_SEO_META_VIOLATION"]}
    assert _should_fix(st) is True
    assert "seo_meta" in _build_fix_keys(st)


# ---------- AA-239: salvage / sentence-completeness ----------

def test_salvage_recovers_in_band_complete_sentence():
    s = _mk(148) + " A longer tail clause that extends this text beyond the band limit area."
    out = _salvage_to_band(s)
    assert out == _mk(148)
    assert SEO_META_MIN <= len(out) <= SEO_META_MAX and out.endswith(".")


def test_salvage_returns_none_when_no_period_in_band():
    cut = ("This twelve-day public journey links Seoul cultural sites with Seoraksan forest "
           "trails an overnight temple stay in Gyeongju and Jeju")
    assert not cut.endswith(".")
    assert _salvage_to_band(cut) is None


def test_best_candidate_never_returns_raw_cut_when_pre_salvageable():
    cut_post = ("This twelve-day journey links Seoul cultural sites with Seoraksan forest "
                "trails an overnight temple stay in Gyeongju and Jeju island")
    pre = _mk(148)
    out = best_meta_candidate(cut_post, pre)
    assert meta_in_band(out) and out.endswith(".")


def test_band_boundaries_140_inclusive_139_reject():
    assert meta_in_band(_mk(140)) is True
    assert meta_in_band(_mk(139)) is False
