"""Quality Editor Pass for S4.2 Social Media Content Engine v2 (AA-145-C).

Active editor pass — LLM revises content against 10-point checklist.
Returns revised_content (str), warnings (str), passed (bool).
"""
from __future__ import annotations

import json
import re

import structlog

from services.acp_s4_social.brief import ContentBrief

QUALITY_EDITOR_SYSTEM = """You are a social media content editor for premium travel brands.
Run the quality checklist below as an internal editor.
Revise fixable issues directly. Do NOT show the checklist.
Return ONLY valid JSON with this exact shape:
{"revised_content": "the revised final content",
 "warnings": "unresolved proof or safety issues only; empty string if none",
 "passed": true}

Quality checklist (apply internally):
1. Is the first line strong?
2. Is the message specific (concrete details, not vague)?
3. Is the audience clear?
4. Is the CTA obvious and actionable?
5. Does it sound human (not corporate AI)?
6. Does it avoid generic AI-style writing?
7. Does it match the requested tone and brand?
8. Is proof or credibility handled honestly?
9. Is the content suitable for the selected channel?
10. Does the final content reflect the selected goal?

Banned phrases to fix if found: "In today's fast-paced world", "game-changing", "revolutionary",
"unlock your potential", "take your X to the next level", "leverage", "synergize",
fake urgency, vague benefit stacks like "save time boost productivity drive growth"
"""


def quality_pass(content: str, brief: ContentBrief, llm_client) -> dict:
    user_prompt = f"""Channel: {brief.channel}
Goal: {brief.goal_name or brief.goal}
Brand: {brief.brand}
Audience: {brief.audience}
CTA: {brief.cta}

Draft content to review and revise:
{content}"""

    try:
        raw = llm_client(QUALITY_EDITOR_SYSTEM, user_prompt)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON in quality pass response: {raw[:200]}")
        data = json.loads(json_match.group())
        return {
            "revised_content": str(data.get("revised_content", content)).strip(),
            "warnings": str(data.get("warnings", "")).strip(),
            "passed": bool(data.get("passed", True)),
        }
    except Exception as e:
        structlog.get_logger().warning("quality_pass_failed", error=str(e))
        return {"revised_content": content, "warnings": str(e), "passed": False}
