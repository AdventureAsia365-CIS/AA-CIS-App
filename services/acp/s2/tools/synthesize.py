"""
Synthesis node. Always runs last.
Calls Bedrock claude-sonnet-4-5 to build visibility analysis.
Writes to acp_silver_s2.visibility_reports using the actual table schema:
  keyword_gaps, competitor_data, google_trends, reddit_insights, gsc_data,
  top_opportunities, confidence_score (new), primary_keywords (new), fetched_at (new).
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

        llm_output = {}
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
            llm_output = json.loads(raw["content"][0]["text"])
            confidence_score = float(llm_output.get("confidence_score", 70.0))
        except Exception as exc:
            logger.error("synthesize_bedrock_error", run_id=run_id, error=str(exc))
            llm_output = {
                "top_opportunities": [],
                "content_gaps": [],
                "summary": f"Synthesis failed: {exc}",
            }

        # Map LLM output + state S3 keys to actual visibility_reports column names
        top_opportunities = llm_output.get("top_opportunities") or []
        keyword_gaps = llm_output.get("content_gaps") or []
        # Use top 3 opportunities as primary keywords
        primary_keywords = top_opportunities[:3]

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO acp_silver_s2.visibility_reports
                    (run_id, tenant_id, country,
                     keyword_gaps, top_opportunities, competitor_data,
                     google_trends, reddit_insights, gsc_data,
                     confidence_score, primary_keywords, fetched_at)
                VALUES
                    ($1::uuid, $2::uuid, $3,
                     $4::jsonb, $5::jsonb, $6,
                     $7, $8, $9,
                     $10, $11::jsonb, NOW())
                """,
                run_id, tenant_id, country,
                json.dumps(keyword_gaps),
                json.dumps(top_opportunities),
                state.get("competitors_s3_key"),
                state.get("trends_s3_key"),
                state.get("reddit_s3_key"),
                state.get("gsc_s3_key"),
                confidence_score,
                json.dumps(primary_keywords),
            )

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE acp_shared.acp_runs
                SET status = 'completed', completed_at = NOW()
                WHERE run_id = $1::uuid
                """,
                run_id,
            )

        completed_tools.append("synthesize")
        logger.info("synthesize_complete", run_id=run_id, confidence_score=confidence_score)
        return {"confidence_score": confidence_score, "completed_tools": completed_tools}

    return synthesize
