"""
services.acp_content_writing.framework_rubrics — T10's F8-equivalent rubric table (AA-450-02
gate map row "F8 framework judge").

Same mechanism as services/acp_produce/gates.py::FRAMEWORK_RUBRICS (binary 1/0 per criterion,
mandatory evidence quote for every 1, judge never sees the writer's own prompt) but a different
table: N7's FRAMEWORK_RUBRICS only covers {hub, PAS, AIDA, hook_story_cta, hook_beats_payoff,
reader_as_hero} — T8's 8 goals (services/acp_angle_gate/goals.py) use `marketing_term` values
including SLAP/FAB/BAB/5W1H that have no entry there.

Every entry below is derived MECHANICALLY from that goal's own already-written `logic` field in
goals.py — one criterion per named beat, same "framework as an ordered arc of beats" shape N7's
own AIDA/PAS entries already use — not invented from scratch. Keyed by GOAL key (not by
marketing_term/framework name), since goals.py is the one real source of truth this repo has for
what each goal's method actually requires, and 2 goals (lead_generation, conversion) already
list a compound method ("AIDA hoặc PAS", "SLAP" per Bang 1's own kept-verbatim wording, AA-449
Decision 2) — keying by goal avoids re-deriving which single framework name a compound entry
would even resolve to.
"""
from __future__ import annotations

# AA-449 Decision 2 kept Bang 1's wording verbatim, including its 2 flagged discrepancies vs
# SKILL_v2.md — this table follows the same discipline, deriving criteria from goals.py's real
# `logic` strings as they exist today, not "corrected" back to SKILL_v2.md's own wording.
GOAL_FRAMEWORK_RUBRICS: dict[str, list[str]] = {
    "promotion": [
        "Attention: opens with a sharp, concrete hook — not a generic scene-setting line",
        "Interest: builds relevant detail or context after the opening",
        "Desire: shows concretely why this matters to the reader, not an abstract claim",
        "Action: ends with one clear call to action",
    ],
    "lead_generation": [
        "Problem or attention: names the friction or desired outcome clearly",
        "Insight: makes the problem or opportunity concrete, not vague",
        "Solution/desire: shows the brand's relevant value as the resolution",
        "CTA: moves the reader toward a lead-capture action (enquiry, waitlist, consultation)",
    ],
    "conversion": [
        "Stop: opens with a specific, non-clickbait hook",
        "Look: makes the reader see the problem or offer clearly",
        "Act: gives one direct next step",
        "Proceed: reinforces why acting now makes sense",
    ],
    "introduction_awareness": [
        "Hook: a clear, specific first-line insight",
        "Context: explains what this is and why it matters",
        "Value: states what the reader should understand or take away",
        "CTA: ends with a soft, low-pressure next step",
    ],
    "trust_building": [
        "Problem: names a real weakness or gap in the status quo",
        "Insight: shows what better judgment or expertise sees that others miss",
        "Proof: gives a concrete, verifiable detail — never a fabricated claim",
        "Action: ends with a low-pressure next step",
    ],
    "engagement_conversation": [
        "Hook: a relatable, specific observation",
        "Value: a useful point, contrast, story, or perspective",
        "CTA: ends with a grounded question or response prompt, not a generic sign-off",
    ],
    "event_announcement": [
        "States what is happening, specifically",
        "Makes clear who it is for",
        "States why it matters",
        "States why the brand is involved",
        "Ends with one clear call to action",
    ],
    "product_service_explanation": [
        "Feature: states what exists, concretely",
        "Advantage: explains why it improves the reader's situation",
        "Benefit: states why the reader specifically cares",
    ],
}

DEFAULT_RUBRIC = ["the piece follows a clear, deliberate structure matching its stated goal"]


def get_framework_rubric(goal_key: str) -> list[str]:
    return GOAL_FRAMEWORK_RUBRICS.get(goal_key, DEFAULT_RUBRIC)


__all__ = ["GOAL_FRAMEWORK_RUBRICS", "DEFAULT_RUBRIC", "get_framework_rubric"]
