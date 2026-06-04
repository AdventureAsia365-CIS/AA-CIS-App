"""Content writer for S4.2 Social Media Content Engine (AA-93).

Ports Ms. Thư's write_final_content() from content_agent.py.
Applies channel-specific rules from SKILL.md.
"""
from __future__ import annotations

from services.acp_s4_social.brief import ContentBrief
from services.acp_s4_social.formula import load_goal_references, load_skill

# Channel-specific word count + style rules (from SKILL.md)
_CHANNEL_RULES: dict[str, str] = {
    "facebook": (
        "150-300 words. Conversational and direct. Short paragraphs (2-3 lines). "
        "2-3 emojis maximum. End with a clear CTA question or link. "
        "No corporate jargon. Strong first line is essential."
    ),
    "linkedin": (
        "200-400 words. Professional and insight-led. No emojis. "
        "Hook on first line (no 'I am thrilled to announce'). "
        "Include one specific data point or observation. "
        "End with a genuine question or soft CTA."
    ),
    "tiktok": (
        "80-150 words. Hook must be in the very first sentence — scroll-stopping. "
        "Fast-moving, energetic language. Short punchy sentences. "
        "Include 5-10 relevant hashtags in a separate section. "
        "Conversational, not corporate."
    ),
    "instagram": (
        "100-200 words. Visual-forward — describe what the reader sees or imagines. "
        "Skimmable with line breaks. "
        "Include 5-15 hashtags in a separate section at the end. "
        "End with a CTA to link in bio or comment."
    ),
    "email": (
        "Subject line (max 50 chars) + body (200-400 words). "
        "Personalised opener using 'you'. One clear idea per email. "
        "CTA button text: action-oriented verb phrase. "
        "Warm, human tone — not a broadcast."
    ),
    "newsletter": (
        "400-600 words. Editorial angle — teach something specific. "
        "Use subheadings for scannability. Include a 'key takeaway' or 'what to do next'. "
        "Calm, expert voice. End with soft CTA to deeper resource."
    ),
    "landing_page": (
        "Headline (8-12 words) + subheadline (1 sentence) + body (300-500 words) + CTA block. "
        "Structured sections with H2 headings. "
        "Proof element required (testimonial, stat, or case detail). "
        "Single clear CTA — no navigation away from page."
    ),
    "ads": (
        "Headline: 25-40 words, pattern-interrupt opening. "
        "Body: 90-125 words, proof + desire + urgency. "
        "CTA: strong action verb + benefit. "
        "Multiple variants: write Primary + 2 variants with different hooks."
    ),
}


SKILL_V2_SYSTEM = """You are a strategy-led English content writer for premium travel brands.
Write using the selected goal's internal writing method. Do not label formulas.
Follow channel rules. Use concrete details, not generic language.
Return only the final content — no explanation, no checklist, no formula labels."""


def _writer_system() -> str:
    skill = load_skill()
    skill_excerpt = skill[:2000] if skill else (
        "Write calm, credible, experience-led content "
        "for discerning travellers (40-60, US/UK/AU professionals)."
    )
    return f"""You are Adventure Asia's senior content writer specialising in travel marketing.

{skill_excerpt}

Brand voice: calm, assured, specific, well-travelled. NOT salesy, generic, or hype-driven.
Never use: "trip of a lifetime", "game-changing", "revolutionary", "unlock your potential".
Always anchor to real details: named places, distances, durations, honest caveats.

Return ONLY the final content — no explanation, no preamble, no markdown code fences."""


def write_content(
    brief: ContentBrief,
    angle: dict,
    formula_text: str,
    llm_client,
) -> str:
    """
    Write final content using the selected angle and formula.

    Args:
        brief:        ContentBrief
        angle:        Selected angle dict (name, why_it_works, length_signal, style_signal)
        formula_text: Loaded formula markdown from references/
        llm_client:   callable(system, user) → str

    Returns:
        str: Final written content
    """
    include_text = "\n- ".join(brief.must_include) if brief.must_include else "None"
    avoid_text = "\n- ".join(brief.must_avoid) if brief.must_avoid else "None"

    brief_section = (
        f"Brand: {brief.brand}\n"
        f"Audience: {brief.audience}\n"
        f"Channel: {brief.channel}\n"
        f"Goal: {brief.goal_name or brief.goal}\n"
        f"Topic: {brief.topic}\n"
        f"Tone: {brief.tone}\n"
        f"CTA: {brief.cta}\n"
        f"Destination: {brief.destination or 'N/A'}\n"
        f"Tour: {brief.tour_name or 'N/A'}\n"
        f"Must include:\n- {include_text}\n"
        f"Must avoid:\n- {avoid_text}"
    )
    angle_section = f"{angle.get('name', 'Direct')}\n{angle.get('why_it_works', '')}"

    if brief.goal_key:
        system = SKILL_V2_SYSTEM
        context = load_goal_references(brief.goal_key)
    else:
        channel_rules = _CHANNEL_RULES.get(brief.channel, "Follow platform best practices.")
        system = _writer_system()
        formula_fallback = "Use AIDA structure: Attention → Interest → Desire → Action"
        formula_content = formula_text[:1500] if formula_text else formula_fallback
        context = (
            f"CHANNEL RULES FOR {brief.channel.upper()}:\n{channel_rules}\n\n"
            f"COPYWRITING FORMULA:\n{formula_content}"
        )

    user_prompt = (
        f"{brief_section}\n\n"
        f"## References\n\n{context}\n\n"
        f"## Selected angle\n\n{angle_section}"
    )
    return llm_client(system, user_prompt)
