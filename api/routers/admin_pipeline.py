# api/routers/admin_pipeline.py
# Admin-only pipeline endpoints — mounted at /admin/* (no Lambda Authorizer at API GW)
# Auth: x-admin-secret header only (no tenant JWT accepted)

import asyncio
import json
import os

import asyncpg
import boto3 as _boto3
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List

from api.routers.admin import verify_admin_secret
from api.routers.v1_pipeline import _rewrite_tour

logger = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["admin-pipeline"])

_pipeline_semaphore = asyncio.Semaphore(2)

# ── Pydantic models ───────────────────────────────────────────────────────────

class TourRunRequest(BaseModel):
    tour_id: str
    batch_id: str
    tenant_id: str
    retry_count: int = 0
    validation_feedback: list = []
    seo_mode: str = "dataforseo"
    rewrite_language: str = "en-US"
    model_tier: str = "haiku"
    subtitle_focus: str = "standard"


class UploadUrlRequest(BaseModel):
    filename: str
    content_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    seo_mode: str = "dataforseo"


class UploadUrlResponse(BaseModel):
    upload_url: str
    s3_key: str
    bucket: str


class IngestS3Request(BaseModel):
    s3_key: str
    bucket: str
    seo_mode: str = "dataforseo"
    model_tier: str = "haiku"
    subtitle_focus: str = "standard"


class BrandIdentityUpdate(BaseModel):
    system_prompt: Optional[str] = None
    style_guide:   Optional[str] = None
    forbidden_words: Optional[List[str]] = None


# ── POST /admin/run-tour ──────────────────────────────────────────────────────

async def _execute_run_tour(req: TourRunRequest) -> dict:
    """Core tour rewrite — called by HTTP endpoint and background retry task."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    TENANT_SLUG_MAP = {"aa_internal": "00000000-0000-0000-0000-000000000001"}
    tenant_uuid = TENANT_SLUG_MAP.get(req.tenant_id, req.tenant_id)
    try:
        row = await conn.fetchrow(
            "SELECT * FROM silver_aa_internal.raw_tours WHERE tour_id = $1::uuid",
            req.tour_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"Tour {req.tour_id} not found")

        tour = {
            "name":        row["src_name"],
            "subtitle":    row["src_subtitle"],
            "summary":     row["src_summary"],
            "description": row["src_description"],
            "highlights":  row["src_highlights"],
            "itineraries": row["src_itineraries"],
            "country":     row["country"],
            "duration":    row["duration"],
            "price":       row["price_raw"],
            "inclusions":  row["inclusions"],
            "exclusions":  row["exclusions"],
        }

        brand_rules: dict = {}
        try:
            br_row = await conn.fetchrow("""
                SELECT system_prompt, style_guide, forbidden_words
                FROM shared.tenant_brand_rules
                WHERE tenant_id = $1::uuid AND is_active = true
                ORDER BY version DESC LIMIT 1
            """, tenant_uuid)
            if br_row:
                brand_rules = {
                    "system_prompt":    br_row["system_prompt"] or "",
                    "style_guide":      br_row["style_guide"] or "",
                    "forbidden_words":  (
                        list(br_row["forbidden_words"]) if isinstance(br_row["forbidden_words"], list)
                        else __import__("json").loads(br_row["forbidden_words"] or "[]")
                    ),
                    "rewrite_language": getattr(req, "rewrite_language", "en-US"),
                }
        except Exception as _br_err:
            logger.warning("brand_rules_fetch_failed", error=str(_br_err))

        seo_data: dict = {}
        try:
            from services.seo_intelligence.handler import process_seo
            destination = (
                f"{row['country']} tours" if row.get("country") else row.get("src_name", "")
            )
            if destination:
                seo_result = await process_seo(
                    tour_id=req.tour_id, destination=destination, seo_mode=req.seo_mode,
                )
                seo_data = seo_result.get("data", {})
        except Exception as _seo_err:
            logger.warning("seo_step_failed", tour_id=req.tour_id, error=str(_seo_err))

        result = await _rewrite_tour(
            tour, idx=0, total=1,
            brand_rules=brand_rules,
            seo=seo_data,
            model_tier=req.model_tier,
            subtitle_focus=req.subtitle_focus,
        )

        _UPGRADE_THRESHOLD = float(os.environ.get("AUTO_UPGRADE_THRESHOLD", "8.5"))
        _score = result.get("quality_score", 0.0)
        _model = result.get("model_used", "")
        if (
            result.get("status") == "success"
            and 0 < _score < _UPGRADE_THRESHOLD
            and "haiku" in _model.lower()
        ):
            _upgraded = await _rewrite_tour(
                tour, idx=0, total=1,
                brand_rules=brand_rules,
                seo=seo_data,
                model_tier="sonnet",
                subtitle_focus=req.subtitle_focus,
            )
            if _upgraded.get("quality_score", 0.0) > _score:
                result = _upgraded

        version_id = None
        if result.get("status") == "success" and result.get("generated"):
            generated = result["generated"]
            status = "approved" if result.get("quality_score", 0.0) >= 7.0 else "pending"
            is_branded = result.get("is_branded", True)
            og_tags_val = json.dumps({} if is_branded else {"unbranded": True})
            version_id = await conn.fetchval("""
                INSERT INTO silver_aa_internal.generated_content (
                    tour_id, tenant_id, version_num,
                    aa_name, aa_subtitle, aa_summary,
                    aa_description, aa_highlights, aa_itineraries,
                    seo_title, seo_meta, seo_keywords_used,
                    model_editorial, status, og_tags
                ) VALUES (
                    $1::uuid, $2::uuid,
                    COALESCE((SELECT MAX(version_num) + 1
                    FROM silver_aa_internal.generated_content
                    WHERE tour_id = $1::uuid), 1),
                    $3, $4, $5, $6, $7::jsonb, $8,
                    $9, $10, $11::jsonb, $12, $13::content_status_enum, $14::jsonb
                ) RETURNING id
            """,
                req.tour_id, tenant_uuid,
                (generated.get("name") or "")[:500],
                (generated.get("subtitle") or "")[:500],
                generated.get("summary"),
                generated.get("description", ""),
                json.dumps(generated.get("highlights", [])),
                generated.get("itineraries", ""),
                (generated.get("seo_title") or "")[:70],
                (generated.get("seo_meta") or "")[:170],
                json.dumps(generated.get("seo_keywords_used", [])),
                result.get("model_used", ""),
                status,
                og_tags_val,
            )

        if version_id and result.get("quality_score") is not None:
            _sub = result.get("sub_scores", {})
            _fc  = result.get("failure_codes", [])
            await conn.execute("""
                INSERT INTO silver_aa_internal.quality_scores (
                    generated_content_id, tour_id, tenant_id,
                    score_overall, score_brand, score_seo,
                    score_structure, score_quality,
                    passed_count, failed_count, failure_codes,
                    validator_fn_version, evaluated_at
                ) VALUES (
                    $1::uuid, $2::uuid, $3::uuid,
                    $4, $5, $6, $7, $8, $9, $10, $11::jsonb, 'v2', NOW()
                ) ON CONFLICT DO NOTHING
            """,
                version_id, req.tour_id,
                "00000000-0000-0000-0000-000000000001",
                float(result.get("quality_score", 0.0)),
                float(_sub.get("brand", 0.0)),
                float(_sub.get("seo", 0.0)),
                float(_sub.get("structure", 0.0)),
                float(_sub.get("quality", 0.0)),
                int(result.get("passed_count", 0)),
                int(result.get("failed_count", 0)),
                json.dumps(_fc),
            )

        status = "approved" if result.get("quality_score", 0.0) >= 7.0 else "pending"
        if version_id and status == "approved":
            from services.export.handler import process_export
            try:
                await process_export(str(version_id))
            except Exception as _exp_err:
                logger.error("export_failed", tour_id=req.tour_id, error=str(_exp_err))

        cost_usd    = float(result.get("cost_usd") or 0.0)
        tokens_in   = int(result.get("input_tokens") or 0)
        tokens_out  = int(result.get("output_tokens") or 0)
        tour_passed = float(result.get("quality_score") or 0.0) >= 7.0
        model_name  = result.get("model_used") or None
        if isinstance(model_name, str) and not model_name:
            model_name = None
        actual_provider = "openai" if model_name and "gpt" in model_name.lower() else "bedrock"
        if cost_usd > 0 or tokens_in > 0:
            await conn.execute("""
                UPDATE shared.pipeline_runs
                SET cost_usd      = COALESCE(cost_usd, 0)      + $1,
                    tokens_input  = COALESCE(tokens_input, 0)  + $2,
                    tokens_output = COALESCE(tokens_output, 0) + $3,
                    tours_failed  = tours_failed + $4,
                    llm_model     = COALESCE($6, llm_model),
                    llm_provider  = $7,
                    step_name     = 'content_generation'
                WHERE batch_id = $5::uuid
            """,
                cost_usd, tokens_in, tokens_out,
                0 if tour_passed else 1,
                req.batch_id, model_name, actual_provider,
            )

        return {
            "tour_id":       req.tour_id,
            "batch_id":      req.batch_id,
            "version_id":    str(version_id) if version_id else None,
            "status":        result.get("status"),
            "quality_score": result.get("quality_score"),
            "generated":     result.get("generated"),
            "cost_usd":      result.get("cost_usd"),
            "model_used":    result.get("model_used"),
        }
    finally:
        await conn.close()


async def _run_tour_safe(tour_req: TourRunRequest) -> None:
    async with _pipeline_semaphore:
        last_exc: Exception | None = None
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(2 ** attempt)
            try:
                await _execute_run_tour(tour_req)
                return
            except Exception as exc:
                last_exc = exc
                logger.warning("run_tour_attempt_failed", tour_id=tour_req.tour_id,
                               attempt=attempt + 1, error=str(exc))
        logger.error("background_run_tour_failed", tour_id=tour_req.tour_id,
                     batch_id=tour_req.batch_id, error=str(last_exc))
        try:
            conn = await asyncpg.connect(os.environ["DATABASE_URL"])
            await conn.execute(
                "UPDATE shared.pipeline_runs SET status='failed', error_message=$2 "
                "WHERE batch_id=$1::uuid AND status='ingesting'",
                tour_req.batch_id, str(last_exc)[:1000],
            )
            await conn.close()
        except Exception as db_exc:
            logger.error("failed_to_mark_pipeline_failed", error=str(db_exc))


@router.post("/run-tour")
async def run_tour(req: TourRunRequest, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    return await _execute_run_tour(req)


# ── POST /admin/upload-url ────────────────────────────────────────────────────

@router.post("/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(body: UploadUrlRequest, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    import uuid as _uuid
    import re as _re
    tenant_id = "00000000-0000-0000-0000-000000000001"
    bucket    = os.environ.get("BRONZE_BUCKET", "aa-cis-bronze-867490540162")
    safe_filename = _re.sub(r'[^a-zA-Z0-9._-]', '_', body.filename)
    s3_key    = f"raw-inbox/{tenant_id}/{_uuid.uuid4()}_{safe_filename}"
    s3 = _boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-1"))
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": s3_key, "ContentType": body.content_type,
                "Metadata": {"seo-mode": body.seo_mode}},
        ExpiresIn=300,
    )
    return UploadUrlResponse(upload_url=upload_url, s3_key=s3_key, bucket=bucket)


# ── POST /admin/ingest-s3 ─────────────────────────────────────────────────────

@router.post("/ingest-s3")
async def ingest_s3(
    req: IngestS3Request,
    background_tasks: BackgroundTasks,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    from services.ingestion.handler import process_file

    result = await process_file(req.bucket, req.s3_key, seo_mode=req.seo_mode)
    if result.get("status") == "skipped_duplicate":
        return {"status": "duplicate", "batch_id": None, "tour_count": 0}

    batch_id = result.get("source_id")
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tour_id FROM silver_aa_internal.raw_tours WHERE batch_id = $1::uuid",
            batch_id,
        )

    sf_threshold = int(os.environ.get("SF_BATCH_THRESHOLD", "15"))
    tour_ids = [str(r["tour_id"]) for r in rows]

    if len(tour_ids) > sf_threshold:
        sf_arn = os.environ.get("STEP_FUNCTIONS_ARN", "")
        if sf_arn:
            sfn = _boto3.client("stepfunctions", region_name=os.environ.get("AWS_REGION", "us-west-1"))
            try:
                sfn.start_execution(
                    stateMachineArn=sf_arn,
                    name=f"pipeline-{batch_id}",
                    input=json.dumps({
                        "tour_ids": tour_ids,
                        "tenant_id": "00000000-0000-0000-0000-000000000001",
                        "batch_id": str(batch_id),
                        "seo_mode": req.seo_mode,
                        "model_tier": req.model_tier,
                    }),
                )
                return {"status": "sf_triggered", "batch_id": batch_id, "tour_count": len(rows)}
            except Exception as sf_err:
                logger.error("sf_start_execution_failed", error=str(sf_err), batch_id=batch_id)

    for row in rows:
        tour_req = TourRunRequest(
            tour_id=str(row["tour_id"]),
            batch_id=batch_id,
            tenant_id="00000000-0000-0000-0000-000000000001",
            seo_mode=req.seo_mode,
            model_tier=req.model_tier,
            subtitle_focus=req.subtitle_focus,
        )
        background_tasks.add_task(_run_tour_safe, tour_req)

    return {"status": "triggered", "batch_id": batch_id, "tour_count": len(rows)}


# ── GET /admin/metrics ────────────────────────────────────────────────────────

@router.get("/metrics")
async def get_pipeline_metrics(
    request: Request,
    days: int = 7,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    tenant_slug = "aa_internal"

    async with pool.acquire() as conn:
        daily = await conn.fetch("""
            SELECT
                DATE(started_at)              AS day,
                COUNT(*)                      AS runs,
                COALESCE(SUM(tours_total),0)  AS tours,
                COALESCE(SUM(tours_passed),0) AS passed,
                COALESCE(SUM(tours_hitl),0)   AS hitl,
                COALESCE(SUM(tours_failed),0) AS failed,
                COALESCE(ROUND(SUM(cost_usd)::numeric,4), 0) AS cost
            FROM shared.pipeline_runs
            WHERE started_at >= NOW() - ($1 || ' days')::interval
              AND status != 'ingesting'
            GROUP BY DATE(started_at)
            ORDER BY day ASC
        """, str(days))

        cost_by_model = await conn.fetch("""
            SELECT
                CASE
                    WHEN COALESCE(llm_model,'') LIKE '%haiku%'  THEN 'claude-haiku-4-5'
                    WHEN COALESCE(llm_model,'') LIKE '%sonnet%' THEN 'claude-sonnet-4-5'
                    WHEN COALESCE(llm_model,'') LIKE '%gpt-4%'  THEN 'gpt-4.1'
                    ELSE 'claude-haiku-4-5'
                END                              AS model,
                COUNT(*)                         AS batches,
                COALESCE(SUM(cost_usd), 0)       AS total_cost
            FROM shared.pipeline_runs
            WHERE cost_usd > 0 AND status != 'ingesting'
            GROUP BY 1 ORDER BY total_cost DESC
        """)

        models = await conn.fetch(f"""
            SELECT
                CASE
                    WHEN COALESCE(gc.model_editorial,'') LIKE '%haiku%'  THEN 'claude-haiku-4-5'
                    WHEN COALESCE(gc.model_editorial,'') LIKE '%sonnet%' THEN 'claude-sonnet-4-5'
                    WHEN COALESCE(gc.model_editorial,'') LIKE '%gpt-4%'  THEN 'gpt-4.1'
                    ELSE 'claude-haiku-4-5'
                END                                          AS model,
                COUNT(*)                                     AS calls,
                ROUND(AVG(qs.score_overall)::numeric, 1)     AS avg_score
            FROM silver_{tenant_slug}.generated_content gc
            LEFT JOIN silver_{tenant_slug}.quality_scores qs
                ON qs.generated_content_id = gc.id
            GROUP BY 1 ORDER BY calls DESC
        """)

        avg_cost_per_run = await conn.fetchval("""
            SELECT ROUND(SUM(cost_usd) / NULLIF(COUNT(*), 0)::numeric, 6)
            FROM shared.pipeline_runs
            WHERE cost_usd > 0 AND status != 'ingesting'
        """)

        published_count = await conn.fetchval("""
            SELECT COUNT(*) FROM gold_aa_internal.published_tours
            WHERE tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
        """)

        tenant_rewrite_count = await conn.fetchval(
            "SELECT COUNT(*) FROM gold_aa_internal.tenant_tour_versions"
        )

        tenant_breakdown = await conn.fetch("""
            SELECT t.slug, t.plan_tier, COUNT(ttv.id) AS rewrite_count
            FROM gold_aa_internal.tenant_tour_versions ttv
            JOIN shared.tenants t ON t.tenant_id = ttv.tenant_id
            GROUP BY t.slug, t.plan_tier ORDER BY rewrite_count DESC
        """)

        daily_rewrites = await conn.fetch("""
            SELECT DATE(created_at) AS day, COUNT(*) AS rewrites
            FROM gold_aa_internal.tenant_tour_versions
            WHERE created_at >= NOW() - ($1 || ' days')::interval
            GROUP BY DATE(created_at)
        """, str(days))

        llm_calls = await conn.fetchval(
            f"SELECT COUNT(*) FROM silver_{tenant_slug}.generated_content"
        )

        last_run = await conn.fetchrow("""
            SELECT tours_total, tours_passed, tours_failed, started_at, completed_at,
                   EXTRACT(EPOCH FROM (completed_at - started_at)) AS duration_sec
            FROM shared.pipeline_runs
            WHERE completed_at IS NOT NULL
            ORDER BY started_at DESC LIMIT 1
        """)

        health_rows = await conn.fetch("""
            SELECT endpoint,
                   COUNT(*)                                             AS calls,
                   ROUND(AVG(response_ms)::numeric, 0)                 AS avg_ms,
                   SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) AS errors,
                   SUM(CASE WHEN status_code = 429  THEN 1 ELSE 0 END) AS rate_limited,
                   MAX(called_at)                                       AS last_call
            FROM shared.tenant_api_usage
            WHERE called_at >= NOW() - INTERVAL '1 hour'
            GROUP BY endpoint ORDER BY calls DESC
        """)

    ENDPOINT_SERVICE_MAP = {
        "/v1/pipeline/run":         "Step Functions Pipeline",
        "/v1/pipeline/run-tour":    "Content Generation",
        "/admin/run-tour":          "Content Generation",
        "/v1/pipeline/review-queue": "Validation Lambda",
        "/v1/tours":                "Export / Catalog API",
        "/v1/pipeline/upload-url":  "Ingestion Lambda",
        "/admin/upload-url":        "Ingestion Lambda",
        "/admin/metrics":           "Admin Metrics API",
        "/v1/pipeline/sources":     "Source Tracker",
        "/health":                  "API Health Check",
    }

    import re as _re
    pipeline_health = []
    seen_services: set = set()
    for r in health_rows:
        ep = r["endpoint"]
        ep_norm = _re.sub(r'/[0-9a-f-]{8,}', '/{id}', ep)
        service = ENDPOINT_SERVICE_MAP.get(ep, ENDPOINT_SERVICE_MAP.get(ep_norm, ep))
        if service in seen_services:
            continue
        seen_services.add(service)
        errors = int(r["errors"] or 0)
        calls  = int(r["calls"] or 0)
        avg_ms = float(r["avg_ms"] or 0)
        status = "healthy" if errors == 0 else ("degraded" if errors / max(calls, 1) < 0.1 else "down")
        pipeline_health.append({"name": service, "status": status,
                                 "latency": f"{avg_ms:.0f}ms", "errors": errors, "calls": calls})

    CORE_SERVICES = ["Ingestion Lambda", "Step Functions Pipeline",
                     "Content Generation", "Validation Lambda", "Export / Catalog API"]
    for svc in CORE_SERVICES:
        if svc not in seen_services:
            pipeline_health.append({"name": svc, "status": "idle",
                                    "latency": "—", "errors": 0, "calls": 0})

    cost_map = {r["model"]: float(r["total_cost"]) for r in cost_by_model}
    seen_models: set = set()
    model_usage = []
    for r in models:
        model      = r["model"]
        calls      = int(r["calls"])
        total_cost = cost_map.get(model, 0.0)
        model_usage.append({
            "model":         model,
            "calls":         calls,
            "avg_score":     float(r["avg_score"]) if r["avg_score"] else None,
            "total_cost":    round(total_cost, 4),
            "cost_per_call": round(total_cost / calls, 6) if calls > 0 else 0.0,
        })
        seen_models.add(model)
    for r in cost_by_model:
        if r["model"] not in seen_models:
            total_cost = float(r["total_cost"])
            model_usage.append({
                "model": r["model"], "calls": int(r["batches"]),
                "avg_score": None, "total_cost": round(total_cost, 4), "cost_per_call": 0.0,
            })

    rewrite_by_day = {str(r["day"]): int(r["rewrites"]) for r in daily_rewrites}
    return {
        "daily_runs": [
            {
                "date":     str(r["day"]),
                "runs":     r["runs"],
                "tours":    r["tours"],
                "passed":   r["passed"],
                "hitl":     r["hitl"],
                "failed":   r["failed"],
                "cost":     float(r["cost"]),
                "rewrites": rewrite_by_day.get(str(r["day"]), 0),
            }
            for r in daily
        ],
        "model_usage": model_usage,
        "avg_cost_per_run": float(avg_cost_per_run) if avg_cost_per_run else 0.0,
        "last_run": {
            "tours_total":  last_run["tours_total"]  if last_run else 0,
            "tours_passed": last_run["tours_passed"] if last_run else 0,
            "tours_failed": last_run["tours_failed"] if last_run else 0,
            "duration_sec": float(last_run["duration_sec"]) if last_run and last_run["duration_sec"] else 0,
        } if last_run else None,
        "pipeline_health": pipeline_health,
        "published_count":       int(published_count or 0),
        "tenant_rewrite_count":  int(tenant_rewrite_count or 0),
        "llm_calls":             int(llm_calls or 0),
        "content_summary": {
            "total_published_master":    int(published_count or 0),
            "total_tenant_rewrites":     int(tenant_rewrite_count or 0),
            "total_content_all_tenants": int(published_count or 0) + int(tenant_rewrite_count or 0),
            "tenant_breakdown": [
                {"slug": r["slug"], "plan_tier": r["plan_tier"], "rewrite_count": int(r["rewrite_count"])}
                for r in tenant_breakdown
            ],
        },
    }


# ── GET /admin/metrics/seo ────────────────────────────────────────────────────

@router.get("/metrics/seo")
async def get_seo_metrics(request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        top_keywords = await conn.fetch("""
            SELECT keyword_search, top_keywords, fetched_at
            FROM silver_aa_internal.seo_context
            ORDER BY fetched_at DESC LIMIT 20
        """)
        total_tours = await conn.fetchval(
            "SELECT COUNT(*) FROM gold_aa_internal.published_tours "
            "WHERE tenant_id = '00000000-0000-0000-0000-000000000001'::uuid"
        )
        seo_covered = await conn.fetchval("""
            SELECT COUNT(DISTINCT pt.tour_id)
            FROM gold_aa_internal.published_tours pt
            JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE pt.tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
              AND EXISTS (
                  SELECT 1 FROM silver_aa_internal.seo_context sc WHERE sc.tour_id = rt.tour_id
              )
        """)
        countries = await conn.fetch("""
            SELECT rt.country, COUNT(sc.id) as count
            FROM silver_aa_internal.seo_context sc
            JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = sc.tour_id
            WHERE rt.country IS NOT NULL
            GROUP BY rt.country ORDER BY count DESC
        """)

    redis = request.app.state.redis
    cache_stats: dict = {"hit_rate": "N/A", "keys": 0}
    try:
        info = await redis.info("stats")
        hits   = int(info.get("keyspace_hits", 0))
        misses = int(info.get("keyspace_misses", 0))
        total  = hits + misses
        cache_stats["hit_rate"] = f"{round(hits/total*100, 1)}%" if total > 0 else "0%"
        cache_stats["hits"]     = hits
        cache_stats["misses"]   = misses
        db_info = await redis.info("keyspace")
        cache_stats["keys"] = sum(
            int(v.split(",")[0].split("=")[1])
            for v in db_info.values() if isinstance(v, str) and "keys=" in v
        )
    except Exception:
        pass

    import json as _j
    keyword_counts: dict = {}
    for row in top_keywords:
        try:
            kw_data = row["top_keywords"]
            if isinstance(kw_data, str):
                kw_data = _j.loads(kw_data)
            items = kw_data if isinstance(kw_data, list) else (kw_data.get("top_keywords") or [] if isinstance(kw_data, dict) else [])
            for item in items[:5]:
                kw = item.get("keyword") if isinstance(item, dict) else str(item)
                if kw:
                    keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
        except Exception:
            pass

    top_kw = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    return {
        "total_tours":  total_tours,
        "seo_covered":  seo_covered,
        "coverage_pct": round(seo_covered / total_tours * 100, 1) if total_tours else 0,
        "countries":    [{"country": dict(r)["country"], "count": dict(r)["count"]} for r in countries],
        "top_keywords": [{"keyword": k, "count": v} for k, v in top_kw],
        "cache":        cache_stats,
    }


# ── GET /admin/metrics/library ────────────────────────────────────────────────

@router.get("/metrics/library")
async def get_library_metrics(request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        by_country = await conn.fetch("""
            SELECT rt.country,
                   COUNT(pt.id)                            AS total,
                   ROUND(AVG(pt.quality_score)::numeric,2) AS avg_score,
                   MAX(pt.published_at)                    AS last_published
            FROM gold_aa_internal.published_tours pt
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE pt.tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
            GROUP BY rt.country ORDER BY total DESC
        """)
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*)                                  AS total,
                ROUND(AVG(quality_score)::numeric, 2)     AS avg_score,
                COUNT(CASE WHEN published_at >= NOW() - INTERVAL '30 days' THEN 1 END) AS published_last_30d,
                COUNT(CASE WHEN published_at < NOW() - INTERVAL '180 days' THEN 1 END) AS stale_count
            FROM gold_aa_internal.published_tours
            WHERE tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
        """)
        score_dist = await conn.fetch("""
            SELECT
                CASE
                    WHEN quality_score >= 9 THEN '9-10'
                    WHEN quality_score >= 8 THEN '8-9'
                    WHEN quality_score >= 7 THEN '7-8'
                    ELSE '<7'
                END AS range,
                COUNT(*) AS count
            FROM gold_aa_internal.published_tours
            WHERE tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
            GROUP BY range ORDER BY range DESC
        """)

    return {
        "total":              stats["total"],
        "avg_score":          float(stats["avg_score"] or 0),
        "published_last_30d": stats["published_last_30d"],
        "stale_count":        stats["stale_count"],
        "by_country":         [dict(r) for r in by_country],
        "score_distribution": [dict(r) for r in score_dist],
    }


# ── GET /admin/metrics/spot-workers ──────────────────────────────────────────

@router.get("/metrics/spot-workers")
async def get_spot_workers(request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    ecs = _boto3.client("ecs", region_name=os.environ.get("AWS_REGION", "us-west-1"))
    cluster = os.environ.get("ECS_CLUSTER", "aa-cis-dev-cluster")
    try:
        task_arns = ecs.list_tasks(cluster=cluster, desiredStatus="RUNNING").get("taskArns", [])
        spot_tasks, on_demand_tasks = [], []
        if task_arns:
            for t in ecs.describe_tasks(cluster=cluster, tasks=task_arns).get("tasks", []):
                cap  = t.get("capacityProviderName", "FARGATE")
                info = {
                    "task_id":  t["taskArn"].split("/")[-1][:12],
                    "status":   t.get("lastStatus", "UNKNOWN"),
                    "cpu":      t.get("cpu", "256"),
                    "memory":   t.get("memory", "512"),
                    "started":  str(t.get("startedAt", "")),
                    "capacity": cap,
                }
                (spot_tasks if cap == "FARGATE_SPOT" else on_demand_tasks).append(info)
        spot_count  = len(spot_tasks)
        total_count = len(task_arns)
        return {
            "total_tasks":     total_count,
            "spot_tasks":      spot_count,
            "on_demand_tasks": len(on_demand_tasks),
            "spot_pct":        round(spot_count / total_count * 100) if total_count else 0,
            "saving_per_hr":   round(spot_count * 0.04048 * 0.7, 4),
            "tasks":           spot_tasks + on_demand_tasks,
        }
    except Exception as e:
        return {"total_tasks": 0, "spot_tasks": 0, "on_demand_tasks": 0,
                "spot_pct": 0, "saving_per_hr": 0, "tasks": [], "error": str(e)}


# ── GET/POST /admin/brand-identity ────────────────────────────────────────────

@router.get("/brand-identity")
async def get_brand_identity(request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    import json as _json_br
    pool = request.app.state.pool
    tenant_id = "00000000-0000-0000-0000-000000000001"
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT system_prompt, style_guide, forbidden_words, version, updated_at, created_at
            FROM shared.tenant_brand_rules
            WHERE tenant_id = $1 AND is_active = true
            ORDER BY version DESC LIMIT 1
        """, tenant_id)
        if not row:
            return {"configured": False, "system_prompt": None,
                    "style_guide": None, "forbidden_words": [], "history": []}
        history_rows = await conn.fetch("""
            SELECT version, is_active, system_prompt, style_guide,
                   forbidden_words, updated_at, created_at
            FROM shared.tenant_brand_rules WHERE tenant_id = $1 ORDER BY version DESC
        """, tenant_id)

    def parse_fw(fw):
        if fw is None: return []
        if isinstance(fw, list): return fw
        try: return _json_br.loads(fw)
        except Exception: return []

    history = [{
        "version":         h["version"],
        "is_active":       h["is_active"],
        "system_prompt":   h["system_prompt"] or "",
        "style_guide":     h["style_guide"] or "",
        "forbidden_words": parse_fw(h["forbidden_words"]),
        "updated_at": h["updated_at"].isoformat() if h["updated_at"] else None,
        "created_at": h["created_at"].isoformat() if h["created_at"] else None,
    } for h in history_rows]
    return {
        "configured":      True,
        "system_prompt":   row["system_prompt"],
        "style_guide":     row["style_guide"],
        "forbidden_words": parse_fw(row["forbidden_words"]),
        "version":         row["version"],
        "updated_at":      row["updated_at"].isoformat() if row["updated_at"] else None,
        "history":         history,
    }


@router.post("/brand-identity")
async def update_brand_identity(
    body: BrandIdentityUpdate,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    import json as _json
    pool = request.app.state.pool
    tenant_id = "00000000-0000-0000-0000-000000000001"
    async with pool.acquire() as conn:
        current = await conn.fetchval("""
            SELECT COALESCE(MAX(version), 0) FROM shared.tenant_brand_rules WHERE tenant_id = $1
        """, tenant_id)
        await conn.execute(
            "UPDATE shared.tenant_brand_rules SET is_active = false WHERE tenant_id = $1", tenant_id
        )
        await conn.execute("""
            INSERT INTO shared.tenant_brand_rules
                (tenant_id, system_prompt, style_guide, forbidden_words, version, is_active, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, true, NOW())
        """, tenant_id, body.system_prompt, body.style_guide,
            _json.dumps(body.forbidden_words or []), current + 1)
    return {"status": "updated", "version": current + 1}


@router.post("/brand-identity/upload")
async def upload_brand_file(request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    import uuid as _uuid2
    import re as _re2
    tenant_id    = "00000000-0000-0000-0000-000000000001"
    body         = await request.json()
    filename     = body.get("filename", "brand.pdf")
    content_type = body.get("content_type", "application/pdf")
    safe_name    = _re2.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    s3_key       = f"brand-identity/{tenant_id}/{_uuid2.uuid4()}_{safe_name}"
    bucket       = os.environ.get("BRONZE_BUCKET", "aa-cis-bronze-867490540162")
    s3 = _boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-1"))
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": s3_key, "ContentType": content_type},
        ExpiresIn=300,
    )
    return {"upload_url": upload_url, "s3_key": s3_key}


# ── GET /admin/billing ────────────────────────────────────────────────────────

@router.get("/billing")
async def get_admin_billing(
    request: Request,
    x_admin_secret: str = Header(None),
    tenant_id: str = "00000000-0000-0000-0000-000000000001",
):
    """Admin billing view — defaults to aa_internal; pass ?tenant_id= for a specific tenant."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                v.tenant_name, v.plan_tier, v.billing_month,
                v.tours_quota_monthly, v.api_calls_quota_monthly,
                v.price_usd_monthly,
                v.tours_rewritten, v.api_calls_used,
                v.quota_tours_pct, v.quota_calls_pct,
                v.tours_overage, v.overage_usd, v.llm_cost_usd,
                v.overage_rate_usd_per_tour
            FROM shared.v_tenant_monthly_usage v
            WHERE v.tenant_id = $1::uuid
        """, tenant_id)

        activity = await conn.fetch("""
            SELECT ttv.id, ttv.created_at, ttv.status, ttv.edit_source,
                   pt.aa_name, rt.country
            FROM gold_aa_internal.tenant_tour_versions ttv
            JOIN gold_aa_internal.published_tours pt ON pt.id = ttv.published_tour_id
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE ttv.tenant_id = $1::uuid
            ORDER BY ttv.created_at DESC LIMIT 5
        """, tenant_id)

    if not row:
        return {
            "plan_tier": "starter", "tours_quota_monthly": 50,
            "api_calls_quota_monthly": 5000, "price_usd_monthly": 299.0,
            "tours_rewritten": 0, "api_calls_used": 0,
            "quota_tours_pct": 0.0, "quota_calls_pct": 0.0,
            "tours_overage": 0, "overage_usd": 0.0,
            "llm_cost_usd": 0.0, "overage_rate_usd_per_tour": 4.0,
            "activity": [],
        }

    return {
        **{k: (float(v) if hasattr(v, '__float__') and not isinstance(v, int) else v)
           for k, v in dict(row).items() if k != "billing_month"},
        "billing_month": str(row["billing_month"])[:7] if row["billing_month"] else None,
        "activity": [
            {
                "id": str(a["id"]),
                "created_at": a["created_at"].isoformat(),
                "status": a["status"],
                "edit_source": a["edit_source"],
                "tour_name": a["aa_name"],
                "country": a["country"],
            }
            for a in activity
        ],
    }
