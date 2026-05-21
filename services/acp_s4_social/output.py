"""DB persistence for S4.2 Social Media Content Engine (AA-93).

Maps channel → correct JSONB column in acp_silver_s4.social_content.
Channel mapping (from social_generation_workflow.md):
  facebook   → facebook_post = {content: str}
  tiktok     → tiktok = {content: str, hashtags: []}
  ads        → facebook_ad = {body: str, headline: str}
  others     → strategy_notes = {content: str, channel: str}
"""
from __future__ import annotations

import json
import re
import uuid

import asyncpg

from services.acp_s4_social.brief import ContentBrief


def _extract_hashtags(content: str) -> list[str]:
    return re.findall(r"#\w+", content)


def _build_jsonb_columns(channel: str, content: str) -> dict:
    """Map channel to correct JSONB column payload."""
    if channel == "facebook":
        return {
            "tiktok": None,
            "facebook_post": json.dumps({"content": content}),
            "facebook_ad": None,
            "strategy_notes": None,
        }
    elif channel == "tiktok":
        hashtags = _extract_hashtags(content)
        body = re.sub(r"\s*#\w+", "", content).strip()
        return {
            "tiktok": json.dumps({"content": body, "hashtags": hashtags}),
            "facebook_post": None,
            "facebook_ad": None,
            "strategy_notes": None,
        }
    elif channel == "ads":
        lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
        headline = lines[0] if lines else content[:60]
        body = "\n".join(lines[1:]) if len(lines) > 1 else content
        return {
            "tiktok": None,
            "facebook_post": None,
            "facebook_ad": json.dumps({"headline": headline, "body": body}),
            "strategy_notes": None,
        }
    else:
        # linkedin, instagram, email, newsletter, landing_page → strategy_notes
        return {
            "tiktok": None,
            "facebook_post": None,
            "facebook_ad": None,
            "strategy_notes": json.dumps({"content": content, "channel": channel}),
        }


async def save_to_db(
    content: str,
    brief: ContentBrief,
    meta: dict,
    db: asyncpg.Connection,
) -> str:
    """
    INSERT into acp_silver_s4.social_content.

    Args:
        content:  Final content string
        brief:    ContentBrief
        meta:     {run_id, tenant_id, tour_id, tour_name, angle_name,
                   formula_used, mode, llm_provider, model_id, warnings}
        db:       asyncpg connection

    Returns:
        social_id (str UUID)
    """
    jsonb_cols = _build_jsonb_columns(brief.channel, content)
    warnings_text = "; ".join(meta.get("warnings") or []) or None

    run_id = meta.get("run_id") or str(uuid.uuid4())
    tour_id = meta.get("tour_id") or str(uuid.uuid4())

    row = await db.fetchrow(
        """INSERT INTO acp_silver_s4.social_content
           (run_id, tenant_id, tour_id, tour_name,
            tiktok, facebook_post, facebook_ad, strategy_notes,
            channel, content_brief, selected_angle, formula_used,
            mode, quality_warnings, llm_provider, model_id,
            validation_status)
         VALUES
           ($1::uuid, $2, $3::uuid, $4,
            $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb,
            $9, $10::jsonb, $11, $12,
            $13, $14, $15, $16,
            $17)
         RETURNING social_id::text""",
        run_id,
        meta.get("tenant_id", "aa_internal"),
        tour_id,
        meta.get("tour_name"),
        jsonb_cols["tiktok"],
        jsonb_cols["facebook_post"],
        jsonb_cols["facebook_ad"],
        jsonb_cols["strategy_notes"],
        brief.channel,
        json.dumps(brief.to_dict()),
        meta.get("angle_name"),
        meta.get("formula_used"),
        meta.get("mode", "auto"),
        warnings_text,
        meta.get("llm_provider", "bedrock"),
        meta.get("model_id"),
        "passed" if not meta.get("warnings") else "flagged_human",
    )
    return row["social_id"]
