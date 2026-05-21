"""Quality gate for S4.2 Social Media Content Engine (AA-93).

Ports Ms. Thư's quality_editor_pass() from content_agent.py.
9-criterion check from SKILL.md. Returns revised content + warnings.
"""
from __future__ import annotations

import re

from services.acp_s4_social.brief import ContentBrief

# Forbidden generic phrases (from SKILL.md + content_agent.py)
FORBIDDEN_PHRASES = [
    "in today's fast-paced world",
    "game-changing",
    "revolutionary",
    "unlock your potential",
    "take your",
    "to the next level",
    "dive into",
    "leverage",
    "synergy",
    "cutting-edge",
    "best-in-class",
    "world-class",
    "paradigm shift",
    "seamless experience",
    "at the end of the day",
    "it goes without saying",
]

_QUALITY_SYSTEM = """You are a content quality editor specialising in travel marketing.

Review the content against these 9 criteria:
1. Strong, specific opening (not generic)
2. Clear, specific message (not vague)
3. Audience fit (right language for them)
4. Obvious, actionable CTA
5. Sounds human (not AI-generated sludge)
6. No generic AI phrases ("game-changing", "revolutionary", "unlock your potential")
7. Matches requested tone
8. Honest proof (no fabricated claims or fake urgency)
9. Fits the channel format

Revise any failing sections. Return ONLY valid JSON:
{
  "revised_content": "<full revised content>",
  "warnings": ["<issue 1 if any>", ...],
  "passed": true/false
}"""


def quality_pass(content: str, brief: ContentBrief, llm_client) -> dict:
    """
    Run quality check on content. Detects forbidden phrases locally first,
    then uses LLM for deeper quality assessment.

    Returns:
        dict with: revised_content (str), warnings (list[str]), passed (bool)
    """
    # Fast local check for forbidden phrases
    local_warnings: list[str] = []
    lowered = content.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in lowered:
            local_warnings.append(f"Forbidden phrase detected: '{phrase}'")

    prompt = f"""Content to review:

Channel: {brief.channel}
Tone: {brief.tone}
Goal: {brief.goal}
Audience: {brief.audience}

Content:
---
{content}
---

Additional local flags: {local_warnings if local_warnings else 'None'}

Review against all 9 criteria. Revise if needed. Return JSON."""

    import json
    import re as _re

    raw = llm_client(_QUALITY_SYSTEM, prompt)

    # Strip markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Extract JSON object
    match = _re.search(r"\{.*\}", raw, _re.DOTALL)
    if match:
        raw = match.group(0)

    try:
        result = json.loads(raw)
        result["warnings"] = result.get("warnings", []) + local_warnings
        result["passed"] = len(result.get("warnings", [])) == 0
        return result
    except (json.JSONDecodeError, ValueError):
        return {
            "revised_content": content,
            "warnings": local_warnings or ["Quality check parse failed — manual review required"],
            "passed": len(local_warnings) == 0,
        }
