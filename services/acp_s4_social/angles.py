"""Angle generator for S4.2 Social Media Content Engine (AA-93).

Ports Ms. Thư's generate_angles() logic from content_agent.py.
Auto mode returns 1 angle (strongest). Guided mode returns all 3.
"""
from __future__ import annotations

import json
import re

from services.acp_s4_social.brief import ContentBrief


_ANGLE_SYSTEM = """You are a senior content strategist specialising in travel and luxury experiences.

Given a content brief, generate 3 distinct angles to approach the content.
Each angle must be strategically different — not just variations of the same idea.

Return ONLY valid JSON array (no preamble):
[
  {
    "name": "<short angle name>",
    "why_it_works": "<1-2 sentence explanation of psychological/strategic reason>",
    "length_signal": "<e.g. 150 words, 3 paragraphs, 5 bullet points>",
    "style_signal": "<e.g. conversational, expert authority, narrative story>"
  },
  ...
]"""


def _angles_prompt(brief: ContentBrief) -> str:
    include_text = "\n- ".join(brief.must_include) if brief.must_include else "None"
    avoid_text = "\n- ".join(brief.must_avoid) if brief.must_avoid else "None"
    return f"""Content Brief:
Brand: {brief.brand}
Audience: {brief.audience}
Channel: {brief.channel}
Goal: {brief.goal}
Topic: {brief.topic}
Tone: {brief.tone}
CTA: {brief.cta}
Destination: {brief.destination or 'N/A'}
Tour: {brief.tour_name or 'N/A'}
Must include:
- {include_text}
Must avoid:
- {avoid_text}

Generate 3 distinct content angles for this brief."""


def generate_angles(brief: ContentBrief, llm_client, mode: str = "auto") -> list[dict]:
    """
    Generate content angles via LLM.

    Args:
        brief:      ContentBrief with all anchors filled
        llm_client: callable(system, user) → str  (injected by handler)
        mode:       'auto' returns [best_angle], 'guided' returns all 3

    Returns:
        list[dict] with keys: name, why_it_works, length_signal, style_signal
    """
    prompt = _angles_prompt(brief)
    raw = llm_client(_ANGLE_SYSTEM, prompt)

    # Strip markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Extract JSON array
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        raw = match.group(0)

    try:
        angles: list[dict] = json.loads(raw)
        if not isinstance(angles, list):
            angles = []
    except (json.JSONDecodeError, ValueError):
        angles = [
            {
                "name": "Direct approach",
                "why_it_works": "Addresses the audience pain point directly with clear value proposition.",
                "length_signal": "200 words",
                "style_signal": "conversational",
            }
        ]

    # Ensure at least 1 angle
    if not angles:
        angles = [{"name": "Direct approach", "why_it_works": "Fallback angle.",
                   "length_signal": "200 words", "style_signal": "conversational"}]

    # Auto mode: return best angle only (first is ranked strongest by LLM)
    if mode == "auto":
        return angles[:1]

    return angles[:3]
