"""
3-tier lesson read/write/promote.

Tier 1 (job)   — this run only           → acp_shared.acp_lessons_agency
Tier 2 (root)  — country-level durable   → acp_shared.acp_lessons_agency
Tier 3 (system)— cross-tenant (>=0.85)   → acp_shared.acp_lessons_shared
"""
import json
import os
import time

import boto3
import psycopg2
import psycopg2.extras

import logging

from models import LessonUpdateOutput, SystemPromotion  # noqa: F401

logger = logging.getLogger(__name__)

HAIKU_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
H3_PROMOTION_THRESHOLD = 0.80
_BEDROCK_REGION = "us-west-1"

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _read_prompt(filename: str) -> str:
    with open(os.path.join(_PROMPT_DIR, filename)) as f:
        return f.read()


def _bedrock_client():
    return boto3.client("bedrock-runtime", region_name=_BEDROCK_REGION)


def _invoke(client, model_id: str, prompt: str, max_tokens: int = 2048) -> tuple[str, int, int]:
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    for attempt in range(3):
        try:
            resp = client.invoke_model(modelId=model_id, body=body)
            parsed = json.loads(resp["body"].read())
            text = parsed["content"][0]["text"]
            usage = parsed.get("usage", {})
            return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        except client.exceptions.ThrottlingException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def read_lessons(conn, tenant_id: str, country: str) -> str:
    """Read last-5 job + all root lessons for tenant+country, plus all system lessons."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT tier, content FROM acp_shared.acp_lessons_agency
            WHERE tenant_id = %s AND country = %s
              AND tier = 'job'
            ORDER BY created_at DESC LIMIT 5
        """, (tenant_id, country))
        job_rows = cur.fetchall()

        cur.execute("""
            SELECT tier, content FROM acp_shared.acp_lessons_agency
            WHERE tenant_id = %s AND country = %s
              AND tier = 'root'
            ORDER BY created_at DESC
        """, (tenant_id, country))
        root_rows = cur.fetchall()

        cur.execute("""
            SELECT content FROM acp_shared.acp_lessons_shared
            WHERE country = %s OR country IS NULL
            ORDER BY created_at DESC
        """, (country,))
        system_rows = cur.fetchall()

    parts = []
    if job_rows:
        parts.append("## Recent Run Lessons (job)")
        parts.extend(f"- {r['content']}" for r in job_rows)
    if root_rows:
        parts.append("## Country Lessons (root)")
        parts.extend(f"- {r['content']}" for r in root_rows)
    if system_rows:
        parts.append("## System Lessons")
        parts.extend(f"- {r['content']}" for r in system_rows)

    return "\n".join(parts) if parts else "No prior lessons."


def lesson_update_call(
    run_id: str,
    tenant_id: str,
    country: str,
    lesson_summary: str,
    skeleton_summary: str,
) -> tuple[LessonUpdateOutput, int, int]:
    """Step 7: Bedrock Haiku lesson_update. Returns (output, in_tok, out_tok)."""
    prompt_template = _read_prompt("lesson_update_prompt.md")
    run_meta = json.dumps({
        "run_id": run_id,
        "tenant_id": tenant_id,
        "country": country,
        "skeleton_summary": skeleton_summary,
    }, indent=2)
    prompt = (
        f"{prompt_template}\n\n"
        f"## Run Metadata\n```json\n{run_meta}\n```\n\n"
        f"## Existing Lessons\n{lesson_summary}"
    )

    client = _bedrock_client()
    text, in_tok, out_tok = _invoke(client, HAIKU_MODEL_ID, prompt)

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    data = json.loads(text)
    return LessonUpdateOutput(**data), in_tok, out_tok


def write_lessons(conn, run_id: str, tenant_id: str, country: str, output: LessonUpdateOutput) -> None:
    """Step 8: Write tier 1+2 to acp_lessons_agency, tier 3 to acp_lessons_shared."""
    with conn.cursor() as cur:
        for content in output.job_lessons:
            cur.execute("""
                INSERT INTO acp_shared.acp_lessons_agency
                    (run_id, tenant_id, country, tier, content)
                VALUES (%s, %s, %s, 'job', %s)
            """, (run_id, tenant_id, country, content))

        for content in output.root_lessons_append:
            cur.execute("""
                INSERT INTO acp_shared.acp_lessons_agency
                    (run_id, tenant_id, country, tier, content)
                VALUES (%s, %s, %s, 'root', %s)
            """, (run_id, tenant_id, country, content))

        for promotion in output.system_promotions:
            if promotion.confidence < H3_PROMOTION_THRESHOLD:
                logger.info(
                    "h3_promotion_below_threshold run_id=%s confidence=%.2f content=%s",
                    run_id, promotion.confidence, promotion.content[:60],
                )
                continue
            cur.execute("""
                INSERT INTO acp_shared.acp_lessons_shared
                    (content, country, promoted_from_run_id)
                VALUES (%s, %s, %s)
            """, (promotion.content, country, run_id))
            logger.info(
                "h3_promotion_written run_id=%s confidence=%.2f content=%s",
                run_id, promotion.confidence, promotion.content[:60],
            )
