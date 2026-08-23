"""
services.acp_angle_gate.prompts — builds the system/user prompt for T8's one real LLM call
(generate.py::generate_angles()).

Workflow steps 4-6 (docs/claude_tasks/AA-449-00-step0-t8-angle-gate-investigation.md's saved
build task): apply the goal's formula -> generate exactly 3 angles, each shaped by that formula
applied a different way to the same title/content seed -> recommend the strongest one. All 3
folded into ONE LLM call (not 3 separate calls) — same "one call returns the full set" shape
generate_node() in services/content_generation/graph.py already uses.
"""
from __future__ import annotations

from services.acp_angle_gate.brand_audience import BrandAudience
from services.acp_angle_gate.channel_style import ChannelStyle
from services.acp_angle_gate.goals import Goal

SYSTEM_PROMPT = """You are a senior content strategist for Adventure Asia (AA), a travel \
company. Your job in this step is ONLY to generate 3 distinct content angles for one piece of \
content — you are NOT writing the final content itself (that happens later, after a human picks \
one of your 3 angles).

An "angle" here means: one specific strategic approach to the SAME content seed/topic, shaped by \
a chosen goal and its marketing formula. The 3 angles you generate must be genuinely different \
approaches — not 3 small wording variations of the same idea.

Each angle needs exactly 4 fields:
- name: a short, specific label for this angle (not generic, e.g. not just "Angle 1")
- why_it_works: 1-2 sentences, a concrete business reason this angle fits the goal/audience/\
channel — never vague ("this is engaging")
- formula_fit: name the marketing formula step-shape this angle follows (from the goal's own \
formula, given below) and briefly how this specific angle realizes it
- best_final_style: how this angle should be WRITTEN when it becomes final content on the given \
channel — follow the channel's own style/structure guidance given below, do not invent a \
different style

Never invent facts, statistics, testimonials, or claims not present in the content seed given to \
you. If the content seed lacks a concrete detail a strong angle would want, say so honestly \
rather than fabricating one.

Return ONLY valid JSON, no markdown fences, no commentary, in exactly this shape:
{
  "angles": [
    {"name": "...", "why_it_works": "...", "formula_fit": "...", "best_final_style": "..."},
    {"name": "...", "why_it_works": "...", "formula_fit": "...", "best_final_style": "..."},
    {"name": "...", "why_it_works": "...", "formula_fit": "...", "best_final_style": "..."}
  ],
  "recommended_index": 0,
  "recommendation_reason": "short reason this one is the strongest of the 3"
}
recommended_index must be 0, 1, or 2."""


def build_user_prompt(
    *, content_seed: str, goal: Goal, channel_style: ChannelStyle, brand_audience: BrandAudience,
    destination: str | None, trip_name: str | None,
) -> str:
    segment = brand_audience.get("customer_segment") or "(not specified for this tenant)"
    mindset = brand_audience.get("customer_mindset") or "(not specified for this tenant)"

    parts = [
        f"CONTENT SEED (from a curated atom — the concrete detail this content must be about):\n"
        f"{content_seed}",
    ]
    if trip_name:
        parts.append(f"TRIP: {trip_name}" + (f" ({destination})" if destination else ""))
    parts.append(
        f"GOAL: {goal['name']}\n"
        f"Goal description: {goal['description']}\n"
        f"Formula logic: {goal['logic']}\n"
        f"Marketing term: {goal['marketing_term']}"
    )
    parts.append(
        f"CHANNEL: {channel_style['display_name']}\n"
        f"Use when: {channel_style['use_when']}\n"
        f"Structure: {channel_style['structure']}\n"
        f"Style: {channel_style['style']}\n"
        f"Avoid: {channel_style['avoid']}"
    )
    parts.append(
        f"BRAND AUDIENCE (fixed, from this tenant's brand identity — write angles that would "
        f"genuinely appeal to THIS audience, not a generic traveller):\n"
        f"Customer segment: {segment}\n"
        f"Customer mindset: {mindset}"
    )
    return "\n\n".join(parts)


__all__ = ["SYSTEM_PROMPT", "build_user_prompt"]
