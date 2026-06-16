"""F5 (AA-194): tests for _trim_to_word_boundary — seo title/meta trimming.

Covers the SEO title (60, sentence=False) and seo_meta (155, sentence=True)
trim paths used in admin_pipeline at the export step.
"""

from api.routers.admin_pipeline import _trim_to_word_boundary


def _ends_on_word_boundary(original: str, trimmed: str) -> bool:
    """True if `trimmed` is a clean prefix of `original.strip()` that does not
    cut a word in half (it ends exactly where a space/end-of-string is)."""
    src = original.strip()
    if not src.startswith(trimmed):
        return False
    # either consumed everything, or the very next source char is a space
    return len(trimmed) == len(src) or src[len(trimmed)] == " "


# ── never split mid-word ──────────────────────────────────────────────────────

def test_trim_never_splits_mid_word():
    # limit 10 lands inside "luxury" -> must back up to the space after "Bhutan"
    text = "Bhutan luxury adventure journey"
    out = _trim_to_word_boundary(text, 10)
    assert out == "Bhutan"
    assert len(out) <= 10
    assert _ends_on_word_boundary(text, out)


# ── SEO title path (limit 60, sentence=False) ─────────────────────────────────

def test_trim_title_under_sixty_and_word_boundary():
    text = ("Discreet Executive Bhutan Highlands Private Journey for "
            "Discerning Senior Travellers")
    out = _trim_to_word_boundary(text, 60)
    assert len(out) <= 60
    assert _ends_on_word_boundary(text, out)


# ── seo_meta path, sentence=True, terminator present ──────────────────────────

def test_trim_meta_sentence_ends_on_terminator():
    # first sentence ends well inside 155; tail (no terminator) pushes total > 155
    text = ("We craft a discreet private journey across the highlands. "
            "A second clause continues at length without any further sentence "
            "ending punctuation to force the trim window past the limit here")
    assert len(text) > 155
    out = _trim_to_word_boundary(text, 155, sentence=True)
    assert out.endswith(".")
    assert out == "We craft a discreet private journey across the highlands."
    assert len(out) <= 155


# ── seo_meta path, sentence=True, NO terminator in window (fallback branch) ────

def test_trim_meta_sentence_no_terminator_falls_back_to_word_boundary():
    # no . ! ? anywhere in the first 155 chars -> must fall back to word boundary
    text = ("a discreet private journey across the quiet highlands for "
            "discerning senior professionals seeking refined unhurried "
            "experiences far from the usual crowded tourist routes and noise "
            "of mass market travel options today")
    assert len(text) > 155
    out = _trim_to_word_boundary(text, 155, sentence=True)
    assert "." not in out and "!" not in out and "?" not in out
    assert len(out) <= 155
    assert _ends_on_word_boundary(text, out)


# ── already within limit -> stripped, otherwise unchanged ─────────────────────

def test_trim_already_within_limit_returns_stripped_unchanged():
    assert _trim_to_word_boundary("  Short refined title  ", 60) == "Short refined title"
    # already short and no surrounding whitespace -> identical
    assert _trim_to_word_boundary("Short refined title", 60) == "Short refined title"


# ── empty / None guard ────────────────────────────────────────────────────────

def test_trim_none_and_empty_return_empty_string():
    assert _trim_to_word_boundary(None, 60) == ""
    assert _trim_to_word_boundary("", 155, sentence=True) == ""
