"""F4 (AA-196): pre_audit_checks flags generic day titles in itineraries."""

from services.content_generation.brand_audit_node import pre_audit_checks
from services.content_generation.brand_standards import AA_COWORK_STRUCTURE_PROMPT
from services.content_generation.flag_fix_node import STAGE2_FIX_MAPPING


def _itin(generated_itin):
    """Minimal clean generated dict carrying only the itineraries under test."""
    return {
        "name": "Bhutan Highlands Journey",
        "subtitle": "A refined private journey",
        "seo_meta": "A discreet private journey across the highlands.",
        "highlights": [],
        "itineraries": generated_itin,
    }


def test_pre_audit_flags_generic_exploration_title():
    codes = pre_audit_checks(_itin("Day 2 -- Exploration"))
    assert "ITINERARY_DAY_TITLE_GENERIC" in codes


def test_pre_audit_flags_generic_free_day_title():
    codes = pre_audit_checks(_itin("Day 3 -- Free Day"))
    assert "ITINERARY_DAY_TITLE_GENERIC" in codes


def test_pre_audit_flags_generic_arrival_and_departure_titles():
    assert "ITINERARY_DAY_TITLE_GENERIC" in pre_audit_checks(_itin("Day 1 -- Arrival"))
    assert "ITINERARY_DAY_TITLE_GENERIC" in pre_audit_checks(_itin("Day 1 -- Arrival Day"))
    assert "ITINERARY_DAY_TITLE_GENERIC" in pre_audit_checks(_itin("Day 9 -- Departure"))
    assert "ITINERARY_DAY_TITLE_GENERIC" in pre_audit_checks(_itin("Day 4 -- Transfer"))


def test_pre_audit_flags_generic_title_within_multiday_string():
    multiday = (
        "Day 1 -- Trekking to Sapa Valley Villages\n"
        "Day 2 -- Exploration\n"
        "Day 3 -- Cycling the Mae Taeng Valley"
    )
    codes = pre_audit_checks(_itin(multiday))
    assert "ITINERARY_DAY_TITLE_GENERIC" in codes


def test_pre_audit_good_place_activity_title_not_flagged():
    codes = pre_audit_checks(_itin("Day 2 -- Trekking to Sapa Valley Villages"))
    assert "ITINERARY_DAY_TITLE_GENERIC" not in codes


def test_pre_audit_generic_word_inside_descriptive_title_not_flagged():
    # "Exploration" / "Transfer" as part of a place/activity title must NOT trip
    codes = pre_audit_checks(
        _itin("Day 2 -- Exploration of the Mae Taeng Valley Waterfalls")
    )
    assert "ITINERARY_DAY_TITLE_GENERIC" not in codes


def test_pre_audit_clean_multiday_itinerary_not_flagged():
    multiday = (
        "Day 1 -- Trekking to Sapa Valley Villages\n"
        "Day 2 -- Mae Taeng Valley Cycling Day: Waterfalls, Farmland & Temple"
    )
    codes = pre_audit_checks(_itin(multiday))
    assert "ITINERARY_DAY_TITLE_GENERIC" not in codes


def test_stage2_fix_mapping_routes_day_title_code_to_itineraries():
    assert STAGE2_FIX_MAPPING["ITINERARY_DAY_TITLE_GENERIC"] == "itineraries"


def test_failure_code_present_in_brand_standards():
    assert "ITINERARY_DAY_TITLE_GENERIC" in AA_COWORK_STRUCTURE_PROMPT
