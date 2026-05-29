import re
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

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from typing import Optional

from services.ingestion.excel_parser import ExcelParser
from services.content_generation.graph import build_graph
from pydantic import BaseModel
import asyncpg
import boto3 as _boto3
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
    # Strip markdown bold from itineraries — ensure string type (GPT-4.1 may return dict)
    itin = generated.get("itineraries")
    if itin:
        if isinstance(itin, dict):
            parts = []
            for k, v in itin.items():
                parts.append(f"{k} -- {v}" if isinstance(v, str) else str(v))
            itin = "\n\n".join(parts)
        elif isinstance(itin, list):
            parts = []
            for item in itin:
                if isinstance(item, dict):
                    day   = item.get("day", "")
                    title = item.get("title", "")
                    desc  = item.get("description", "")
                    acts  = item.get("activities", [])
                    day_str = f"Day {day}"
                    if title:
                        day_str += f" — {title}"
                    if desc:
                        day_str += f"\n{desc}"
                    if acts:
                        act_list = ", ".join(str(a) for a in acts) if isinstance(acts, list) else str(acts)
                        day_str += f"\n*Activities: {act_list}*"
                    parts.append(day_str)
                else:
                    parts.append(str(item))
            itin = "\n\n---\n\n".join(parts)
        generated["itineraries"] = clean_itinerary(str(itin))
    # Same for highlights — ensure list of strings
    highlights = generated.get("highlights")
    if highlights and isinstance(highlights, list):
        generated["highlights"] = [str(h) if not isinstance(h, str) else h for h in highlights]
    return generated


def clean_itinerary(text: str) -> str:
    """Strip markdown bold markers (**) from itinerary — LLM sometimes adds them."""
    if not text:
        return text
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = text.replace("**", "")
    return text.strip()


async def _rewrite_tour(
    tour: dict, idx: int, total: int,
    brand_rules: dict = None,
    seo: dict = None,
    model_tier: str = "haiku",
    is_tenant_rewrite: bool = False,
    subtitle_focus: str = "standard",
    seo_mode: str = "dataforseo",
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
            "is_tenant_rewrite": is_tenant_rewrite,
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
            "subtitle_focus":       subtitle_focus,
            "seo_mode":             seo_mode,
            # brand audit defaults
            "brand_audit_status": "",
            "brand_audit_codes":  [],
            "brand_audit_issues": [],
            "brand_audit_fields": [],
            "lessons_extracted":  [],
            "fix_pass_applied":   False,
            "fix_pass_fields":    [],
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
            "error":         result.get("error", ""),
            "is_branded":    result.get("is_branded", True),
            "failure_codes": result.get("failure_codes", []),
            "sub_scores":    result.get("sub_scores", {}),
            "passed_count":  result.get("passed_count", 0),
            "failed_count":  result.get("failed_count", 0),
            "brand_audit_status": result.get("brand_audit_status", ""),
            "brand_audit_codes":  result.get("brand_audit_codes", []),
            "brand_audit_issues": result.get("brand_audit_issues", []),
            "brand_audit_fields": result.get("brand_audit_fields", []),
            "lessons_extracted":  result.get("lessons_extracted", []),
            "fix_pass_applied":   result.get("fix_pass_applied", False),
            "fix_pass_fields":    result.get("fix_pass_fields", []),
            "status": "success" if result.get("generated") and len(result.get("generated", {})) > 0 else "failed",
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


# ── SF per-tour endpoint — MOVED TO /admin/run-tour (admin_pipeline.py) ──────
# Kept as stub so Step Functions ARN references compile; real logic in admin_pipeline.py

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


# ── Auth helper (used by review-queue + sources + execution) ──────────────────

_security = _HTTPBearer()


def _get_tenant(
    request: Request,
    credentials: Optional[_Creds] = Depends(_HTTPBearer(auto_error=False)),
):
    import os
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    x_admin = request.headers.get("x-admin-secret", "")
    if admin_secret and x_admin == admin_secret:
        return {"sub": "00000000-0000-0000-0000-000000000001", "role": "admin"}
    if credentials:
        try:
            return _verify_jwt(credentials.credentials)
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


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
