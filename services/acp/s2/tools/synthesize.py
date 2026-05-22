"""
Synthesis node. Always runs last.
Calls Bedrock claude-sonnet-4-5 to build visibility analysis.

Writes:
  1. acp_silver_s2.visibility_reports — full research output
  2. acp_shared.acp_run_context       — s2_keyword_research, s2_visibility_report,
                                        s2_keyword_clusters, s2_confidence_score
  3. acp_shared.acp_runs              — status = 'completed'

System prompt built from Ms. Thư's stage-2 prompt files in ../prompts/.
"""
import json
import os
import structlog
from pathlib import Path

import boto3

logger = structlog.get_logger()

_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20251001-v1:0"
_AWS_REGION = os.environ.get("AWS_REGION", "us-west-1")
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("prompt_file_missing", path=str(path))
    return ""


# Loaded once at module import — ECS cold-start only
TOUR_VISIBILITY_RULES = _load_prompt("tour_visibility_rules.md")
MARKET_PREFERENCE_RULES = _load_prompt("market_preference_rules.md")
AA_MATCHING_RULES = _load_prompt("aa_matching_rules.md")
BLOG_BRIEF_RULES = _load_prompt("blog_brief_rules.md")
SOCIAL_CONTENT_RULES = _load_prompt("social_content_rules.md")

_SYSTEM_PROMPT = f"""You are an expert travel content strategist for Adventure Asia \
— a premium curated soft-adventure brand.

{TOUR_VISIBILITY_RULES}

When generating blog briefs and content ideas, apply:
{BLOG_BRIEF_RULES}

When matching opportunities to AA tours, apply:
{AA_MATCHING_RULES}

For any social content ideas, apply:
{SOCIAL_CONTENT_RULES}
"""


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

        user_prompt = (
            f"Analyze SEO visibility data for '{country}' tours.\n\n"
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
            "  keyword_clusters: array of objects {cluster_name, keywords[], intent}\n"
            "  market_preference: object {dominant_duration, dominant_style, price_band}\n"
            "  aa_tour_matches: array of objects {keyword, tour_suggestion, match_reason}\n"
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
                    "system": _SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
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
                "keyword_clusters": [],
                "market_preference": {},
                "aa_tour_matches": [],
            }

        top_opportunities = llm_output.get("top_opportunities") or []
        keyword_gaps = llm_output.get("content_gaps") or []
        keyword_clusters = llm_output.get("keyword_clusters") or []
        market_preference = llm_output.get("market_preference") or {}
        aa_tour_matches = llm_output.get("aa_tour_matches") or []
        primary_keywords = top_opportunities[:3]

        # 1. Write to visibility_reports
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
                json.dumps({"s3_key": state.get("competitors_s3_key")}),
                json.dumps({"s3_key": state.get("trends_s3_key")}),
                json.dumps({"s3_key": state.get("reddit_s3_key")}),
                json.dumps({"s3_key": state.get("gsc_s3_key")}),
                confidence_score,
                json.dumps(primary_keywords),
            )

        # 2. Write S2 outputs to acp_run_context (upsert — S1 may not have run)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO acp_shared.acp_run_context
                    (run_id, tenant_id,
                     s2_keyword_research, s2_visibility_report,
                     s2_keyword_clusters, s2_market_preference, s2_aa_tour_matches,
                     s2_confidence_score, updated_at)
                VALUES
                    ($1::uuid, $2,
                     $3::jsonb, $4::jsonb,
                     $5::jsonb, $6::jsonb, $7::jsonb,
                     $8, NOW())
                ON CONFLICT (run_id) DO UPDATE SET
                    s2_keyword_research  = EXCLUDED.s2_keyword_research,
                    s2_visibility_report = EXCLUDED.s2_visibility_report,
                    s2_keyword_clusters  = EXCLUDED.s2_keyword_clusters,
                    s2_market_preference = EXCLUDED.s2_market_preference,
                    s2_aa_tour_matches   = EXCLUDED.s2_aa_tour_matches,
                    s2_confidence_score  = EXCLUDED.s2_confidence_score,
                    updated_at           = NOW()
                """,
                run_id, tenant_id,
                json.dumps({"top_opportunities": top_opportunities, "content_gaps": keyword_gaps,
                            "recommended_actions": llm_output.get("recommended_actions", [])}),
                json.dumps({"summary": llm_output.get("summary", ""),
                            "risk_flags": llm_output.get("risk_flags", []),
                            "primary_keywords": primary_keywords}),
                json.dumps(keyword_clusters),
                json.dumps(market_preference),
                json.dumps(aa_tour_matches),
                round(confidence_score / 100.0, 4),  # normalize 0-100 → 0.0-1.0
            )

        # 3. Update acp_runs status
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
