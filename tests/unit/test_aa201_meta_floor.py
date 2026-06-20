"""AA-201 [AA-193·F5-followup]: seo_meta lower-band floor + complete-sentence rule.

Bug fixed: AA-194 over-corrected — the sentence-trim cut seo_meta to the last period
within 155 chars with NO lower bound, producing 78-93 char meta (under the 140-155 band).
This adds META_TOO_SHORT (floor 140) and upgrades META_INCOMPLETE_SENTENCE to require a
real verb / non-trailing ending, porting Cowork v5 repair_seo_fields into the cloud graph.
"""

from services.content_generation.graph import (
    SEO_META_MIN,
    _FAILURE_MAP,
    meta_complete_sentence,
    validate_node,
)
from api.routers.admin_pipeline import _trim_to_word_boundary


def _baseline_generated(meta: str) -> dict:
    """A generated dict that passes the non-meta checks, varying only seo_meta."""
    return {
        "name": "Highlands of Northern Vietnam",
        "subtitle": "Slow mornings in Sapa's terraced valleys",
        "summary": "Trace the ridgelines above Sapa with a private guide who knows the trails.",
        "description": "A quiet, well-paced route through the terraced highlands of the north.",
        "highlights": [
            "Sunrise over the Muong Hoa terraces",
            "Tea tasting with a Red Dao family",
            "Private transfer to Ta Phin village",
        ],
        "itineraries": (
            "Day 1 — Arrival in Sapa. Settle into the valley and rest.\n\n"
            "Day 2 — Trek to Ta Phin and meet local artisans before returning."
        ),
        "seo_title": "Private Sapa Highlands Trek in Northern Vietnam",
        "seo_meta": meta,
    }


def _codes(meta: str) -> list[str]:
    out = validate_node({"generated": _baseline_generated(meta), "tour": {}})
    return out["failure_codes"]


# Complete sentences (verb present, proper ending) but UNDER the 140 floor
META_78 = "This private Sri Lanka journey covers Sigiriya and Kandy with local guides."
META_93 = "This guided Vietnam route visits Hanoi, Hue and Hoi An at an easy, unhurried walking pace."

# In-band (140-155), complete sentence with a verb
META_148 = (
    "This private Sri Lanka journey covers Sigiriya, Kandy and Yala with unhurried "
    "pacing, expert local guides and comfortable transfers throughout the route."
)

# Ends on a banned trailing word ("with") even though it ends in a period
META_BAD_ENDING = (
    "This curated northern route explores temples, markets and quiet coastline that "
    "stretches across the forested provinces of the far north with."
)

# No linking/action verb at all
META_NO_VERB = "A private route through Sigiriya and Kandy."


def test_short_complete_meta_fires_too_short_78():
    assert len(META_78) < SEO_META_MIN
    codes = _codes(META_78)
    assert "META_TOO_SHORT" in codes
    # it is a valid sentence — the floor must be independent of the sentence check
    assert "META_INCOMPLETE_SENTENCE" not in codes


def test_short_complete_meta_fires_too_short_93():
    assert len(META_93) < SEO_META_MIN
    codes = _codes(META_93)
    assert "META_TOO_SHORT" in codes
    assert "META_INCOMPLETE_SENTENCE" not in codes


def test_in_band_complete_meta_clean():
    assert SEO_META_MIN <= len(META_148) <= 155
    codes = _codes(META_148)
    assert "META_TOO_SHORT" not in codes
    assert "META_INCOMPLETE_SENTENCE" not in codes


def test_bad_trailing_word_fires_incomplete():
    assert meta_complete_sentence(META_BAD_ENDING) is False
    assert "META_INCOMPLETE_SENTENCE" in _codes(META_BAD_ENDING)


def test_short_fragment_fires_incomplete():
    assert meta_complete_sentence(META_NO_VERB) is False
    assert "META_INCOMPLETE_SENTENCE" in _codes(META_NO_VERB)


def test_too_short_registered_in_failure_map():
    assert _FAILURE_MAP["META_TOO_SHORT"] == ("seo", 0.5)


def test_trim_long_meta_no_midword_cut():
    """168-char input → <=155, never cuts mid-word, no sentence-based hard cut."""
    src = (
        "This private journey through the northern highlands covers Sapa, Bac Ha and "
        "the Muong Hoa valley with unhurried pacing, expert local guides and warm homestays."
    )
    assert len(src) > 155
    trimmed = _trim_to_word_boundary(src, 155)
    assert len(trimmed) <= 155
    # every word kept is a whole word from the source — no mid-token split
    assert set(trimmed.split()).issubset(set(src.split()))
    # source resumes at a word boundary right after the kept prefix
    assert src[len(trimmed)] == " " or trimmed == src[:len(trimmed)].rstrip()
