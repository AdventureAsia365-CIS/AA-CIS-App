"""
H-3 Mistake→Rule Pipeline.
PRD v1.1 §5.3: Gate rejection → Haiku extract → confidence >= 0.80 → auto-create
acp_output_rules row and back-fill rule_created_id on acp_hitl_requests.

Design:
- Takes pool (not conn) — acquires its own connection to run after HTTP response returns
- stage stored as smallint in DB; human-readable label used in prompt only
- error_message column used for rule description (matches acp_output_rules schema)
- rejection_note_structured always written for audit, even when rule not created
- actor_type omitted from audit_log — enum has no 'system' value
"""
import json
import logging
import time
from typing import Optional

import boto3

from services.acp_shared.tracer import AcpTracer

logger = logging.getLogger(__name__)

H3_CONFIDENCE_THRESHOLD = 0.80
_BEDROCK_REGION = "us-west-1"
_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

_STAGE_LABELS = {
    1: "S1 Rewrite",
    2: "S3 Campaign Planner",
    3: "S4 Blog",
    4: "S4 Social",
}

_H3_PROMPT = """\
You are a content quality rule extractor for Adventure Asia, a premium soft-adventure travel brand.

A human reviewer rejected AI-generated content with this note:
<rejection_note>
{rejection_note}
</rejection_note>

Context:
- Pipeline stage: {stage_label}
- Gate number: {gate_number}

Extract a deterministic quality rule from this rejection.

Return ONLY valid JSON, no other text:
{{
  "should_extract": true or false,
  "confidence": 0.0 to 1.0,
  "rule_type": "block" or "replace" or "flag",
  "pattern": "<exact substring to match — max 80 chars>",
  "description": "<why this pattern violates AA brand — 1 sentence, max 100 chars>",
  "reasoning": "<why confidence is this value>"
}}

Rules:
- should_extract=false if the rejection is about personal preference, not a repeatable pattern
- should_extract=false if you cannot identify a specific, unambiguous pattern
- confidence >= 0.80 only if the pattern is clear, short, and would catch the same mistake again
- rule_type="block" for banned phrases (preferred)
- rule_type="replace" if a substitution is implied
- rule_type="flag" for patterns that need human review, not outright blocking
- pattern must be a literal substring (< 80 chars) — no regex unless rule_type="flag"
- never create rules so broad they would block legitimate content
"""


def _call_haiku(rejection_note: str, gate_number: int) -> tuple[dict, int, int]:
    """Returns (extracted_data, input_tokens, output_tokens)."""
    client = boto3.client("bedrock-runtime", region_name=_BEDROCK_REGION)
    stage_label = _STAGE_LABELS.get(gate_number, f"Gate {gate_number}")
    prompt = _H3_PROMPT.format(
        rejection_note=rejection_note[:2000],
        stage_label=stage_label,
        gate_number=gate_number,
    )
    response = client.invoke_model(
        modelId=_MODEL_ID,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }),
        contentType="application/json",
        accept="application/json",
    )
    body = json.loads(response["body"].read())
    usage = body.get("usage", {})
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    text = body["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text), in_tok, out_tok


async def extract_and_save_rule(
    pool,
    hitl_id: str,
    run_id: str,
    gate_number: int,
    reviewer_notes: str,
) -> Optional[str]:
    """
    H-3 pipeline. Call with asyncio.create_task() after rejection HTTP response.
    Returns rule_id string if created, None otherwise.
    Fetches tenant_id from acp_runs internally.
    """
    if not reviewer_notes or len(reviewer_notes.strip()) < 10:
        logger.info("h3_skip_short_note run_id=%s", run_id)
        return None

    try:
        tracer = AcpTracer(run_id=run_id, tenant_id="")
        _t = time.time()
        with tracer.span("h3", "rule_extractor") as _span:
            extracted, in_tok, out_tok = _call_haiku(reviewer_notes, gate_number)
            tracer.record_llm_call(_span, _MODEL_ID, in_tok, out_tok, (time.time() - _t) * 1000)
        tracer.flush()
    except Exception as exc:
        logger.warning("h3_haiku_failed run_id=%s error=%s", run_id, exc)
        return None

    async with pool.acquire() as conn:
        # Fetch tenant_id (needed for rule + audit)
        run_row = await conn.fetchrow(
            "SELECT tenant_id FROM acp_shared.acp_runs WHERE run_id = $1::uuid",
            run_id,
        )
        tenant_id = str(run_row["tenant_id"]) if run_row else None

        # Always write structured extraction for audit, regardless of confidence
        await conn.execute(
            "UPDATE acp_shared.acp_hitl_requests "
            "SET rejection_note_structured = $2::jsonb WHERE hitl_id = $1",
            hitl_id,
            json.dumps(extracted),
        )

        if not extracted.get("should_extract", False):
            logger.info("h3_skip_no_extract run_id=%s reasoning=%s",
                        run_id, extracted.get("reasoning", ""))
            return None

        confidence = float(extracted.get("confidence", 0))
        if confidence < H3_CONFIDENCE_THRESHOLD:
            logger.info("h3_skip_low_confidence run_id=%s confidence=%.2f", run_id, confidence)
            return None

        # Insert rule — ON CONFLICT DO NOTHING prevents duplicate patterns per tenant+stage
        rule_id = await conn.fetchval(
            """
            INSERT INTO acp_shared.acp_output_rules
                (tenant_id, stage, rule_type, pattern, error_message,
                 source_type, source_hitl_id, confidence_score, is_active)
            VALUES ($1, $2, $3, $4, $5, 'hitl_rejection', $6::uuid, $7, TRUE)
            ON CONFLICT DO NOTHING
            RETURNING rule_id
            """,
            tenant_id,
            gate_number,
            extracted["rule_type"],
            extracted["pattern"][:500],
            extracted.get("description", "")[:500],
            hitl_id,
            confidence,
        )

        if rule_id:
            # Back-fill rule_created_id on the HITL request
            await conn.execute(
                "UPDATE acp_shared.acp_hitl_requests SET rule_created_id = $2 WHERE hitl_id = $1",
                hitl_id,
                rule_id,
            )

        # Audit log — omit actor_type (no 'system' value in enum)
        await conn.execute(
            """
            INSERT INTO acp_shared.audit_log
                (tenant_id, actor, action, resource_type, resource_id, details)
            VALUES ($1, 'system', 'rule.h3.create', 'acp_output_rules', $2, $3::jsonb)
            """,
            tenant_id,
            str(rule_id) if rule_id else "duplicate",
            json.dumps({
                "hitl_id": hitl_id,
                "run_id": run_id,
                "gate": gate_number,
                "confidence": confidence,
                "pattern": extracted.get("pattern", "")[:80],
                "created": bool(rule_id),
            }),
        )

    if rule_id:
        logger.info("h3_rule_created rule_id=%s gate=%d confidence=%.2f pattern=%s",
                    rule_id, gate_number, confidence, extracted["pattern"][:50])
    else:
        logger.info("h3_duplicate_skipped pattern=%s", extracted.get("pattern", "")[:50])

    return str(rule_id) if rule_id else None
