"""
services.acp_content_writing.prompts — T9 write-step (SKILL_v2.md workflow step 9) prompt
construction. Referenced (not reused, ADR §0.5) against services/acp_s4_social/writer.py's
ContentBrief-assembly shape — written fresh here against T8's real inputs (angle_gate_request/
angle_gate_option, channel_style.py, goals.py, brand_audience.py), not the old ContentBrief.

No hardcoded per-channel word-count numbers (STEP0 §Open Question #3 / build task's own explicit
instruction — neither SKILL_v2.md's own Channel Rules nor T8's real Bảng-2 source,
channel_style.py, states one) — length guidance is qualitative, from channel_style.py's
`structure`/`style` fields, same as the LLM already gets for angle generation (generate.py).

AA-452: `channel_style.py`'s own `blog` entry describes an N7-shaped structure ("Hook→context→
structured H2 sections→FAQ (if TOFU)→CTA") that this module never actually asked the model to
produce in markup terms until now — investigation confirmed T9's blog channel genuinely can
carry N7's F3 (structural variance)/F5 (atom density)/F7 (FAQ dedup) gates, not just F1/F2/F4/F6/
F8/F9. `_BLOG_FORMAT_INSTRUCTIONS` below is appended ONLY when `channel_style['channel'] ==
'blog'` — the other 7 channels' prompts are byte-for-byte unchanged. Two requirements, both new
markup the writer wasn't asked for before:
  1. Real markdown `## ` H2 headers per section (+ `## FAQ` with `**Q: ...**`/`A: ...` pairs if
     the piece includes one) — so `quality_gates.gate_structural_variance()`/`gate_faq_dedup()`
     (ported from `acp_produce/gates.py`, same regexes) have real structure to check.
  2. A `[R:{atom_id}]` tag after every sentence built from a seed fact — same tag shape N7 uses,
     but T9 has exactly one atom per piece so there's only ever one id (no closed-world check
     needed, same simplification `gate_grounding()` already made in AA-450). This is INTERNAL
     provenance markup only, for `gate_atom_density()`/`gate_grounding()` to see — it is never
     shown to the tenant: `quality_gates.strip_citation_tags()` removes every tag from
     `content_text` (and from every gate_ledger/repair_log violation string) before
     `service.write_and_check()` ever persists or returns a piece, for every channel, blog
     included. Non-blog channels never receive this instruction, so they never produce a tag to
     strip in the first place — `strip_citation_tags()` runs on their output too (a deliberate,
     no-cost safety net, not dead code — see that function's own docstring).
"""
from __future__ import annotations

from services.acp_angle_gate.brand_audience import BrandAudience
from services.acp_angle_gate.channel_style import ChannelStyle
from services.acp_angle_gate.goals import Goal

_BLOG_FORMAT_INSTRUCTIONS = """

BLOG-SPECIFIC FORMAT REQUIREMENTS (this channel only — required markup, not a style suggestion):
- Structure the body with real markdown H2 headers: a line starting with exactly "## " for every
  major section (e.g. "## Why Southern Laos"). Do not skip this.
- If, and only if, the piece includes a FAQ section, put it LAST, headed by a line that is
  exactly "## FAQ", followed by one or more Q/A pairs in this exact format and nothing else:
  **Q: <question>**
  A: <answer>
- Immediately after every sentence that uses a specific fact, number, or detail drawn from the
  content seed, append the tag [R:{atom_id}] (this literal id, no spaces inside the brackets). A
  sentence with no such detail needs no tag. This tag is internal provenance markup that will be
  removed before the reader ever sees this piece — write the surrounding sentence exactly as if
  the tag weren't there; it must never change your wording or read as part of the sentence."""

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
    revision_feedback: list[str] | None = None, atom_id: str | None = None,
) -> str:
    """`angle` is the chosen `angle_gate_option` row (name/why_it_works/formula_fit/
    best_final_style). `revision_feedback` (AA-450 Phase 1's confirmed retry shape — specific,
    per-gate violation strings, not a generic "try again") is appended only on attempt 2.

    `atom_id` (AA-452, keyword-only, defaults to `None` so every pre-AA-452 caller/test is
    unaffected): only used when `channel_style['channel'] == 'blog'`, to fill in
    `_BLOG_FORMAT_INSTRUCTIONS`' citation tag. `None`/empty falls back to the literal id "atom"
    rather than emitting a malformed `[R:]` tag — real callers (service.py) always have the
    real atom_id, this fallback only guards a caller that forgets to pass one."""
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
    prompt = "\n".join(lines)
    if channel_style["channel"] == "blog":
        prompt += _BLOG_FORMAT_INSTRUCTIONS.format(atom_id=atom_id or "atom")
    return prompt


__all__ = ["SYSTEM_PROMPT", "build_user_prompt"]
