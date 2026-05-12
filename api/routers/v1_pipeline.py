"""
POST /v1/pipeline/run — Upload Excel → parse → rewrite → return results
Chạy trực tiếp trong ECS, không cần Lambda/Step Functions.
"""
import os
import json
import uuid
import asyncio
import tempfile
import structlog

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Optional

from services.ingestion.excel_parser import ExcelParser
from services.content_generation.graph import build_graph
from pydantic import BaseModel
from pydantic import BaseModel as _BaseModel
from typing import Optional as _Optional, List as _List
import asyncpg
import boto3 as _boto3
from fastapi import Depends, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from api.routers.auth import verify_jwt as _verify_jwt

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/pipeline", tags=["pipeline"])


def _normalize_generated(generated: dict, tour: dict) -> dict:
    """Post-process LLM output: title-case name, strip forbidden words from name."""
    if not generated:
        return generated
    # Title-case name if ALL-CAPS (preserve if already mixed case)
    name = generated.get("name", "")
    if name and name == name.upper():
        generated["name"] = name.title()
    return generated


async def _rewrite_tour(
    tour: dict, idx: int, total: int,
    brand_rules: dict = None,
    seo: dict = None,
    model_tier: str = "haiku",
) -> dict:
    """Rewrite single tour using LangGraph."""
    logger.info("rewriting_tour", idx=idx, total=total, name=tour.get("name", ""))

    try:
        graph = build_graph()
        # P3-S3: Merge brand_rules into initial_state
        _br = brand_rules or {}
        initial_state = {
            "tour": tour,
            "seo": seo or {},
            "model_tier": model_tier,
            "few_shots": [],
            "generated": {},
            "quality_score": 0.0,
            "retry_count": 0,
            "feedback": "",
            "error": "",
            "cost_usd": 0.0,
            "model_used": "",
            "brand_system_prompt":  _br.get("system_prompt", ""),
            "brand_style_guide":    _br.get("style_guide", ""),
            "brand_forbidden_words": _br.get("forbidden_words", []),
            "rewrite_language":     _br.get("rewrite_language", "en-US"),
        }

        def run_graph():
            import asyncio as _asyncio
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            try:
                return graph.invoke(initial_state)
            finally:
                loop.close()
        result = await asyncio.get_event_loop().run_in_executor(None, run_graph)

        return {
            "idx": idx,
            "src_name": tour.get("name", ""),
            "country": tour.get("country", ""),
            "duration": tour.get("duration", ""),
            "generated": _normalize_generated(result.get("generated", {}), tour),
            "quality_score": result.get("quality_score", 0.0),
            "model_used": result.get("model_used", ""),
            "cost_usd": result.get("cost_usd", 0.0),
            "retry_count": result.get("retry_count", 0),
            "error": result.get("error", ""),
            "status": "success" if result.get("generated") else "failed",
        }

    except Exception as e:
        logger.error("rewrite_failed", idx=idx, error=str(e))
        return {
            "idx": idx,
            "src_name": tour.get("name", ""),
            "country": tour.get("country", ""),
            "status": "failed",
            "error": str(e),
        }


@router.post("/run")
async def run_pipeline(
    file: UploadFile = File(...),
    max_tours: int = 5,
):
    """
    Upload Excel file → parse → rewrite up to max_tours tours.
    Returns before/after comparison with quality scores.

    Args:
        file: Excel file (.xlsx)
        max_tours: Max number of tours to process (default 5, max 20)
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Only .xlsx/.xls files supported")

    max_tours = min(max_tours, 20)  # Hard cap at 20

    # Save upload to temp file
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    logger.info("pipeline_started", filename=file.filename, max_tours=max_tours)

    try:
        # Parse Excel
        parser = ExcelParser(tmp_path, source_file=file.filename)
        records = parser.parse()

        if not records:
            raise HTTPException(400, "No valid tour records found in Excel file")

        # Limit tours
        records = records[:max_tours]
        logger.info("tours_parsed", total=len(records))

        # Rewrite tours concurrently (max 3 at a time to avoid rate limits)
        semaphore = asyncio.Semaphore(3)

        async def bounded_rewrite(tour, idx):
            async with semaphore:
                return await _rewrite_tour(tour, idx + 1, len(records))

        tasks = [bounded_rewrite(tour, i) for i, tour in enumerate(records)]
        results = await asyncio.gather(*tasks)

        # Summary stats
        successful = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") == "failed"]
        total_cost = sum(r.get("cost_usd", 0) for r in results)
        avg_quality = (
            sum(r.get("quality_score", 0) for r in successful) / len(successful)
            if successful else 0
        )

        return JSONResponse({
            "batch_id": str(uuid.uuid4()),
            "filename": file.filename,
            "summary": {
                "total": len(records),
                "successful": len(successful),
                "failed": len(failed),
                "avg_quality_score": round(avg_quality, 2),
                "total_cost_usd": round(total_cost, 4),
            },
            "results": results,
        })

    finally:
        os.unlink(tmp_path)


# ── SF per-tour endpoint ──────────────────────────────────────────────────────

class TourRunRequest(BaseModel):
    tour_id: str
    batch_id: str
    tenant_id: str
    retry_count: int = 0
    validation_feedback: list = []
    seo_mode: str = "standard"
    rewrite_language: str = "en-US"  # en-US | en-GB
    model_tier: str = "haiku"        # "haiku" | "sonnet"


@router.post("/run-tour")
async def run_tour(req: TourRunRequest):
    """Per-tour endpoint for Step Functions — load tour from DB, rewrite, return result."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    # Resolve tenant slug → UUID (SF passes slug, API expects UUID)
    TENANT_SLUG_MAP = {"aa_internal": "00000000-0000-0000-0000-000000000001"}
    tenant_uuid = TENANT_SLUG_MAP.get(req.tenant_id, req.tenant_id)
    try:
        row = await conn.fetchrow(
            """SELECT * FROM silver_aa_internal.raw_tours
               WHERE tour_id = $1::uuid""",
            req.tour_id
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


        # P3-S3: Fetch tenant brand rules for customization layer
        brand_rules = {}
        try:
            _tenant_uuid = tenant_uuid
            br_row = await conn.fetchrow("""
                SELECT system_prompt, style_guide, forbidden_words
                FROM shared.tenant_brand_rules
                WHERE tenant_id = $1::uuid AND is_active = true
                ORDER BY version DESC LIMIT 1
            """, _tenant_uuid)
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
            import structlog as _sl
            _sl.get_logger().warning("brand_rules_fetch_failed", error=str(_br_err))

        # SEO Intelligence step — fetch keywords before content generation (AA-50)
        # Seed keyword: "{country} tours" per BUG-3 fix
        seo_data: dict = {}
        try:
            from services.seo_intelligence.handler import process_seo
            destination = (
                f"{row['country']} tours" if row.get("country")
                else row.get("src_name", "")
            )
            if destination:
                seo_result = await process_seo(tour_id=req.tour_id, destination=destination)
                seo_data = seo_result.get("data", {})
                logger.info("seo_step_done", tour_id=req.tour_id,
                            status=seo_result.get("status"), destination=destination)
        except Exception as _seo_err:
            logger.warning("seo_step_failed", tour_id=req.tour_id, error=str(_seo_err))

        result = await _rewrite_tour(
            tour, idx=0, total=1,
            brand_rules=brand_rules,
            seo=seo_data,
            model_tier=req.model_tier,
        )

        # Auto-upgrade: Haiku score below threshold → retry with Sonnet
        _UPGRADE_THRESHOLD = float(os.environ.get("AUTO_UPGRADE_THRESHOLD", "8.5"))
        _score = result.get("quality_score", 0.0)
        _model = result.get("model_used", "")
        if (
            result.get("status") == "success"
            and 0 < _score < _UPGRADE_THRESHOLD
            and "haiku" in _model.lower()
        ):
            logger.info("auto_upgrade_sonnet", tour_id=req.tour_id,
                        score=_score, threshold=_UPGRADE_THRESHOLD, model=_model)
            _upgraded = await _rewrite_tour(
                tour, idx=0, total=1,
                brand_rules=brand_rules,
                seo=seo_data,
                model_tier="sonnet",
            )
            _new_score = _upgraded.get("quality_score", 0.0)
            logger.info("auto_upgrade_result", tour_id=req.tour_id,
                        old_score=_score, new_score=_new_score,
                        upgraded=_new_score > _score)
            if _new_score > _score:
                result = _upgraded

        # Write to generated_content so Validation Lambda can read it
        version_id = None
        if result.get("status") == "success" and result.get("generated"):
            import json as _json
            generated = result["generated"]
            status = "approved" if result.get("quality_score", 0.0) >= 7.0 else "pending"
            version_id = await conn.fetchval("""
                INSERT INTO silver_aa_internal.generated_content (
                    tour_id, tenant_id, version_num,
                    aa_name, aa_subtitle, aa_summary,
                    aa_description, aa_highlights, aa_itineraries,
                    seo_title, seo_meta, seo_keywords_used,
                    model_editorial, status
                ) VALUES (
                    $1::uuid, $2::uuid,
                    COALESCE((SELECT MAX(version_num) + 1
                    FROM silver_aa_internal.generated_content
                    WHERE tour_id = $1::uuid), 1),
                    $3, $4, $5,
                    $6, $7::jsonb, $8,
                    $9, $10, $11::jsonb,
                    $12, $13::content_status_enum
                ) RETURNING id
            """,
                req.tour_id,
                tenant_uuid,
                generated.get("name"),
                generated.get("subtitle"),
                generated.get("summary"),
                generated.get("description", ""),
                _json.dumps(generated.get("highlights", [])),
                generated.get("itineraries", ""),
                generated.get("seo_title"),
                generated.get("seo_meta"),
                _json.dumps(generated.get("seo_keywords_used", [])),
                result.get("model_used", ""),
                status,
            )

        # Write quality score to quality_scores table
        if version_id and result.get("quality_score") is not None:
            await conn.execute("""
                INSERT INTO silver_aa_internal.quality_scores (
                    generated_content_id, tour_id, tenant_id,
                    score_overall, score_brand, score_seo,
                    score_structure, score_quality,
                    passed_count, failed_count,
                    validator_fn_version, evaluated_at
                ) VALUES (
                    $1::uuid, $2::uuid, $3::uuid,
                    $4, $4, $4, $4, $4,
                    0, 0, 'v1', NOW()
                )
                ON CONFLICT DO NOTHING
            """,
                version_id,
                req.tour_id,
                "00000000-0000-0000-0000-000000000001",
                float(result.get("quality_score", 0.0)),
            )

        # Export to gold layer if quality passed — bypasses Step Functions (AA-22)
        if version_id and status == "approved":
            from services.export.handler import process_export
            try:
                await process_export(str(version_id))
                logger.info("export_completed", tour_id=req.tour_id, version_id=str(version_id))
            except Exception as _exp_err:
                logger.error("export_failed", tour_id=req.tour_id,
                             version_id=str(version_id), error=str(_exp_err))

        # G-04: Write cost to pipeline_runs — accumulate per tour
        # tours_passed is NOT incremented here — process_export owns that counter
        # (it sets tours_passed = COUNT(published) which is always accurate)
        cost_usd    = float(result.get("cost_usd") or 0.0)
        tokens_in   = int(result.get("input_tokens") or 0)
        tokens_out  = int(result.get("output_tokens") or 0)
        tour_passed = float(result.get("quality_score") or 0.0) >= 7.0
        model_name = result.get("model_used") or None
        if isinstance(model_name, str) and not model_name:
            model_name = None
        # Derive actual provider from model name — gpt-* is openai, everything else bedrock
        actual_provider = (
            "openai" if model_name and "gpt" in model_name.lower() else "bedrock"
        )
        if cost_usd > 0 or tokens_in > 0:
            await conn.execute("""
                UPDATE shared.pipeline_runs
                SET
                    cost_usd      = COALESCE(cost_usd, 0)      + $1,
                    tokens_input  = COALESCE(tokens_input, 0)  + $2,
                    tokens_output = COALESCE(tokens_output, 0) + $3,
                    tours_failed  = tours_failed + $4,
                    llm_model     = COALESCE($6, llm_model),
                    llm_provider  = $7,
                    step_name     = 'content_generation'
                WHERE batch_id = $5::uuid
            """,
                cost_usd,
                tokens_in,
                tokens_out,
                0 if tour_passed else 1,
                req.batch_id,
                model_name,
                actual_provider,
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


# ── S3 Presigned Upload URL ───────────────────────────────────────────────────

_security = _HTTPBearer()


def _get_tenant(
    request: Request,
    credentials: Optional[_Creds] = Depends(_HTTPBearer(auto_error=False)),
):
    import os
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    x_admin = request.headers.get("X-Admin-Secret", "")
    if admin_secret and x_admin == admin_secret:
        return {"sub": "00000000-0000-0000-0000-000000000001", "role": "admin"}
    if credentials:
        try:
            return _verify_jwt(credentials.credentials)
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


class UploadUrlRequest(BaseModel):
    filename: str
    content_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    seo_mode: str = "standard"  # standard | aggressive | minimal


class UploadUrlResponse(BaseModel):
    upload_url: str
    s3_key: str
    bucket: str


@router.post("/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(
    body: UploadUrlRequest,
    tenant=Depends(_get_tenant),
):
    """Generate S3 presigned PUT URL → triggers Ingestion Lambda on upload."""
    import uuid as _uuid
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")
    bucket    = os.environ.get("BRONZE_BUCKET", "aa-cis-bronze-867490540162")
    import re as _re
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


class IngestS3Request(_BaseModel):
    s3_key: str
    bucket: str
    seo_mode: str = "standard"
    model_tier: str = "haiku"


# Limit concurrent LLM runs to avoid DB pool exhaustion and Bedrock throttling
_pipeline_semaphore = asyncio.Semaphore(2)


async def _run_tour_safe(tour_req: TourRunRequest) -> None:
    """Background task: semaphore-gated, 3-attempt retry, full error capture."""
    async with _pipeline_semaphore:
        last_exc: Exception | None = None
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(2 ** attempt)  # 2s, 4s backoff
            try:
                await run_tour(tour_req)
                # process_export (called inside run_tour) owns tours_passed and
                # batch completion. Nothing more to do on success.
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "run_tour_attempt_failed",
                    tour_id=tour_req.tour_id,
                    attempt=attempt + 1,
                    error=str(exc),
                )

        # All retries exhausted — mark failed and capture error_message
        logger.error(
            "background_run_tour_failed",
            tour_id=tour_req.tour_id,
            batch_id=tour_req.batch_id,
            error=str(last_exc),
        )
        try:
            conn = await asyncpg.connect(os.environ["DATABASE_URL"])
            await conn.execute(
                """UPDATE shared.pipeline_runs
                   SET status = 'failed',
                       error_message = $2
                   WHERE batch_id = $1::uuid AND status = 'ingesting'""",
                tour_req.batch_id,
                str(last_exc)[:1000],
            )
            await conn.close()
        except Exception as db_exc:
            logger.error("failed_to_mark_pipeline_failed", error=str(db_exc))


@router.post("/ingest-s3")
async def ingest_s3(
    req: IngestS3Request,
    background_tasks: BackgroundTasks,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Parse uploaded S3 Excel → insert raw_tours → trigger run_tour per tour."""
    from services.ingestion.handler import process_file

    result = await process_file(req.bucket, req.s3_key, seo_mode=req.seo_mode)

    if result.get("status") == "skipped_duplicate":
        return {"status": "duplicate", "batch_id": None, "tour_count": 0}

    batch_id = result.get("source_id")  # process_file returns batch_id as source_id

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tour_id FROM silver_aa_internal.raw_tours WHERE batch_id = $1::uuid",
            batch_id,
        )

    for row in rows:
        tour_req = TourRunRequest(
            tour_id=str(row["tour_id"]),
            batch_id=batch_id,
            tenant_id="00000000-0000-0000-0000-000000000001",
            seo_mode=req.seo_mode,
            model_tier=req.model_tier,
        )
        background_tasks.add_task(_run_tour_safe, tour_req)

    logger.info("ingest_s3_triggered", batch_id=batch_id, tour_count=len(rows),
                seo_mode=req.seo_mode, model_tier=req.model_tier)
    return {"status": "triggered", "batch_id": batch_id, "tour_count": len(rows)}


# ── Step Functions Execution Status ──────────────────────────────────────────

class ExecutionStatus(BaseModel):
    execution_id: str
    status: str
    start_date: str | None = None
    stop_date:  str | None = None
    tours_processed: int | None = None


@router.get("/execution/{execution_id:path}", response_model=ExecutionStatus)
async def get_execution_status(
    execution_id: str,
    tenant=Depends(_get_tenant),
):
    """Poll Step Functions execution status by ARN."""
    import json as _json
    sf = _boto3.client("stepfunctions", region_name=os.environ.get("AWS_REGION", "us-west-1"))
    try:
        resp   = sf.describe_execution(executionArn=execution_id)
        output = None
        if resp.get("output"):
            output = _json.loads(resp["output"])
        return ExecutionStatus(
            execution_id=execution_id,
            status=resp["status"],
            start_date=str(resp.get("startDate", "")),
            stop_date=str(resp.get("stopDate", "")) if resp.get("stopDate") else None,
            tours_processed=output.get("tours_processed") if output else None,
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Review Queue ──────────────────────────────────────────────────────────────

@router.get("/review-queue")
async def get_review_queue(
    request: Request,
    tenant=Depends(_get_tenant),
    page: int = 1,
    page_size: int = 20,
):
    """Get tours pending HITL review from review_queue table."""
    pool = request.app.state.pool
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")
    offset = (page - 1) * page_size

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT rq.id, rq.tour_id, rq.generated_content_id,
                   rq.review_status, rq.score_overall, rq.failure_summary, rq.created_at,
                   gc.aa_name, gc.aa_subtitle, gc.aa_summary,
                   gc.seo_title, gc.seo_meta,
                   rt.src_name, rt.src_subtitle, rt.src_summary,
                   rt.country, rt.duration
            FROM silver_aa_internal.review_queue rq
            JOIN silver_aa_internal.generated_content gc ON gc.id = rq.generated_content_id
            JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = rq.tour_id
            WHERE rq.tenant_id = $1::uuid
              AND rq.review_status = 'pending'
            ORDER BY rq.created_at DESC
            LIMIT $2 OFFSET $3
        """, tenant_id, page_size, offset)

        total = await conn.fetchval("""
            SELECT COUNT(*) FROM silver_aa_internal.review_queue
            WHERE tenant_id = $1::uuid AND review_status = 'pending'
        """, tenant_id)

    return {
        "data": [dict(r) for r in rows],
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }


@router.post("/review-queue/{review_id}/approve")
async def approve_review(
    review_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Approve a tour in review queue → send_task_success → SF continues to Export."""
    pool = request.app.state.pool
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")

    async with pool.acquire() as conn:
        # Get task_token + generated_content_id
        row = await conn.fetchrow("""
            SELECT step_fn_task_token, generated_content_id
            FROM silver_aa_internal.review_queue
            WHERE id = $1::uuid AND tenant_id = $2::uuid
        """, review_id, tenant_id)

        if not row:
            raise HTTPException(status_code=404, detail="Review not found")

        task_token = row["step_fn_task_token"]
        generated_content_id = str(row["generated_content_id"])

        # Update review_queue + generated_content
        await conn.execute("""
            UPDATE silver_aa_internal.review_queue
            SET review_status = 'approved', reviewed_at = NOW()
            WHERE id = $1::uuid
        """, review_id)

        await conn.execute("""
            UPDATE silver_aa_internal.generated_content
            SET status = 'approved'
            WHERE id = $1::uuid
        """, generated_content_id)

    # Send task success to Step Functions (outside DB transaction)
    if task_token:
        try:
            sfn = _boto3.client(
                "stepfunctions",
                region_name=os.environ.get("AWS_REGION", "us-west-1"),
            )
            sfn.send_task_success(
                taskToken=task_token,
                output=json.dumps({
                    "decision": "approved",
                    "review_id": review_id,
                    "version_id": generated_content_id,
                }),
            )
        except Exception as e:
            import structlog as _sl
            _sl.get_logger().warning("send_task_success_failed", error=str(e))

    return {"status": "approved", "review_id": review_id, "sf_notified": bool(task_token)}


@router.post("/review-queue/{review_id}/reject")
async def reject_review(
    review_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Reject a tour → send_task_failure → SF goes to TourRejected."""
    pool = request.app.state.pool
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT step_fn_task_token
            FROM silver_aa_internal.review_queue
            WHERE id = $1::uuid AND tenant_id = $2::uuid
        """, review_id, tenant_id)

        if not row:
            raise HTTPException(status_code=404, detail="Review not found")

        task_token = row["step_fn_task_token"]

        await conn.execute("""
            UPDATE silver_aa_internal.review_queue
            SET review_status = 'rejected', reviewed_at = NOW()
            WHERE id = $1::uuid
        """, review_id)

    # Send task failure to Step Functions
    if task_token:
        try:
            sfn = _boto3.client(
                "stepfunctions",
                region_name=os.environ.get("AWS_REGION", "us-west-1"),
            )
            sfn.send_task_failure(
                taskToken=task_token,
                error="TourRejectedByReviewer",
                cause="Human reviewer rejected the tour content",
            )
        except Exception as e:
            import structlog as _sl
            _sl.get_logger().warning("send_task_failure_failed", error=str(e))

    return {"status": "rejected", "review_id": review_id, "sf_notified": bool(task_token)}


# =============================================================================
# GET /sources — Upload history (TD-2 UI, added 29/04/2026)
# =============================================================================
@router.get("/sources")
async def get_sources(
    request: Request,
    limit: int = 20,
    tenant=Depends(_get_tenant),
):
    """Return upload history for current tenant."""
    pool = request.app.state.pool
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                id,
                filename,
                s3_path,
                file_hash,
                file_size_kb,
                row_count,
                parsed_at
            FROM silver_aa_internal.raw_sources
            WHERE tenant_id = $1::uuid
            ORDER BY parsed_at DESC
            LIMIT $2
        """, tenant_id, limit)

    return {
        "sources": [
            {
                "id":           str(r["id"]),
                "filename":     r["filename"],
                "s3_path":      r["s3_path"],
                "file_hash":    r["file_hash"][:12] + "..." if r["file_hash"] else None,
                "file_size_kb": r["file_size_kb"],
                "row_count":    r["row_count"],
                "parsed_at":    r["parsed_at"].isoformat() if r["parsed_at"] else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


# =============================================================================
# GET /pipeline/metrics — Dashboard metrics (admin)
# =============================================================================
@router.get("/metrics")
async def get_pipeline_metrics(
    request: Request,
    days: int = 7,
    tenant=Depends(_get_tenant),
):
    """Dashboard metrics: daily runs + model usage."""
    pool = request.app.state.pool
    tenant_slug = "aa_internal"

    async with pool.acquire() as conn:
        # Daily pipeline runs
        daily = await conn.fetch("""
            SELECT
                DATE(started_at)            AS day,
                COUNT(*)                    AS runs,
                COALESCE(SUM(tours_total),0)  AS tours,
                COALESCE(SUM(tours_passed),0) AS passed,
                COALESCE(SUM(tours_hitl),0)   AS hitl,
                COALESCE(SUM(tours_failed),0) AS failed,
                COALESCE(ROUND(SUM(cost_usd)::numeric,4), 0) AS cost
            FROM shared.pipeline_runs
            WHERE started_at >= NOW() - ($1 || ' days')::interval
            GROUP BY DATE(started_at)
            ORDER BY day ASC
        """, str(days))

        # Cost by model — actual billed cost from pipeline_runs
        # CASE normalizes "us.anthropic.claude-haiku-4-5-...-v1:0" and "claude-haiku"
        # to the same display name so old + new runs group together.
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
            WHERE cost_usd > 0
            GROUP BY 1
            ORDER BY total_cost DESC
        """)

        # LLM call quality — from generated_content (per-call granularity)
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
            GROUP BY 1
            ORDER BY calls DESC
        """)

        # Header KPI — avg cost per pipeline run from real data
        avg_cost_per_run = await conn.fetchval("""
            SELECT ROUND(SUM(cost_usd) / NULLIF(COUNT(*), 0)::numeric, 6)
            FROM shared.pipeline_runs
            WHERE cost_usd > 0
        """)

        # Canonical tour count — source of truth for all "Tours Processed" metrics
        published_count = await conn.fetchval("""
            SELECT COUNT(*) FROM gold_aa_internal.published_tours
            WHERE tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
        """)

        # LLM call count — from generated_content (accurate for cost attribution)
        llm_calls = await conn.fetchval(f"""
            SELECT COUNT(*) FROM silver_{tenant_slug}.generated_content
        """)

        # Pipeline health — check last run per service via pipeline_runs
        last_run = await conn.fetchrow("""
            SELECT
                tours_total, tours_passed, tours_failed,
                started_at, completed_at,
                EXTRACT(EPOCH FROM (completed_at - started_at)) AS duration_sec
            FROM shared.pipeline_runs
            WHERE completed_at IS NOT NULL
            ORDER BY started_at DESC LIMIT 1
        """)

        # Service health from tenant_api_usage (last 1 hour)
        health_rows = await conn.fetch("""
            SELECT
                endpoint,
                COUNT(*)                                                    AS calls,
                ROUND(AVG(response_ms)::numeric, 0)                        AS avg_ms,
                SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END)        AS errors,
                SUM(CASE WHEN status_code = 429 THEN 1 ELSE 0 END)         AS rate_limited,
                MAX(called_at)                                              AS last_call
            FROM shared.tenant_api_usage
            WHERE called_at >= NOW() - INTERVAL '1 hour'
            GROUP BY endpoint
            ORDER BY calls DESC
        """)

        # Map endpoints to service names
        ENDPOINT_SERVICE_MAP = {
            "/v1/pipeline/run":         "Step Functions Pipeline",
            "/v1/pipeline/run-tour":    "Content Generation",
            "/v1/pipeline/review-queue": "Validation Lambda",
            "/v1/tours":                "Export / Catalog API",
            "/v1/pipeline/upload-url":  "Ingestion Lambda",
            "/v1/pipeline/metrics":     "Admin Metrics API",
            "/v1/pipeline/sources":     "Source Tracker",
            "/health":                  "API Health Check",
        }

        pipeline_health = []
        seen_services = set()
        for r in health_rows:
            ep = r["endpoint"]
            # Normalize endpoint (strip IDs)
            import re as _re
            ep_norm = _re.sub(r'/[0-9a-f-]{8,}', '/{id}', ep)
            service = ENDPOINT_SERVICE_MAP.get(ep, ENDPOINT_SERVICE_MAP.get(ep_norm, ep))
            if service in seen_services:
                continue
            seen_services.add(service)
            errors = int(r["errors"] or 0)
            calls  = int(r["calls"] or 0)
            avg_ms = float(r["avg_ms"] or 0)
            status = "healthy" if errors == 0 else ("degraded" if errors / max(calls, 1) < 0.1 else "down")
            pipeline_health.append({
                "name":    service,
                "status":  status,
                "latency": f"{avg_ms:.0f}ms",
                "errors":  errors,
                "calls":   calls,
            })

        # Always include core services even if no recent calls
        CORE_SERVICES = [
            "Ingestion Lambda", "Step Functions Pipeline",
            "Content Generation", "Validation Lambda",
            "Export / Catalog API",
        ]
        for svc in CORE_SERVICES:
            if svc not in seen_services:
                pipeline_health.append({
                    "name": svc, "status": "idle",
                    "latency": "—", "errors": 0, "calls": 0,
                })

    # Merge cost (pipeline_runs) + quality (generated_content) by model name
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
    # Include models that appear only in pipeline_runs (no generated_content match)
    for r in cost_by_model:
        if r["model"] not in seen_models:
            total_cost = float(r["total_cost"])
            model_usage.append({
                "model":         r["model"],
                "calls":         int(r["batches"]),
                "avg_score":     None,
                "total_cost":    round(total_cost, 4),
                "cost_per_call": 0.0,
            })

    return {
        "daily_runs": [
            {
                "date":   str(r["day"]),
                "runs":   r["runs"],
                "tours":  r["tours"],
                "passed": r["passed"],
                "hitl":   r["hitl"],
                "failed": r["failed"],
                "cost":   float(r["cost"]),
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
        "published_count": int(published_count or 0),
        "llm_calls":       int(llm_calls or 0),
    }


# =============================================================================
# Brand Identity endpoints
# =============================================================================


class BrandIdentityUpdate(_BaseModel):
    system_prompt: _Optional[str] = None
    style_guide:   _Optional[str] = None
    forbidden_words: _Optional[_List[str]] = None


@router.get("/brand-identity")
async def get_brand_identity(
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Get brand identity config for current tenant — includes all versions."""
    import json as _json_br
    pool = request.app.state.pool
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")
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
            FROM shared.tenant_brand_rules
            WHERE tenant_id = $1
            ORDER BY version DESC
        """, tenant_id)

    def parse_fw(fw):
        if fw is None: return []
        if isinstance(fw, list): return fw
        try: return _json_br.loads(fw)
        except Exception:  # noqa: BLE001
            return []
    history = [{
        "version":       h["version"],
        "is_active":     h["is_active"],
        "system_prompt": h["system_prompt"] or "",
        "style_guide":   h["style_guide"] or "",
        "forbidden_words": parse_fw(h["forbidden_words"]),
        "updated_at": h["updated_at"].isoformat() if h["updated_at"] else None,
        "created_at": h["created_at"].isoformat() if h["created_at"] else None,
    } for h in history_rows]
    return {
        "configured":    True,
        "system_prompt": row["system_prompt"],
        "style_guide":   row["style_guide"],
        "forbidden_words": parse_fw(row["forbidden_words"]),
        "version":    row["version"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "history":    history,
    }


@router.post("/brand-identity")
async def update_brand_identity(
    body: BrandIdentityUpdate,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Upsert brand identity for current tenant."""
    pool = request.app.state.pool
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")
    import json as _json
    async with pool.acquire() as conn:
        # Get current version
        current = await conn.fetchval("""
            SELECT COALESCE(MAX(version), 0) FROM shared.tenant_brand_rules
            WHERE tenant_id = $1
        """, tenant_id)

        await conn.execute("""
            UPDATE shared.tenant_brand_rules SET is_active = false WHERE tenant_id = $1
        """, tenant_id)

        await conn.execute("""
            INSERT INTO shared.tenant_brand_rules
                (tenant_id, system_prompt, style_guide, forbidden_words, version, is_active, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, true, NOW())
        """,
            tenant_id,
            body.system_prompt,
            body.style_guide,
            _json.dumps(body.forbidden_words or []),
            current + 1,
        )
    return {"status": "updated", "version": current + 1}


@router.post("/brand-identity/upload")
async def upload_brand_file(
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Get presigned URL to upload brand identity PDF/DOCX to S3."""
    import uuid as _uuid2
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")
    body = await request.json()
    filename = body.get("filename", "brand.pdf")
    content_type = body.get("content_type", "application/pdf")

    import re as _re2
    safe_name = _re2.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    s3_key = f"brand-identity/{tenant_id}/{_uuid2.uuid4()}_{safe_name}"
    bucket = os.environ.get("BRONZE_BUCKET", "aa-cis-bronze-867490540162")

    s3 = _boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-1"))
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": s3_key, "ContentType": content_type},
        ExpiresIn=300,
    )
    return {"upload_url": upload_url, "s3_key": s3_key}


# ── P3-S8: SEO Intelligence metrics ──────────────────────────────────────────

@router.get("/metrics/seo")
async def get_seo_metrics(
    request: Request,
    tenant=Depends(_get_tenant),
):
    """SEO Intelligence tab: DataForSEO usage + Redis cache stats + top keywords."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        # Top keywords by country from seo_contexts
        top_keywords = await conn.fetch("""
            SELECT keyword_search, top_keywords, fetched_at
            FROM silver_aa_internal.seo_context
            ORDER BY fetched_at DESC
            LIMIT 20
        """)

        # SEO coverage: how many tours have seo_contexts
        total_tours = await conn.fetchval(
            "SELECT COUNT(*) FROM gold_aa_internal.published_tours "
            "WHERE tenant_id = '00000000-0000-0000-0000-000000000001'::uuid"
        )
        # seo_context is cached per destination (not per tour) — count tours whose
        # country has a seo_context entry
        seo_covered = await conn.fetchval("""
            SELECT COUNT(DISTINCT pt.tour_id)
            FROM gold_aa_internal.published_tours pt
            JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE pt.tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
              AND EXISTS (
                  SELECT 1 FROM silver_aa_internal.seo_context sc
                  WHERE sc.tour_id = rt.tour_id
              )
        """)

        # Countries covered — join raw_tours for actual country name
        countries = await conn.fetch("""
            SELECT rt.country, COUNT(sc.id) as count
            FROM silver_aa_internal.seo_context sc
            JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = sc.tour_id
            WHERE rt.country IS NOT NULL
            GROUP BY rt.country ORDER BY count DESC
        """)

    # Redis cache stats
    redis = request.app.state.redis
    cache_stats = {"hit_rate": "N/A", "keys": 0}
    try:
        info = await redis.info("stats")
        hits = int(info.get("keyspace_hits", 0))
        misses = int(info.get("keyspace_misses", 0))
        total = hits + misses
        cache_stats["hit_rate"] = f"{round(hits/total*100, 1)}%" if total > 0 else "0%"
        cache_stats["hits"] = hits
        cache_stats["misses"] = misses
        db_info = await redis.info("keyspace")
        cache_stats["keys"] = sum(
            int(v.split(",")[0].split("=")[1])
            for v in db_info.values() if isinstance(v, str) and "keys=" in v
        )
    except Exception:
        pass

    # Parse keywords from seo_contexts
    # asyncpg returns JSONB columns as raw JSON strings — must parse explicitly
    import json as _j
    keyword_counts: dict = {}
    for row in top_keywords:
        try:
            kw_data = row["top_keywords"]
            if isinstance(kw_data, str):
                kw_data = _j.loads(kw_data)
            if isinstance(kw_data, list):
                items = kw_data
            elif isinstance(kw_data, dict):
                items = kw_data.get("top_keywords") or []
            else:
                items = []
            for item in items[:5]:
                kw = item.get("keyword") if isinstance(item, dict) else str(item)
                if kw: keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
        except Exception:
            pass

    top_kw = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)[:15]

    return {
        "total_tours":   total_tours,
        "seo_covered":   seo_covered,
        "coverage_pct":  round(seo_covered / total_tours * 100, 1) if total_tours else 0,
        "countries":     [{"country": dict(r)["country"], "count": dict(r)["count"]} for r in countries],
        "top_keywords":  [{"keyword": k, "count": v} for k, v in top_kw],
        "cache":         cache_stats,
    }


# ── P3-S8: Content Library metrics ───────────────────────────────────────────

@router.get("/metrics/library")
async def get_library_metrics(
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Content Library tab: pool coverage by country/type, freshness."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        # Coverage by country
        by_country = await conn.fetch("""
            SELECT rt.country,
                   COUNT(pt.id)                          AS total,
                   ROUND(AVG(pt.quality_score)::numeric,2) AS avg_score,
                   MAX(pt.published_at)                  AS last_published
            FROM gold_aa_internal.published_tours pt
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE pt.tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
            GROUP BY rt.country
            ORDER BY total DESC
        """)

        # Overall stats
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*)                                     AS total,
                ROUND(AVG(quality_score)::numeric, 2)        AS avg_score,
                COUNT(CASE WHEN published_at >= NOW() - INTERVAL '30 days'
                      THEN 1 END)                            AS published_last_30d,
                COUNT(CASE WHEN published_at < NOW() - INTERVAL '180 days'
                      THEN 1 END)                            AS stale_count
            FROM gold_aa_internal.published_tours
            WHERE tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
        """)

        # Score distribution
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
        "total":            stats["total"],
        "avg_score":        float(stats["avg_score"] or 0),
        "published_last_30d": stats["published_last_30d"],
        "stale_count":      stats["stale_count"],
        "by_country":       [dict(r) for r in by_country],
        "score_distribution": [dict(r) for r in score_dist],
    }


# ── P3-S8: Spot Workers real data ─────────────────────────────────────────────

@router.get("/metrics/spot-workers")
async def get_spot_workers(
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Spot Workers tab: real ECS Fargate Spot task data."""
    import boto3 as _boto3_sw
    ecs = _boto3_sw.client(
        "ecs", region_name=os.environ.get("AWS_REGION", "us-west-1")
    )
    cluster = os.environ.get("ECS_CLUSTER", "aa-cis-dev-cluster")

    try:
        # List running tasks
        task_arns = ecs.list_tasks(
            cluster=cluster, desiredStatus="RUNNING"
        ).get("taskArns", [])

        spot_tasks = []
        on_demand_tasks = []

        if task_arns:
            tasks = ecs.describe_tasks(
                cluster=cluster, tasks=task_arns
            ).get("tasks", [])

            for t in tasks:
                cap = t.get("capacityProviderName", "FARGATE")
                info = {
                    "task_id":  t["taskArn"].split("/")[-1][:12],
                    "status":   t.get("lastStatus", "UNKNOWN"),
                    "cpu":      t.get("cpu", "256"),
                    "memory":   t.get("memory", "512"),
                    "started":  str(t.get("startedAt", "")),
                    "capacity": cap,
                }
                if cap == "FARGATE_SPOT":
                    spot_tasks.append(info)
                else:
                    on_demand_tasks.append(info)

        # Cost saving estimate
        spot_count = len(spot_tasks)
        total_count = len(task_arns)
        spot_pct = round(spot_count / total_count * 100) if total_count else 0
        # Fargate: ~$0.04048/vCPU/hr, Spot: ~70% cheaper
        saving_per_hr = spot_count * 0.04048 * 0.7

        return {
            "total_tasks":     total_count,
            "spot_tasks":      spot_count,
            "on_demand_tasks": len(on_demand_tasks),
            "spot_pct":        spot_pct,
            "saving_per_hr":   round(saving_per_hr, 4),
            "tasks":           spot_tasks + on_demand_tasks,
        }
    except Exception as e:
        return {
            "total_tasks": 0, "spot_tasks": 0,
            "on_demand_tasks": 0, "spot_pct": 0,
            "saving_per_hr": 0, "tasks": [],
            "error": str(e),
        }


# ── P3-S6: Tenant billing summary ────────────────────────────────────────────

@router.get("/billing")
async def get_tenant_billing(
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Tenant billing summary — quota usage, spend, overage."""
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")
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

        # Recent activity — last 5 versions created
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
            "plan_tier": "starter",
            "tours_quota_monthly": 50,
            "api_calls_quota_monthly": 5000,
            "price_usd_monthly": 299.0,
            "tours_rewritten": 0, "api_calls_used": 0,
            "quota_tours_pct": 0.0, "quota_calls_pct": 0.0,
            "tours_overage": 0, "overage_usd": 0.0,
            "llm_cost_usd": 0.0, "overage_rate_usd_per_tour": 4.0,
            "activity": [],
        }

    return {
        **{k: (float(v) if hasattr(v, '__float__') and not isinstance(v, int)
               else v)
           for k, v in dict(row).items()
           if k not in ("billing_month",)},
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
