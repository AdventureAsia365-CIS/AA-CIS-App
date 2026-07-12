"""AA-251 (ADR-2026-021, hướng 4): seed builder tour-name specificity + fuzzy
DFS_INTENT_UNDERUSED match. Root cause was (a) seed always generic
"{country} tours" and (b) match requiring the whole keyword phrase verbatim in
seo_title+seo_meta — content mentioning "South Korea" still failed for lacking
the literal word "tours" glued to it.
"""

from services.content_generation.graph import validate_node, _keyword_intent_matched
from services.seo_intelligence.seed_builder import build_seed
from tests.unit.test_content_graph import make_state


# ── build_seed: tour_name fallback (AA-251) ─────────────────────────────────

def test_build_seed_tour_name_used_when_no_activity():
    seed = build_seed("South Korea", None, "Korea's Coast-to-Coast Ride")
    assert seed == "Korea's Coast-to-Coast Ride South Korea"


def test_build_seed_tour_name_only_no_country():
    assert build_seed("", None, "Sunset Kayak Adventure") == "Sunset Kayak Adventure"


def test_build_seed_activity_still_wins_over_tour_name():
    # AA-197 behavior unchanged: activity+country is more specific than tour_name.
    seed = build_seed("South Korea", ["Cycling, Hiking"], "Korea's Coast-to-Coast Ride")
    assert seed == "Cycling in South Korea"


def test_build_seed_no_tour_name_falls_back_to_country_tours():
    # AA-197 regression: 2-arg callers and callers with no tour_name unaffected.
    assert build_seed("South Korea", None) == "South Korea tours"
    assert build_seed("South Korea", None, "") == "South Korea tours"


# ── _keyword_intent_matched: token overlap, not verbatim substring (AA-251) ──

def test_intent_matched_without_literal_tours_suffix():
    # kw is "south korea tours" but content only has "South Korea" — should match
    # once "tours" is treated as filler, not held against the content.
    assert _keyword_intent_matched(
        ["south korea tours"],
        "korea's coast-to-coast ride | discreet cycling through south korea",
    )


def test_intent_not_matched_when_truly_off_topic():
    assert not _keyword_intent_matched(
        ["sri lanka wildlife safari"],
        "japan alpine hiking retreat for discerning travellers",
    )


def test_intent_matched_partial_token_overlap_above_threshold():
    # 2/3 significant tokens overlap (>= 0.5 threshold) -> matched
    assert _keyword_intent_matched(
        ["best hiking trails seoul"],
        "seoul hiking guide for discreet executive travel",
    )


# ── validate_node: DFS_INTENT_UNDERUSED end-to-end (AA-251) ─────────────────

def _base_generated(seo_title, seo_meta):
    return {
        "name":        "Korea's Coast-to-Coast Ride",
        "subtitle":    "A discreet cycling traverse of South Korea's coastlines",
        "summary":     "A multi-day cycling route tracing South Korea's eastern and western "
                       "coastlines, built for discerning riders seeking uncrowded roads.",
        "highlights":  [
            "Coastal cycling routes away from tourist crowds",
            "Support vehicle and daily bike maintenance included",
            "Private lodging each night along the route",
        ],
        "itineraries": "Day 1: Depart Incheon, ride west coast. Day 2: Cross-country transfer. "
                       "Day 3: Ride east coast to Gangneung.",
        "seo_title":   seo_title,
        "seo_meta":    seo_meta,
        "trip_type":   "adventure",
    }


def test_validate_no_false_positive_generic_country_tours_keyword():
    # This is the AA-251 regression case: seed fell back to "South Korea tours",
    # DFS returned "south korea tours" as top keyword, content is genuinely about
    # South Korea cycling but never says the literal word "tours" — must NOT fire.
    state = make_state(
        tour={"name": "Korea's Coast-to-Coast Ride", "country": "South Korea"},
        seo={"top_keywords": [{"keyword": "south korea tours"}]},
        generated=_base_generated(
            seo_title="Korea's Coast-to-Coast Ride | Adventure Asia",
            seo_meta="A discreet, multi-day cycling traverse of South Korea's coastlines, "
                     "designed for riders who prefer uncrowded roads and private lodging.",
        ),
    )
    result = validate_node(state)
    assert "DFS_INTENT_UNDERUSED" not in result["failure_codes"]


def test_validate_still_catches_truly_off_topic_content():
    state = make_state(
        tour={"name": "Korea's Coast-to-Coast Ride", "country": "South Korea"},
        seo={"top_keywords": [{"keyword": "south korea tours"}]},
        generated=_base_generated(
            seo_title="Sri Lanka Wildlife Safari | Adventure Asia",
            seo_meta="A guided wildlife safari through Sri Lanka's national parks, spotting "
                     "leopards and elephants across remote reserves.",
        ),
    )
    result = validate_node(state)
    assert "DFS_INTENT_UNDERUSED" in result["failure_codes"]
