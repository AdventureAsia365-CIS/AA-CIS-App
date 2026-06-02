"""
LLM cost tracking utilities for ACP pipeline stages.

Prices are per 1M tokens (USD).
"""
import logging
import os

import psycopg2

logger = logging.getLogger(__name__)

BEDROCK_PRICING = {
    "sonnet": {"input": 3.0,  "output": 15.0},
    "haiku":  {"input": 0.25, "output": 1.25},
}


def calc_bedrock_cost(input_tokens: int, output_tokens: int, model_tier: str) -> float:
    p = BEDROCK_PRICING.get(model_tier, BEDROCK_PRICING["sonnet"])
    return round((input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000, 6)


def extract_usage_from_response(response: dict) -> tuple[int, int]:
    """
    Handles both Bedrock invoke_model and converse API response shapes.
    Returns (input_tokens, output_tokens). Never raises — returns (0, 0) on missing key.
    """
    try:
        if "usage" in response:
            u = response["usage"]
            return (
                u.get("inputTokens", u.get("input_tokens", 0)),
                u.get("outputTokens", u.get("output_tokens", 0)),
            )
        if "ResponseMetadata" in response:
            meta = response.get("usage", {})
            return meta.get("inputTokens", 0), meta.get("outputTokens", 0)
    except Exception:
        pass
    return 0, 0


def record_stage_cost(
    run_id: str,
    stage: str,
    cost: float,
    input_tokens: int,
    output_tokens: int,
    db_url: str = None,
) -> None:
    """
    Atomically accumulate cost into acp_stage_runs for (run_id, stage).
    Safe to call multiple times per stage — each Bedrock call adds to the total.
    Never raises — logs warning on failure.
    """
    url = db_url or os.environ.get("DATABASE_URL")
    if not url:
        logger.warning("record_stage_cost: DATABASE_URL not set, skipping")
        return
    if not run_id:
        return
    try:
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO acp_shared.acp_stage_runs
                        (run_id, stage, llm_cost_usd, tokens_input, tokens_output)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, stage) DO UPDATE
                        SET llm_cost_usd  = acp_shared.acp_stage_runs.llm_cost_usd  + EXCLUDED.llm_cost_usd,
                            tokens_input  = acp_shared.acp_stage_runs.tokens_input  + EXCLUDED.tokens_input,
                            tokens_output = acp_shared.acp_stage_runs.tokens_output + EXCLUDED.tokens_output,
                            updated_at    = NOW()
                    """,
                    (run_id, stage, cost, input_tokens, output_tokens),
                )
            conn.commit()
    except Exception as e:
        logger.warning("record_stage_cost failed run_id=%s stage=%s: %s", run_id, stage, e)


def finalize_run_cost(run_id: str, db_url: str = None) -> None:
    """
    Sum all stage costs → acp_runs.total_llm_cost_usd.
    Call once when run reaches terminal state (completed/failed).
    Safe to call multiple times — idempotent.
    Never raises — logs warning on failure.
    """
    url = db_url or os.environ.get("DATABASE_URL")
    if not url:
        logger.warning("finalize_run_cost: DATABASE_URL not set, skipping")
        return
    if not run_id:
        return
    try:
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE acp_shared.acp_runs r
                    SET total_llm_cost_usd = (
                        SELECT COALESCE(SUM(llm_cost_usd), 0)
                        FROM acp_shared.acp_stage_runs
                        WHERE run_id = r.run_id
                    )
                    WHERE r.run_id = %s
                    """,
                    (run_id,),
                )
            conn.commit()
    except Exception as e:
        logger.warning("finalize_run_cost failed run_id=%s: %s", run_id, e)
