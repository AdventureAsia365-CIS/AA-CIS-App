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
from services.acp_angle_gate.goals import Goal
from services.acp_shared.dfs_relevance import SearchDemandSignal

# AA-469 Việc 4 (flow-order fix, this session) — channel moved OUT of angle generation entirely.
# Confirmed with Nghiệp: the real order is atom+DFS/PAA+brand -> Goal -> 3 angles -> pick 1 ->
# THEN pick Channel -> T9 write. Angle generation used to take a `channel_style` param and
# include a CHANNEL block here; both are gone. This is safe, not a content-quality regression:
# services/acp_content_writing/prompts.py::build_user_prompt() (T9's OWN prompt, unchanged by
# this session) already includes the FULL channel_style block (structure/style/avoid) at write
# time, independently of whatever this module produces — channel-fit was always re-applied in
# full at write time regardless, this only removes an early, now-redundant channel-conditioning
# pass over the angle's own `best_final_style` field.

SYSTEM_PROMPT = """You are a senior content strategist for Adventure Asia (AA), a travel \
company. Your job in this step is ONLY to generate 3 distinct content angles for one piece of \
content — you are NOT writing the final content itself (that happens later, after a human picks \
one of your 3 angles AND a channel — neither the specific channel nor its format rules are known \
yet at this step).

An "angle" here means: one specific strategic approach to the SAME content seed/topic, shaped by \
a chosen goal and its marketing formula. The 3 angles you generate must be genuinely different \
approaches — not 3 small wording variations of the same idea.

Each angle needs exactly 4 required fields, plus a 5th when questions are supplied below:
- name: a short, specific label for this angle (not generic, e.g. not just "Angle 1")
- why_it_works: 1-2 sentences, a concrete business reason this angle fits the goal/audience — \
never vague ("this is engaging")
- formula_fit: name the marketing formula step-shape this angle follows (from the goal's own \
formula, given below) and briefly how this specific angle realizes it
- best_final_style: how this angle's own story/narrative should feel and unfold when it's \
eventually written — tone, shape, opening approach — general to the angle itself, not tied to \
any one channel (channel-specific format/structure rules are applied separately, later, once a \
channel is chosen)
- answers: (AA-512) a list of the questions from "Travelers also ask" below that THIS SPECIFIC \
angle would genuinely answer if written — quoted EXACTLY as given, word for word. Claim only \
what the angle really covers: an angle answering 2 questions well beats one listing 6 it barely \
touches. Empty list if none of the given questions fit this angle, or if no questions were given.

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
    {"name": "...", "why_it_works": "...", "formula_fit": "...", "best_final_style": "...", "answers": []},
    {"name": "...", "why_it_works": "...", "formula_fit": "...", "best_final_style": "...", "answers": []},
    {"name": "...", "why_it_works": "...", "formula_fit": "...", "best_final_style": "...", "answers": []}
  ],
  "recommended_index": 0,
  "recommendation_reason": "short reason this one is the strongest of the 3"
}
recommended_index must be 0, 1, or 2. NOTE: when a channel is already known for this request \
(most requests today, via the Slate — see services/acp_angle_gate/service.py), the caller \
RE-RANKS the 3 angles itself by measurable criteria (real PAA-answer count, checked against your \
"answers" claims, and channel avoid-list violations) and may override recommended_index — your \
own recommendation is only the fallback for the rare request where no channel is known yet."""


def build_user_prompt(
    *, content_seed: str, goal: Goal, brand_audience: BrandAudience,
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
        f"BRAND AUDIENCE (fixed, from this tenant's brand identity — write angles that would "
        f"genuinely appeal to THIS audience, not a generic traveller):\n"
        f"Customer segment: {segment}\n"
        f"Customer mindset: {mindset}"
    )
    # AA-469 Việc 4 — optional 5th block (was 6th, back when CHANNEL was still a block here — see
    # this module's own header comment on the flow-order fix that removed it). Omitted entirely
    # (not "SEARCH DEMAND: none") when there's no seo_context row for this tour, or when the row
    # has neither PAA questions nor related keywords — an empty/absent block would just be prompt
    # noise, and the prompt stays byte-identical for every request with no real signal to add.
    if search_demand and (search_demand.people_also_ask or search_demand.related_keywords):
        lines = [f"SEARCH DEMAND SIGNAL (real traveler search behavior for this destination — "
                 f"see system prompt for how to use this):\nRelevance: {search_demand.relevance}"]
        if search_demand.people_also_ask:
            # AA-512 — the FULL pool, not capped at 5 like before: an angle's "answers" claim is
            # now server-verified against exactly this list (services/acp_angle_gate/ranking.py),
            # so truncating it here would make a real answered question unmatchable.
            lines.append("Travelers also ask: " + "; ".join(search_demand.people_also_ask))
        if search_demand.related_keywords:
            lines.append("Related search terms: " + ", ".join(search_demand.related_keywords[:8]))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


__all__ = ["SYSTEM_PROMPT", "build_user_prompt"]
