import pytest
from shared.validators.rules import validate_content, ALL_VALIDATORS

PERFECT_CONTENT = {
    "name":      "Halong Bay Private Cruise",
    "subtitle":  "A curated journey through karst landscapes",
    "summary":   "Discover the timeless beauty of Halong Bay on a refined private cruise designed for discerning travellers seeking immersive experiences.",
    "highlights": [
        "Private sundeck with panoramic views",
        "Chef-prepared Vietnamese cuisine onboard",
        "Guided kayaking through hidden lagoons",
    ],
    "seo_title": "Halong Bay Private Cruise | Adventure Asia",
    "seo_meta":  "Experience Halong Bay on a curated private cruise with Adventure Asia. Tailored journeys for discerning travellers seeking refined luxury.",
    "trip_type": "cultural",
}

# --- Full suite ---

def test_29_validators_registered():
    assert len(ALL_VALIDATORS) == 29

def test_perfect_content_passes_all():
    result = validate_content(PERFECT_CONTENT)
    assert result["score"] == 10.0
    assert result["failed"] == 0
    assert result["audit_status"] == "passed"

def test_empty_content_fails():
    result = validate_content({})
    assert result["score"] < 7.0
    assert result["audit_status"] in ["flagged", "failed"]

# --- Layer 1: Required Fields ---

def test_v01_missing_name():
    c = {**PERFECT_CONTENT, "name": ""}
    result = validate_content(c)
    assert any("L1-01" in i for i in result["issues"])

def test_v04_highlights_min_2():
    c = {**PERFECT_CONTENT, "highlights": ["Only one"]}
    result = validate_content(c)
    assert any("L1-04" in i for i in result["issues"])

# --- Layer 2: Brand Voice ---

def test_v07_forbidden_word_cheap():
    c = {**PERFECT_CONTENT, "summary": "Get the cheapest tour in Asia with our best deals " * 3}
    result = validate_content(c)
    assert any("L2-07" in i for i in result["issues"])

def test_v08_no_preferred_words():
    c = {**PERFECT_CONTENT,
         "name":     "Vietnam Tour",
         "subtitle": "A great trip for you",
         "summary":  "This is a very basic tour description without any special words here." * 2}
    result = validate_content(c)
    assert any("L2-08" in i for i in result["issues"])

def test_v09_exclamation_mark():
    c = {**PERFECT_CONTENT, "summary": PERFECT_CONTENT["summary"] + " Amazing!"}
    result = validate_content(c)
    assert any("L2-09" in i for i in result["issues"])

def test_v11_summary_too_short():
    c = {**PERFECT_CONTENT, "summary": "Too short."}
    result = validate_content(c)
    assert any("L2-11" in i for i in result["issues"])

def test_v14_first_person():
    c = {**PERFECT_CONTENT, "summary": "We are offering you the best tours. " * 3}
    result = validate_content(c)
    assert any("L2-14" in i for i in result["issues"])

def test_v15_generic_opener():
    c = {**PERFECT_CONTENT, "summary": "Are you looking for the perfect tour? " * 3}
    result = validate_content(c)
    assert any("L2-15" in i for i in result["issues"])

# --- Layer 3: SEO ---

def test_v18_seo_title_too_long():
    c = {**PERFECT_CONTENT, "seo_title": "A" * 61}
    result = validate_content(c)
    assert any("L3-18" in i for i in result["issues"])

def test_v20_seo_meta_too_long():
    c = {**PERFECT_CONTENT, "seo_meta": "A" * 161}
    result = validate_content(c)
    assert any("L3-20" in i for i in result["issues"])

def test_v21_seo_meta_too_short():
    c = {**PERFECT_CONTENT, "seo_meta": "Short meta."}
    result = validate_content(c)
    assert any("L3-21" in i for i in result["issues"])

def test_v24_invalid_trip_type():
    c = {**PERFECT_CONTENT, "trip_type": "invalid_type"}
    result = validate_content(c)
    assert any("L3-24" in i for i in result["issues"])

def test_v24_valid_trip_types():
    for t in ["cultural", "adventure", "wellness", "culinary", "wildlife"]:
        c = {**PERFECT_CONTENT, "trip_type": t}
        result = validate_content(c)
        assert not any("L3-24" in i for i in result["issues"])

# --- Layer 4: Structure ---

def test_v25_too_many_highlights():
    c = {**PERFECT_CONTENT, "highlights": [f"Highlight number {i} is here" for i in range(9)]}
    result = validate_content(c)
    assert any("L4-25" in i for i in result["issues"])

def test_v28_duplicate_highlights():
    c = {**PERFECT_CONTENT, "highlights": [
        "Private sundeck with panoramic views",
        "Private sundeck with panoramic views",
        "Kayaking excursion through lagoons",
    ]}
    result = validate_content(c)
    assert any("L4-28" in i for i in result["issues"])

def test_v29_name_too_long():
    c = {**PERFECT_CONTENT, "name": "A" * 81}
    result = validate_content(c)
    assert any("L4-29" in i for i in result["issues"])

# --- Score calculation ---

def test_score_range():
    result = validate_content(PERFECT_CONTENT)
    assert 0.0 <= result["score"] <= 10.0

def test_audit_status_flagged():
    # Make ~half fail
    c = {
        "name":      "Vietnam Tour",
        "subtitle":  "A trip",
        "summary":   "Short.",
        "highlights": ["one"],
        "seo_title": "A" * 61,
        "seo_meta":  "Short",
        "trip_type": "bad_type",
    }
    result = validate_content(c)
    assert result["audit_status"] in ["flagged", "failed"]
