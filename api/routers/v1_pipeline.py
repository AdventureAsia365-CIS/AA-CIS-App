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

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from services.ingestion.excel_parser import ExcelParser
from services.content_generation.graph import build_graph
from shared.llm_client.client import LLMClient
from shared.llm_client.models import LLMRequest
from services.content_generation.prompts import SYSTEM_PROMPT, build_rewrite_prompt
from pydantic import BaseModel
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



async def _rewrite_tour(tour: dict, idx: int, total: int) -> dict:
    """Rewrite single tour using LangGraph."""
    logger.info("rewriting_tour", idx=idx, total=total, name=tour.get("name", ""))

    try:
        graph = build_graph()
        initial_state = {
            "tour": tour,
            "seo": {},
            "few_shots": [],
            "generated": {},
            "quality_score": 0.0,
            "retry_count": 0,
            "feedback": "",
            "error": "",
            "cost_usd": 0.0,
            "model_used": "",
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

@router.post("/run-tour")
async def run_tour(req: TourRunRequest):
    """Per-tour endpoint for Step Functions — load tour from DB, rewrite, return result."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
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

        result = await _rewrite_tour(tour, idx=0, total=1)

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
                    aa_highlights, seo_title, seo_meta,
                    model_editorial, status
                ) VALUES (
                    $1::uuid, $2::uuid,
                    COALESCE((SELECT MAX(version_num) + 1
                    FROM silver_aa_internal.generated_content
                    WHERE tour_id = $1::uuid), 1),
                    $3, $4, $5,
                    $6::jsonb, $7, $8,
                    $9, $10::content_status_enum
                ) RETURNING id
            """,
                req.tour_id,
                "00000000-0000-0000-0000-000000000001",
                generated.get("name"),
                generated.get("subtitle"),
                generated.get("summary"),
                _json.dumps(generated.get("highlights", [])),
                generated.get("seo_title"),
                generated.get("seo_meta"),
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

def _get_tenant(credentials: _Creds = Depends(_security)):
    try:
        return _verify_jwt(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

class UploadUrlRequest(BaseModel):
    filename: str
    content_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

class UploadUrlResponse(BaseModel):
    upload_url: str
    s3_key: str
    bucket: str

@router.post("/v1/pipeline/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(
    body: UploadUrlRequest,
    tenant=Depends(_get_tenant),
):
    """Generate S3 presigned PUT URL → triggers Ingestion Lambda on upload."""
    import uuid as _uuid
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")
    bucket    = os.environ.get("BRONZE_BUCKET", "aa-cis-bronze-867490540162")
    s3_key    = f"raw-inbox/{tenant_id}/{_uuid.uuid4()}_{body.filename}"
    s3 = _boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-1"))
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": s3_key, "ContentType": body.content_type},
        ExpiresIn=300,
    )
    return UploadUrlResponse(upload_url=upload_url, s3_key=s3_key, bucket=bucket)


# ── Step Functions Execution Status ──────────────────────────────────────────

class ExecutionStatus(BaseModel):
    execution_id: str
    status: str
    start_date: str | None = None
    stop_date:  str | None = None
    tours_processed: int | None = None

@router.get("/v1/pipeline/execution/{execution_id:path}", response_model=ExecutionStatus)
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

@router.get("/v1/pipeline/review-queue")
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


@router.post("/v1/pipeline/review-queue/{review_id}/approve")
async def approve_review(
    review_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Approve a tour in review queue → mark as approved."""
    pool = request.app.state.pool
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE silver_aa_internal.review_queue
            SET review_status = 'approved', reviewed_at = NOW()
            WHERE id = $1::uuid AND tenant_id = $2::uuid
        """, review_id, tenant_id)

        # Also update generated_content status
        await conn.execute("""
            UPDATE silver_aa_internal.generated_content gc
            SET status = 'approved'
            FROM silver_aa_internal.review_queue rq
            WHERE rq.id = $1::uuid
              AND gc.id = rq.generated_content_id
        """, review_id)

    return {"status": "approved", "review_id": review_id}


@router.post("/v1/pipeline/review-queue/{review_id}/reject")
async def reject_review(
    review_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Reject a tour in review queue."""
    pool = request.app.state.pool
    tenant_id = tenant.get("sub", "00000000-0000-0000-0000-000000000001")

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE silver_aa_internal.review_queue
            SET review_status = 'rejected', reviewed_at = NOW()
            WHERE id = $1::uuid AND tenant_id = $2::uuid
        """, review_id, tenant_id)

    return {"status": "rejected", "review_id": review_id}
