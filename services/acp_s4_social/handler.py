"""
AA-93 S4.2 Social Media Content Engine — orchestration handler.

Two modes from Ms. Thư's content_agent.py:
  AUTO:   brief → best_angle → write → quality → save → social_id
  GUIDED: Step 1: brief → 3 angles (return to user for selection)
          Step 2: brief + selected_angle → write → quality → save → social_id
"""
from __future__ import annotations

import json
import logging

import asyncpg

from services.acp_s4_social.angles import generate_angles
from services.acp_s4_social.brief import ContentBrief
from services.acp_s4_social.dedup import check_cross_platform_dedup
from services.acp_s4_social.formula import (
    get_formula_name,
    get_goal_primary_formula,
    load_formula_file,
    load_goal_references,
)
from services.acp_s4_social.output import save_to_db
from services.acp_s4_social.quality import quality_pass
from services.acp_s4_social.writer import write_content
from services.acp_shared.quality_evaluator import QUALITY_PASS_THRESHOLD, evaluate_quality
from services.acp_shared.stage_checkpoint import checkpoint_complete, checkpoint_failed
from services.acp_shared.strategy_validator import validate_strategy

logger = logging.getLogger(__name__)


def _load_formula(brief: ContentBrief) -> tuple[str, str]:
    """Return (formula_name, formula_text) using goal_key if present, else channel+goal."""
    if brief.goal_key:
        formula_name = get_goal_primary_formula(brief.goal_key)
        formula_text = load_goal_references(brief.goal_key)
    else:
        formula_name = get_formula_name(brief.channel, brief.goal)
        formula_text = load_formula_file(formula_name)
    return formula_name, formula_text


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
    run_id = meta.get("run_id")
    tour_id = meta.get("tour_id")

    # Validate strategy if provided
    strategy_notes = meta.get("strategy_notes")
    if strategy_notes is not None:
        validation = validate_strategy(strategy_notes, tour_id=str(tour_id or ""))
        if not validation.is_valid:
            logger.warning(
                "strategy_validation_failed in run_auto",
                missing=validation.missing_fields,
                empty=validation.empty_fields,
            )

    try:
        # Step 1: Select formula (v2: goal_key → selective refs; v1: channel+goal)
        formula_name, formula_text = _load_formula(brief)

        # Step 2: Generate 3 angles (store all; use first as best)
        all_angles = generate_angles(brief, llm_client, mode="guided")
        best_angle = all_angles[0] if all_angles else {
            "name": "Direct", "why_it_works": "",
            "length_signal": "200 words", "style_signal": "conversational",
        }
        angles_json = {
            "angle_1": all_angles[0] if len(all_angles) > 0 else None,
            "angle_2": all_angles[1] if len(all_angles) > 1 else None,
            "angle_3": all_angles[2] if len(all_angles) > 2 else None,
            "selected_index": 1,
        }

        # Step 3: Write content
        content = write_content(brief, best_angle, formula_text, llm_client)

        # Step 4: Legacy quality pass (revision)
        quality = quality_pass(content, brief, llm_client)
        final_content = quality.get("revised_content", content)
        warnings = list(quality.get("warnings", []))

        # Step 5: Evaluator quality score (best-effort)
        quality_passed = False
        try:
            quality_score = evaluate_quality(final_content, brief.channel, llm_client)
            quality_passed = quality_score.passed
            if not quality_score.passed:
                msg = (
                    f"quality_eval_failed: avg={quality_score.average:.2f}"
                    f" < {QUALITY_PASS_THRESHOLD}"
                )
                warnings.append(msg)
        except Exception as qe:
            logger.warning("evaluate_quality error (non-fatal): %s", qe)

        # Step 6: Cross-platform dedup check (best-effort, only if multi-platform result)
        tiktok_text = meta.get("tiktok_text", "")
        fb_post_text = meta.get("fb_post_text", "")
        fb_ad_text = meta.get("fb_ad_text", "")
        if any([tiktok_text, fb_post_text, fb_ad_text]):
            dedup_flags = check_cross_platform_dedup(
                tiktok_text or final_content,
                fb_post_text or final_content,
                fb_ad_text or final_content,
            )
            warnings.extend(dedup_flags)

        # Step 7: Save to DB
        save_meta = {
            **meta,
            "angle_name": best_angle.get("name"),
            "formula_used": formula_name,
            "mode": "auto",
            "warnings": warnings,
            "angles_json": json.dumps(angles_json),
            "quality_score": quality_passed,
        }
        social_id = await save_to_db(final_content, brief, save_meta, db)

        # Step 8: Checkpoint complete (best-effort)
        if run_id and tour_id:
            try:
                await checkpoint_complete(db, str(run_id), "social_tour", str(tour_id))
            except Exception:
                pass

        return {
            "social_id": social_id,
            "channel": brief.channel,
            "formula_used": formula_name,
            "content_preview": final_content[:200],
            "warnings": warnings,
            "status": "done",
        }

    except Exception as e:
        if run_id and tour_id:
            try:
                await checkpoint_failed(db, str(run_id), "social_tour", str(tour_id), str(e))
            except Exception:
                pass
        raise


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
    run_id = meta.get("run_id")
    tour_id = meta.get("tour_id")

    # Validate strategy if provided
    strategy_notes = meta.get("strategy_notes")
    if strategy_notes is not None:
        validation = validate_strategy(strategy_notes, tour_id=str(tour_id or ""))
        if not validation.is_valid:
            logger.warning(
                "strategy_validation_failed in run_guided_write",
                missing=validation.missing_fields,
                empty=validation.empty_fields,
            )

    formula_name, formula_text = _load_formula(brief)
    content = write_content(brief, selected_angle, formula_text, llm_client)
    quality = quality_pass(content, brief, llm_client)
    final_content = quality.get("revised_content", content)
    warnings = list(quality.get("warnings", []))

    # Evaluator quality score (best-effort)
    quality_passed = False
    try:
        quality_score = evaluate_quality(final_content, brief.channel, llm_client)
        quality_passed = quality_score.passed
        if not quality_score.passed:
            msg = (
                f"quality_eval_failed: avg={quality_score.average:.2f}"
                f" < {QUALITY_PASS_THRESHOLD}"
            )
            warnings.append(msg)
    except Exception as qe:
        logger.warning("evaluate_quality error (non-fatal): %s", qe)

    save_meta = {
        **meta,
        "angle_name": selected_angle.get("name"),
        "formula_used": formula_name,
        "mode": "guided",
        "warnings": warnings,
        "quality_score": quality_passed,
    }
    social_id = await save_to_db(final_content, brief, save_meta, db)

    # Checkpoint complete (best-effort)
    if run_id and tour_id:
        try:
            await checkpoint_complete(db, str(run_id), "social_tour", str(tour_id))
        except Exception:
            pass

    return {
        "social_id": social_id,
        "channel": brief.channel,
        "formula_used": formula_name,
        "content_preview": final_content[:200],
        "warnings": warnings,
        "status": "done",
    }
