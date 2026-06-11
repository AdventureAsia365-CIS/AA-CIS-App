"""
Lambda entry point — S3 Campaign Planner.

event = {"run_id": "uuid", "tenant_id": "str"}

Steps:
  1  Read inputs from DB (acp_run_context, tenant_brand_rules, lessons)
  2  Build compact_packet
  3  Bedrock Sonnet skeleton call
  4  Bedrock Sonnet expand call
  5  Bedrock Haiku ads call + PDF + S3 upload
  6  Deterministic validators (non-blocking)
  7  Bedrock Haiku lesson_update call
  8  Write lessons
  9  Write outputs (acp_run_context, content_calendars, ads_plan)
  10 Gate 2 HITL request + EventBridge
"""
import json
import os
import time
import traceback
from urllib.parse import urlparse

import boto3
import psycopg2
import psycopg2.extras

import ads as _ads
import lessons as _lessons
import planner as _planner
import validators as _validators
from models import S3RunResult
from run_context import get_run_context_sync, write_s3_stage_sync

try:
    from acp_shared.tracer import AcpTracer as _AcpTracer
except ImportError:
    _AcpTracer = None

_EB_SOURCE_S3 = "acp.s3"
_EB_DETAIL_S3_COMPLETED = "acp.s3.completed"

S3_THRESHOLD_BYTES = 512_000  # 500 KB — above this, load large fields from S3
_S3_SILVER_BUCKET = os.environ.get("S3_SILVER_BUCKET", "acp-silver-867490540162")


def _get_db_conn():
    db_url = os.environ["DATABASE_URL"]
    parts = urlparse(db_url)
    return psycopg2.connect(
        host=parts.hostname,
        port=parts.port or 5432,
        user=parts.username,
        password=parts.password,
        dbname=parts.path.lstrip("/"),
        sslmode="require",
    )


def _read_run_inputs(conn, run_id: str, tenant_id: str) -> tuple[dict, dict, str]:
    """Returns (run_context_dict, tenant_rules, country)."""
    # Validated read — raises RunContextValidationError if row absent or s2 fields missing
    ctx = get_run_context_sync(conn, run_id, require_stages=("s2",))
    run_context = {
        "s2_keyword_research": ctx.s2_keyword_research or {},
        "s2_visibility_report": ctx.s2_visibility_report or {},
        "s1_keywords_used": ctx.s1_keywords_used or [],
        "brand_brief": ctx.brand_brief or {},
        # S3 offload keys — may be None for runs before migration 060
        "s2_keywords_s3_key": ctx.s2_keywords_s3_key,
        "s2_report_s3_key": ctx.s2_report_s3_key,
    }

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT system_prompt, style_guide, forbidden_words
            FROM shared.tenant_brand_rules
            WHERE tenant_id = %s
        """, (tenant_id,))
        rules_row = cur.fetchone()
        tenant_rules = dict(rules_row) if rules_row else {}

        cur.execute(
            "SELECT country FROM acp_shared.acp_runs WHERE run_id = %s",
            (run_id,),
        )
        run_row = cur.fetchone()
        if not run_row:
            raise ValueError(f"No acp_runs row for run_id={run_id}")
        country = run_row["country"] or ""

    return run_context, tenant_rules, country


def _write_outputs(
    conn,
    run_id: str,
    tenant_id: str,
    country: str,
    skeleton,
    expanded_markdown: str,
    ads_output,
    ads_s3_key: str,
    validation_errors: list[str],
    funnel_mix: dict,
    model_id_skeleton: str,
    model_id_ads: str,
    in_tok: int,
    out_tok: int,
) -> tuple[str, str]:
    """Returns (calendar_id, ads_plan_id)."""
    skeleton_json = json.dumps(skeleton.model_dump())
    campaigns_json = json.dumps([c.model_dump() for c in ads_output.campaigns])
    errors_json = json.dumps(validation_errors)
    funnel_json = json.dumps(funnel_mix)

    with conn.cursor() as cur:
        # content_calendars
        cur.execute("""
            INSERT INTO acp_silver_s3.content_calendars
                (run_id, tenant_id, country, strategy, calendar_weeks,
                 expanded_markdown, skeleton_json, funnel_mix,
                 validation_errors, model_id, input_tokens, output_tokens)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb,
                    %s, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s, %s, %s)
            RETURNING calendar_id
        """, (
            run_id, tenant_id, country,
            json.dumps({"document_title": skeleton.document_title}),
            json.dumps([w.model_dump() for w in skeleton.weeks]),
            expanded_markdown,
            skeleton_json,
            funnel_json,
            errors_json,
            model_id_skeleton,
            in_tok, out_tok,
        ))
        calendar_id = str(cur.fetchone()[0])

        # ads_plan
        cur.execute("""
            INSERT INTO acp_silver_s3.ads_plan
                (run_id, tenant_id, country, model_id, campaigns,
                 pdf_s3_key, input_tokens, output_tokens)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            RETURNING ads_plan_id
        """, (
            run_id, tenant_id, country, model_id_ads,
            campaigns_json, ads_s3_key, in_tok, out_tok,
        ))
        ads_plan_id = str(cur.fetchone()[0])

    # Atomic S3 stage write — only touches s3_* columns
    write_s3_stage_sync(conn, run_id, {
        "s3_content_calendar": {
            "calendar_id": calendar_id, "document_title": skeleton.document_title,
        },
        "s3_ads_plan": {"ads_plan_id": ads_plan_id, "campaign_count": len(ads_output.campaigns)},
        "s3_funnel_mix": funnel_mix,
    })

    return calendar_id, ads_plan_id


def _create_hitl_gate2(conn, run_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO acp_shared.acp_hitl_requests
                (run_id, stage, gate_type, reviewer_id, status,
                 auto_approved, confidence_score, reviewer_type, payload)
            VALUES (%s, 3, 'content_calendar', 'ms.thu',
                    'pending', false, NULL, 'tenant_admin', %s::jsonb)
        """, (run_id, json.dumps({"gate": 2, "reviewer": "ms.thu"})))
        # AA-186: gate is now an event boundary — mark the stage as awaiting
        # human review until acp.hitl.approved/rejected resolves it.
        cur.execute("""
            UPDATE acp_shared.acp_stage_runs
            SET status = 'awaiting_gate', updated_at = NOW()
            WHERE run_id = %s AND stage = 's3'
        """, (run_id,))


def _record_cost(conn, run_id: str, stage: str, cost: float, in_tok: int, out_tok: int) -> None:
    """Upsert per-stage cost into acp_stage_runs using the existing connection."""
    try:
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
                (run_id, stage, cost, in_tok, out_tok),
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("_record_cost failed run_id=%s: %s", run_id, e)


def load_context_field(
    run_context: dict,
    field_key: str,
    s3_key_field: str,
    s3_client,
    bucket: str,
):
    """Return field value from S3 when an offload key is present, else return inline value.

    Graceful: if s3_key_field is absent or None, falls back to run_context[field_key].
    """
    s3_key = run_context.get(s3_key_field)
    if s3_key:
        obj = s3_client.get_object(Bucket=bucket, Key=s3_key)
        return json.loads(obj["Body"].read())
    return run_context.get(field_key)


_HAIKU_PRICE = {"input": 0.25, "output": 1.25}
_SONNET_PRICE = {"input": 3.0, "output": 15.0}


def _calc_cost(in_tok: int, out_tok: int, tier: str) -> float:
    p = _SONNET_PRICE if tier == "sonnet" else _HAIKU_PRICE
    return round((in_tok * p["input"] + out_tok * p["output"]) / 1_000_000, 6)


def _finalize_cost(conn, run_id: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE acp_shared.acp_runs r
                SET total_llm_cost_usd = (
                    SELECT COALESCE(SUM(llm_cost_usd), 0)
                    FROM acp_shared.acp_stage_runs WHERE run_id = r.run_id
                )
                WHERE r.run_id = %s
                """,
                (run_id,),
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("_finalize_cost failed run_id=%s: %s", run_id, e)


def _emit_eventbridge(run_id: str, tenant_id: str) -> None:
    eb = boto3.client("events", region_name="us-west-1")
    eb.put_events(Entries=[{
        "Source": _EB_SOURCE_S3,
        "DetailType": _EB_DETAIL_S3_COMPLETED,
        "Detail": json.dumps({"run_id": run_id, "tenant_id": tenant_id, "gate": 2}),
        "EventBusName": "aa-cis-dev-acp-events",
    }])


def handler(event, context):
    run_id = event.get("run_id", "")
    tenant_id = event.get("tenant_id", "")

    if not run_id or not tenant_id:
        return {"status": "error", "error": "run_id and tenant_id are required"}

    tracer = None
    if _AcpTracer is not None:
        try:
            tracer = _AcpTracer(run_id=run_id, tenant_id=tenant_id)
        except Exception:
            pass

    conn = None
    total_in = 0
    total_out = 0
    try:
        conn = _get_db_conn()

        # ── Step 1: Read inputs ───────────────────────────────────────────────
        run_context, tenant_rules, country = _read_run_inputs(conn, run_id, tenant_id)

        # ── Step 1a: S3 offload — resolve large fields before building packet ─
        context_bytes = len(json.dumps(run_context, default=str).encode("utf-8"))
        if context_bytes > S3_THRESHOLD_BYTES:
            s3_client = boto3.client("s3", region_name="us-west-1")
            run_context["s2_keyword_research"] = load_context_field(
                run_context, "s2_keyword_research", "s2_keywords_s3_key",
                s3_client, _S3_SILVER_BUCKET,
            )
            run_context["s2_visibility_report"] = load_context_field(
                run_context, "s2_visibility_report", "s2_report_s3_key",
                s3_client, _S3_SILVER_BUCKET,
            )

        s1_keywords_used = run_context.get("s1_keywords_used") or []
        if isinstance(s1_keywords_used, str):
            s1_keywords_used = json.loads(s1_keywords_used)

        # ── Step 1b: Read lessons ─────────────────────────────────────────────
        lesson_summary = _lessons.read_lessons(conn, tenant_id, country)

        # ── Step 2: Build compact_packet ──────────────────────────────────────
        packet = _planner.build_compact_packet(run_context, tenant_rules, country, lesson_summary)

        # ── Step 3: Skeleton ──────────────────────────────────────────────────
        _t = time.time()
        skeleton, in3, out3 = _planner.skeleton_call(packet)
        if tracer:
            with tracer.span("s3", "skeleton") as span:
                tracer.record_llm_call(span, _planner.SONNET_MODEL_ID, in3, out3, (time.time() - _t) * 1000)
        total_in += in3
        total_out += out3
        _record_cost(conn, run_id, "s3", _calc_cost(in3, out3, "sonnet"), in3, out3)

        # ── Step 4: Expand ────────────────────────────────────────────────────
        _t = time.time()
        expanded_markdown, in4, out4 = _planner.expand_call(skeleton, tenant_rules, packet)
        if tracer:
            with tracer.span("s3", "expand") as span:
                tracer.record_llm_call(span, _planner.SONNET_MODEL_ID, in4, out4, (time.time() - _t) * 1000)
        total_in += in4
        total_out += out4
        _record_cost(conn, run_id, "s3", _calc_cost(in4, out4, "sonnet"), in4, out4)

        # ── Step 5: Ads ───────────────────────────────────────────────────────
        _t = time.time()
        ads_output, in5, out5 = _ads.generate_ads(packet)
        if tracer:
            with tracer.span("s3", "ads") as span:
                tracer.record_llm_call(span, _ads.HAIKU_MODEL_ID, in5, out5, (time.time() - _t) * 1000)
        total_in += in5
        total_out += out5
        _record_cost(conn, run_id, "s3", _calc_cost(in5, out5, "haiku"), in5, out5)
        ads_s3_key = _ads.upload_ads_pdf(ads_output, tenant_id, country, run_id)

        # ── Step 6: Validators (non-blocking) ─────────────────────────────────
        all_posts = [
            p.model_dump()
            for week in skeleton.weeks
            for p in week.posts
        ]
        validation_errors = _validators.run_all(
            expanded_markdown, all_posts, country, s1_keywords_used
        )

        # ── Step 7: Lesson update ─────────────────────────────────────────────
        n_posts = sum(len(w.posts) for w in skeleton.weeks)
        skeleton_summary = f"{skeleton.document_title} — {len(skeleton.weeks)} weeks, {n_posts} posts"
        _t = time.time()
        lesson_output, in7, out7 = _lessons.lesson_update_call(
            run_id, tenant_id, country, lesson_summary, skeleton_summary
        )
        if tracer:
            with tracer.span("s3", "lesson_update") as span:
                tracer.record_llm_call(span, _lessons.HAIKU_MODEL_ID, in7, out7, (time.time() - _t) * 1000)
        total_in += in7
        total_out += out7
        _record_cost(conn, run_id, "s3", _calc_cost(in7, out7, "haiku"), in7, out7)

        # ── Step 8: Write lessons ─────────────────────────────────────────────
        _lessons.write_lessons(conn, run_id, tenant_id, country, lesson_output)

        # ── Step 9: Write outputs ─────────────────────────────────────────────
        funnel_mix = packet.funnel_mix
        calendar_id, ads_plan_id = _write_outputs(
            conn, run_id, tenant_id, country,
            skeleton, expanded_markdown,
            ads_output, ads_s3_key,
            validation_errors, funnel_mix,
            _planner.SONNET_MODEL_ID, _ads.HAIKU_MODEL_ID,
            total_in, total_out,
        )

        # ── Step 10: Gate 2 HITL + EventBridge ───────────────────────────────
        _create_hitl_gate2(conn, run_id)
        _finalize_cost(conn, run_id)
        conn.commit()

        if tracer:
            tracer.flush()
        _emit_eventbridge(run_id, tenant_id)

        return S3RunResult(
            run_id=run_id,
            status="completed",
            calendar_id=calendar_id,
            ads_plan_id=ads_plan_id,
            validation_errors=validation_errors,
            input_tokens=total_in,
            output_tokens=total_out,
        ).model_dump()

    except Exception as exc:
        if conn:
            conn.rollback()
        return {
            "status": "error",
            "run_id": run_id,
            "tenant_id": tenant_id,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        if conn:
            conn.close()
