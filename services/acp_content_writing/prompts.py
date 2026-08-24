"""
services.acp_content_writing.prompts — T9 write-step (SKILL_v2.md workflow step 9) prompt
construction. Referenced (not reused, ADR §0.5) against services/acp_s4_social/writer.py's
ContentBrief-assembly shape — written fresh here against T8's real inputs (angle_gate_request/
angle_gate_option, channel_style.py, goals.py, brand_audience.py), not the old ContentBrief.

No hardcoded per-channel word-count numbers (STEP0 §Open Question #3 / build task's own explicit
instruction — neither SKILL_v2.md's own Channel Rules nor T8's real Bảng-2 source,
channel_style.py, states one) — length guidance is qualitative, from channel_style.py's
`structure`/`style` fields, same as the LLM already gets for angle generation (generate.py).
"""
from __future__ import annotations

from services.acp_angle_gate.brand_audience import BrandAudience
from services.acp_angle_gate.channel_style import ChannelStyle
from services.acp_angle_gate.goals import Goal

SYSTEM_PROMPT = """You are a strategy-led English content writer for a premium travel brand.

Write ONE finished piece of content for the exact channel, goal, and angle given below — not a
draft with placeholders, not an outline, the actual final copy a person could post as-is.

Rules:
- Combine the brand/audience context, the channel's structure and style, the selected goal's
  writing method, and the chosen angle every time. Do not write from channel style alone.
- Use concrete, verifiable details from the content seed given. Never invent a fact, number,
  measurement, or claim that is not in the content seed.
- Include the given call to action, worked naturally into the piece — not pasted on as a bare
  final sentence unless the channel's own style calls for that.
- Avoid generic AI-style writing: no vague benefit stacks, no fake urgency, no unsupported
  superlatives, no manipulative language, no rhetorical-question padding, no clichés ("hidden
  gem", "bucket list", "must-visit", "breathtaking", "unforgettable", "nestled", "tapestry",
  "embark on", "immerse yourself", "look no further", "in today's fast-paced world",
  "game-changing", "revolutionary", "unlock your potential").
- Sound human, specific, and lightly persuasive — not corporate, not hype-driven.
- Return ONLY the final content itself — no explanation, no preamble, no markdown code fence,
  no restating the brief back."""


def build_user_prompt(
    *, content_seed: str, goal: Goal, channel_style: ChannelStyle,
    brand_audience: BrandAudience, angle: dict, cta: str,
    destination: str | None = None, trip_name: str | None = None,
    revision_feedback: list[str] | None = None,
) -> str:
    """`angle` is the chosen `angle_gate_option` row (name/why_it_works/formula_fit/
    best_final_style). `revision_feedback` (AA-450 Phase 1's confirmed retry shape — specific,
    per-gate violation strings, not a generic "try again") is appended only on attempt 2."""
    segment = brand_audience.get("customer_segment") or "discerning travellers"
    mindset = brand_audience.get("customer_mindset") or "a well-travelled, detail-oriented mindset"

    lines = [
        f"CHANNEL: {channel_style['display_name']}",
        f"CHANNEL USE CASE: {channel_style['use_when']}",
        f"CHANNEL STRUCTURE: {channel_style['structure']}",
        f"CHANNEL STYLE: {channel_style['style']}",
        f"CHANNEL — AVOID: {channel_style['avoid']}",
        "",
        f"GOAL: {goal['name']} — {goal['description']}",
        f"WRITING METHOD FOR THIS GOAL: {goal['logic']}",
        "",
        f"AUDIENCE: {segment}",
        f"AUDIENCE MINDSET: {mindset}",
        "",
        f"SELECTED ANGLE: {angle['name']}",
        f"WHY THIS ANGLE WORKS: {angle['why_it_works']}",
        f"ANGLE'S BEST FINAL STYLE: {angle['best_final_style']}",
        "",
        f"CALL TO ACTION TO INCLUDE: {cta}",
        "",
        f"CONTENT SEED (the only source of facts — do not add facts beyond this):\n{content_seed}",
    ]
    if destination:
        lines.insert(-2, f"DESTINATION: {destination}")
    if trip_name:
        lines.insert(-2, f"TRIP: {trip_name}")
    if revision_feedback:
        lines.append(
            "\nPREVIOUS ATTEMPT FAILED QUALITY REVIEW — fix EXACTLY these issues, preserve "
            "everything else that was already working:\n- " + "\n- ".join(revision_feedback)
        )
    return "\n".join(lines)


__all__ = ["SYSTEM_PROMPT", "build_user_prompt"]
