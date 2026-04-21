import uuid

TENANT_ID = "00000000-0000-0000-0000-000000000001"
BATCH_ID = str(uuid.uuid4())

SAMPLE_TOUR = {
    "tour_id": str(uuid.uuid4()),
    "batch_id": BATCH_ID,
    "country": "Vietnam",
    "src_name": "HA LONG BAY 3 DAY CRUISE",
    "src_subtitle": "Ha Long Bay, Vietnam",
    "src_summary": "Explore the stunning limestone karsts of Ha Long Bay on this 3-day cruise.",
    "src_highlights": ["Kayaking through caves", "Sunset on deck", "Fresh seafood"],
    "src_itineraries": [
        {"day": 1, "title": "Embarkation", "description": "Board the cruise at noon."},
        {"day": 2, "title": "Kayaking", "description": "Morning kayak through Luon Cave."},
        {"day": 3, "title": "Disembarkation", "description": "Return to Hanoi by afternoon."},
    ],
    "pipeline_status": "ingested",
}

SAMPLE_SEO = {
    "keyword_search": "ha long bay cruise vietnam",
    "keyword_ideas": [
        {"keyword": "ha long bay 3 day cruise", "volume": 8100},
        {"keyword": "vietnam cruise package", "volume": 4400},
    ],
    "demographics": {"age_18_34": 0.45, "age_35_54": 0.38},
    "trends": {"jan": 72, "feb": 68, "mar": 85, "apr": 90},
    "provider": "dataforseo",
}

# aa_summary: 89 words — within brand rule v08 range of 80–150
SAMPLE_GENERATED = {
    "aa_name": "Ha Long Bay 3-Day Luxury Cruise",
    "aa_subtitle": "Sail through Vietnam's iconic limestone karst seascape",
    "aa_summary": (
        "Drift through the emerald waters of Ha Long Bay aboard a boutique junk cruise. "
        "Kayak into hidden sea caves, watch the sun dip below jagged karst peaks, "
        "and feast on fresh seafood pulled straight from the Gulf of Tonkin. "
        "Each morning begins with tai chi on the private sun deck and ends with a "
        "chef-prepared banquet served beneath a canopy of stars. "
        "On the final morning, wake to mist rolling across the bay before returning "
        "to Hanoi with memories of one of Southeast Asia's most remarkable landscapes."
    ),
    "aa_highlights": [
        "Kayak through the ancient Luon Cave at sunrise",
        "Sunset cocktails on the private sun deck",
        "Chef-prepared seafood banquet each evening",
    ],
    "aa_itineraries": "Day 1: Board at noon — settle into your cabin...",
    "seo_title": "Ha Long Bay 3-Day Cruise | Adventure Asia",
    "seo_meta": "Discover Ha Long Bay on a 3-day boutique cruise — kayaking, caves, and fresh seafood in Vietnam's most iconic seascape.",
    "model_editorial": "claude-3-5-sonnet-20241022",
    "model_schema": "gpt-4.1",
    "prompt_version": "v3.2",
    "retry_count": 0,
    "status": "generated",
}

# Verify word count at import time
_wc = len(SAMPLE_GENERATED["aa_summary"].split())
assert 80 <= _wc <= 150, f"SAMPLE_GENERATED aa_summary word count {_wc} out of 80-150 range"
