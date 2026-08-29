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
from services.acp_shared.dfs_relevance import SearchDemandSignal

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

If a SEARCH DEMAND SIGNAL block is given below, treat it as real traveler search behavior you \
may use to judge which angle is most relevant or timely — never as a source of new facts about \
the trip itself. A "People also ask" question is evidence people search for that topic, not a \
claim about this specific trip; do not answer it as though it were a verified fact from the \
content seed. If it doesn't naturally fit the content seed, ignore it rather than forcing an \
angle around it.

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
    search_demand: SearchDemandSignal | None = None,
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
    # AA-469 Việc 4 — 6th, optional block. Omitted entirely (not "SEARCH DEMAND: none") when
    # there's no seo_context row for this tour, or when the row has neither PAA questions nor
    # related keywords — an empty/absent block would just be prompt noise, and the fixed
    # 5-block prompt this function has always built stays byte-identical for every request that
    # has no real signal to add (confirmed via STEP0 that 0 requests read seo_context before
    # this change; this keeps that the exact behavior for those still-common cases).
    if search_demand and (search_demand.people_also_ask or search_demand.related_keywords):
        lines = [f"SEARCH DEMAND SIGNAL (real traveler search behavior for this destination — "
                 f"see system prompt for how to use this):\nRelevance: {search_demand.relevance}"]
        if search_demand.people_also_ask:
            lines.append("Travelers also ask: " + "; ".join(search_demand.people_also_ask[:5]))
        if search_demand.related_keywords:
            lines.append("Related search terms: " + ", ".join(search_demand.related_keywords[:8]))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


__all__ = ["SYSTEM_PROMPT", "build_user_prompt"]
