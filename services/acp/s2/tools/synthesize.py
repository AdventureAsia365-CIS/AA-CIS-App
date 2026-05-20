"""
Synthesis node. Always runs last.
Calls Bedrock claude-sonnet-4-5 to build a visibility_report JSONB.
Writes report to acp_silver_s2.visibility_reports.
Updates acp_shared.acp_runs status to 'completed'.
"""
import json
import os
import structlog

import boto3

logger = structlog.get_logger()

_MODEL_ID = "us.anthropic.claude-sonnet-4-5"
_AWS_REGION = os.environ.get("AWS_REGION", "us-west-1")


def make_synthesize_node(pool, s3_client):
    _bedrock = boto3.client("bedrock-runtime", region_name=_AWS_REGION)

    async def synthesize(state: dict) -> dict:
        run_id = state["run_id"]
        country = state["country"]
        tenant_id = state["tenant_id"]
        kw_count = state.get("keyword_count", 0)
        intent_pct = state.get("informational_intent_pct") or 0.0
        existing_risk = state.get("existing_content_risk", False)
        completed_tools = list(state.get("completed_tools", []))

        prompt = (
            f"You are a travel content strategist. Analyze SEO visibility data for '{country}' tours.\n\n"
            f"Research summary:\n"
            f"- Keywords analyzed: {kw_count}\n"
            f"- Informational intent: {intent_pct:.1f}%\n"
            f"- Existing content risk: {existing_risk}\n"
            f"- Data sources collected: {', '.join(completed_tools)}\n\n"
            "Return a JSON object with exactly these keys:\n"
            "  summary: string (2-3 sentence strategic overview)\n"
            "  top_opportunities: array of 3-5 keyword opportunity strings\n"
            "  content_gaps: array of 2-3 identified content gap strings\n"
            "  recommended_actions: array of 3 next-step action strings\n"
            "  risk_flags: array of risk strings (empty array if none)\n"
            "  confidence_score: float 0-100\n\n"
            "Respond with only valid JSON. No markdown, no explanation."
        )

        visibility_report = {}
        confidence_score = 0.0
        try:
            response = _bedrock.invoke_model(
                modelId=_MODEL_ID,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )
            raw = json.loads(response["body"].read())
            visibility_report = json.loads(raw["content"][0]["text"])
            confidence_score = float(visibility_report.get("confidence_score", 70.0))
        except Exception as exc:
            logger.error("synthesize_bedrock_error", run_id=run_id, error=str(exc))
            visibility_report = {"error": str(exc), "summary": "Synthesis failed — Bedrock error"}

        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO acp_silver_s2.visibility_reports
                    (run_id, tenant_id, country, visibility_report, confidence_score,
                     keyword_count, existing_content_risk,
                     keywords_s3_key, competitors_s3_key, trends_s3_key,
                     reddit_s3_key, gsc_s3_key, fetched_at)
                VALUES ($1::uuid, $2::uuid, $3, $4::jsonb, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
                ON CONFLICT (run_id) DO UPDATE
                    SET visibility_report     = EXCLUDED.visibility_report,
                        confidence_score      = EXCLUDED.confidence_score,
                        keyword_count         = EXCLUDED.keyword_count,
                        existing_content_risk = EXCLUDED.existing_content_risk,
                        fetched_at            = NOW()
            """,
                run_id, tenant_id, country,
                json.dumps(visibility_report), confidence_score, kw_count, existing_risk,
                state.get("keywords_s3_key"),
                state.get("competitors_s3_key"),
                state.get("trends_s3_key"),
                state.get("reddit_s3_key"),
                state.get("gsc_s3_key"),
            )

        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE acp_shared.acp_runs
                SET status = 'completed', completed_at = NOW()
                WHERE run_id = $1::uuid
            """, run_id)

        completed_tools.append("synthesize")
        logger.info("synthesize_complete", run_id=run_id, confidence_score=confidence_score)
        return {"confidence_score": confidence_score, "completed_tools": completed_tools}

    return synthesize
