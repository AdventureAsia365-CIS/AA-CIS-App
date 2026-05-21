"""
AA-93 S4.2 Social Media Content Engine — orchestration handler.

Two modes from Ms. Thư's content_agent.py:
  AUTO:   brief → best_angle → write → quality → save → social_id
  GUIDED: Step 1: brief → 3 angles (return to user for selection)
          Step 2: brief + selected_angle → write → quality → save → social_id
"""
from __future__ import annotations

import asyncpg

from services.acp_s4_social.angles import generate_angles
from services.acp_s4_social.brief import ContentBrief
from services.acp_s4_social.formula import get_formula_name, load_formula_file
from services.acp_s4_social.output import save_to_db
from services.acp_s4_social.quality import quality_pass
from services.acp_s4_social.writer import write_content


async def run_auto(
    brief: ContentBrief,
    meta: dict,
    db: asyncpg.Connection,
    llm_client,
) -> dict:
    """
    Auto mode: select best angle automatically, write, quality-check, save.

    Returns:
        {social_id, channel, content_preview, formula_used, warnings}
    """
    # Step 1: Select formula
    formula_name = get_formula_name(brief.channel, brief.goal)
    formula_text = load_formula_file(formula_name)

    # Step 2: Generate best angle (auto = return 1)
    angles = generate_angles(brief, llm_client, mode="auto")
    best_angle = angles[0] if angles else {"name": "Direct", "why_it_works": "",
                                           "length_signal": "200 words", "style_signal": "conversational"}

    # Step 3: Write content
    content = write_content(brief, best_angle, formula_text, llm_client)

    # Step 4: Quality pass
    quality = quality_pass(content, brief, llm_client)
    final_content = quality.get("revised_content", content)
    warnings = quality.get("warnings", [])

    # Step 5: Save to DB
    save_meta = {
        **meta,
        "angle_name": best_angle.get("name"),
        "formula_used": formula_name,
        "mode": "auto",
        "warnings": warnings,
    }
    social_id = await save_to_db(final_content, brief, save_meta, db)

    return {
        "social_id": social_id,
        "channel": brief.channel,
        "formula_used": formula_name,
        "content_preview": final_content[:200],
        "warnings": warnings,
        "status": "done",
    }


def run_guided_angles(brief: ContentBrief, llm_client) -> list[dict]:
    """
    Guided mode step 1: generate 3 angles for human selection.

    Returns:
        list[dict] with keys: name, why_it_works, length_signal, style_signal
    """
    return generate_angles(brief, llm_client, mode="guided")


async def run_guided_write(
    brief: ContentBrief,
    selected_angle: dict,
    meta: dict,
    db: asyncpg.Connection,
    llm_client,
) -> dict:
    """
    Guided mode step 2: write with selected angle, quality-check, save.

    Returns:
        {social_id, channel, content_preview, formula_used, warnings}
    """
    formula_name = get_formula_name(brief.channel, brief.goal)
    formula_text = load_formula_file(formula_name)
    content = write_content(brief, selected_angle, formula_text, llm_client)
    quality = quality_pass(content, brief, llm_client)
    final_content = quality.get("revised_content", content)
    warnings = quality.get("warnings", [])

    save_meta = {
        **meta,
        "angle_name": selected_angle.get("name"),
        "formula_used": formula_name,
        "mode": "guided",
        "warnings": warnings,
    }
    social_id = await save_to_db(final_content, brief, save_meta, db)

    return {
        "social_id": social_id,
        "channel": brief.channel,
        "formula_used": formula_name,
        "content_preview": final_content[:200],
        "warnings": warnings,
        "status": "done",
    }
