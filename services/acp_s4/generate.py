"""
AA-49 H-2 — S4 Blog Draft Generation with post-processor + evaluator integration.

Flow:
  1. LLM generates blog draft (content_md, seo_title, seo_meta)
  2. apply_output_rules() — deterministic brand/quality rules (ECS, hits DB)
  3. acp-s4-evaluate Lambda — isolated quality scoring (Bedrock only, no DB)
  4. Gate: evaluator_score >= 7.5 required
  5. Save to acp_silver_s4.blog_drafts with all harness columns
"""
import json
import boto3
import asyncpg
import structlog

from api.services.acp_post_processor import apply_output_rules, OutputRuleViolation

logger = structlog.get_logger()

EVALUATOR_FUNCTION_NAME = "aa-cis-dev-acp-s4-evaluate"
EVALUATOR_SCORE_THRESHOLD = 7.5

_lambda_client = boto3.client("lambda", region_name="us-west-1")


async def generate_blog_draft(
    tenant_id: str,
    run_id: str,
    calendar_item_id: str,
    db: asyncpg.Connection,
    llm_output: dict,
) -> dict:
    """
    Apply H-2 post-processor + H-1 evaluator after LLM blog draft generation.

    Args:
        tenant_id:   UUID string
        run_id:      UUID string
        calendar_item_id: UUID string
        db:          asyncpg connection (for rules fetch + blog_drafts insert)
        llm_output:  same as draft_input (passed through for mutation)

    Returns:
        dict with status, draft_id, evaluator_score, review_flags, rules_applied
    """
    output = dict(llm_output)

    # STEP 1 — Apply output rules (deterministic, post-LLM, hits DB)
    try:
        output = await apply_output_rules(
            output=output,
            stage="S4",
            tenant_id=tenant_id,
            db=db,
        )
    except OutputRuleViolation as e:
        logger.warning("s4_rule_violation", rule_id=e.rule_id, rule_type=e.rule_type, detail=str(e))
        return {
            "status": "blocked",
            "error": {"rule_id": e.rule_id, "rule_type": e.rule_type, "message": str(e)},
        }

    review_flags = output.get("review_flags", [])
    rules_applied = output.get("rules_applied", [])

    # STEP 2 — Call acp-s4-evaluate Lambda (text-only — isolation enforced)
    content_text = output.get("content_md", "") or output.get("content", "")
    try:
        eval_response = _lambda_client.invoke(
            FunctionName=EVALUATOR_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps({"text": content_text}),  # ONLY content, no brand/outline
        )
        eval_body = json.loads(eval_response["Payload"].read())
        if eval_body.get("statusCode") != 200:
            raise RuntimeError(f"Evaluator returned {eval_body.get('statusCode')}: {eval_body.get('body')}")
        eval_result = json.loads(eval_body["body"])
    except Exception as e:
        logger.error("s4_evaluator_failed", error=str(e))
        return {"status": "evaluator_error", "error": str(e)}

    evaluator_score = float(eval_result.get("evaluator_score", 0))
    evaluator_input_hash = eval_result.get("evaluator_input_hash", "")
    eval_issues = eval_result.get("issues", [])

    logger.info("s4_evaluator_done", score=evaluator_score, issues=len(eval_issues),
                hash=evaluator_input_hash[:16])

    # STEP 3 — Gate: score must meet threshold
    if evaluator_score < EVALUATOR_SCORE_THRESHOLD:
        logger.warning("s4_score_gate_failed", score=evaluator_score, threshold=EVALUATOR_SCORE_THRESHOLD)
        return {
            "status": "score_gate_failed",
            "evaluator_score": evaluator_score,
            "issues": eval_issues,
        }

    # STEP 4 — Save to blog_drafts with all harness columns
    row = await db.fetchrow(
        """INSERT INTO acp_silver_s4.blog_drafts
             (run_id, tenant_id, calendar_item_id, title, slug, content_md,
              word_count, seo_title, seo_meta, target_keywords,
              status, evaluator_score, evaluator_input_hash, review_flags, rules_applied)
           VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6,
                   $7, $8, $9, $10::jsonb,
                   'draft', $11, $12, $13::jsonb, $14::jsonb)
           RETURNING draft_id::text""",
        run_id,
        tenant_id,
        calendar_item_id,
        output.get("title", ""),
        output.get("slug", ""),
        output.get("content_md", ""),
        len(content_text.split()),
        output.get("seo_title", ""),
        output.get("seo_meta", ""),
        json.dumps(output.get("target_keywords", [])),
        evaluator_score,
        evaluator_input_hash,
        json.dumps(review_flags),
        json.dumps(rules_applied),
    )

    logger.info("s4_draft_saved", draft_id=row["draft_id"], score=evaluator_score,
                rules_applied=len(rules_applied), review_flags=len(review_flags))

    return {
        "status": "ok",
        "draft_id": row["draft_id"],
        "evaluator_score": evaluator_score,
        "evaluator_input_hash": evaluator_input_hash,
        "review_flags": review_flags,
        "rules_applied": rules_applied,
    }
