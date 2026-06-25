"""AA-231 Phase A: prompt-level seo_meta band hardening (pure, no LLM).

Guards that the 140–155 band is now enforced both as a top-level STRICT RULE
in SYSTEM_PROMPT and as a prominent body line in build_rewrite_prompt (not only
buried inside the OUTPUT JSON FORMAT field description).
"""
from services.content_generation.prompts import SYSTEM_PROMPT, build_rewrite_prompt


def test_system_prompt_has_seo_meta_length_rule():
    assert "SEO META LENGTH" in SYSTEM_PROMPT
    assert "140" in SYSTEM_PROMPT
    assert "155" in SYSTEM_PROMPT


def test_rewrite_prompt_has_critical_length_requirement():
    tour = {
        "name": "Sri Lanka by Rail",
        "country": "Sri Lanka",
        "duration": "10 Days",
        "summary": "A private rail journey.",
        "description": "Cross-country by train.",
        "highlights": ["Sigiriya", "Kandy"],
        "itineraries": "Day 1 — Colombo",
        "inclusions": "Guide",
        "exclusions": "Flights",
    }
    seo = {
        "keywords": {"top_keywords": ["sri lanka tours", "kandy"]},
        "people_also_ask": ["Is Sri Lanka safe?"],
    }
    out = build_rewrite_prompt(tour, seo)

    assert "CRITICAL LENGTH REQUIREMENT" in out
    assert "140" in out
    assert "155" in out
    # band line must sit in the prompt body, before the JSON schema block
    assert out.index("CRITICAL LENGTH REQUIREMENT") < out.index("OUTPUT JSON FORMAT")
