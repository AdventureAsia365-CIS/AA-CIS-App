# api/routers/admin_pipeline.py
# Admin-only pipeline endpoints — mounted at /admin/* (no Lambda Authorizer at API GW)
# Auth: x-admin-secret header only (no tenant JWT accepted)

import asyncio
import base64
import datetime
import json
import os
from uuid import UUID

import asyncpg
import boto3 as _boto3
import structlog
from fastapi import APIRouter, Header, HTTPException, Request
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
    seo_mode: str = "standard"
    rewrite_language: str = "en-US"
    model_tier: str = "haiku"
    subtitle_focus: str = "standard"
    brand_rules_version: Optional[int] = None
    brand_name: Optional[str] = None


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
    bucket: str = ""
    seo_mode: str = "dataforseo"
    model_tier: str = "haiku"
    subtitle_focus: str = "standard"
    dry_run: bool = False
    tenant_id: str = "00000000-0000-0000-0000-000000000001"
    max_tours: int = 500


class BrandIdentityUpdate(BaseModel):
    system_prompt: Optional[str] = None
    style_guide:   Optional[str] = None
    forbidden_words: Optional[List[str]] = None


class CountryUpdateRequest(BaseModel):
    country: str


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
        brand_rule_id: str = ""
        brand_name_val: str = ""
        try:
            _brand_name_filter = getattr(req, "brand_name", None)
            if _brand_name_filter:
                br_row = await conn.fetchrow("""
                    SELECT id, brand_name, system_prompt, style_guide, forbidden_words
                    FROM shared.tenant_brand_rules
                    WHERE tenant_id = $1::uuid AND brand_name = $2
                    ORDER BY version DESC LIMIT 1
                """, tenant_uuid, _brand_name_filter)
            else:
                br_row = await conn.fetchrow("""
                    SELECT id, brand_name, system_prompt, style_guide, forbidden_words
                    FROM shared.tenant_brand_rules
                    WHERE tenant_id = $1::uuid AND is_active = true
                    ORDER BY version DESC LIMIT 1
                """, tenant_uuid)
            if br_row:
                brand_rule_id = str(br_row["id"]) if br_row["id"] else ""
                brand_name_val = br_row["brand_name"] or ""
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
        dataforseo_used: bool = False
        try:
            from services.seo_intelligence.handler import process_seo
            _SEO_MODE_MAP = {"standard": "dataforseo", "aggressive": "dataforseo", "minimal": "disabled"}
            effective_seo_mode = _SEO_MODE_MAP.get(req.seo_mode, req.seo_mode)
            destination = (
                f"{row['country']} tours" if row.get("country") else row.get("src_name", "")
            )
            if destination:
                seo_result = await process_seo(
                    tour_id=req.tour_id, destination=destination, seo_mode=effective_seo_mode,
                )
                seo_data = seo_result.get("data", {})
                dataforseo_used = seo_result.get("status") == "fetched"
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
            metadata_val = json.dumps({
                "brand_rule_id":   brand_rule_id,
                "brand_name":      brand_name_val,
                "seo_mode":        req.seo_mode,
                "model_used":      result.get("model_used", ""),
                "llm_cost_usd":    float(result.get("cost_usd") or 0.0),
                "dataforseo_used": dataforseo_used,
                "generated_at":    datetime.datetime.utcnow().isoformat() + "Z",
                "pipeline_version": "v2",
            })
            version_id = await conn.fetchval("""
                INSERT INTO silver_aa_internal.generated_content (
                    tour_id, tenant_id, version_num,
                    aa_name, aa_subtitle, aa_summary,
                    aa_description, aa_highlights, aa_itineraries,
                    seo_title, seo_meta, seo_keywords_used,
                    model_editorial, status, og_tags, metadata
                ) VALUES (
                    $1::uuid, $2::uuid,
                    COALESCE((SELECT MAX(version_num) + 1
                    FROM silver_aa_internal.generated_content
                    WHERE tour_id = $1::uuid), 1),
                    $3, $4, $5, $6, $7::jsonb, $8,
                    $9, $10, $11::jsonb, $12, $13::content_status_enum, $14::jsonb, $15::jsonb
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
                metadata_val,
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
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)

    _bucket = req.bucket or os.environ.get("BRONZE_BUCKET", "aa-cis-bronze-867490540162")

    # ── dry_run=True: parse-only preview, no DB write ─────────────────────────
    if req.dry_run:
        import tempfile as _tempfile
        import hashlib as _hashlib
        from services.ingestion.excel_parser import ExcelParser as _ExcelParser
        import uuid as _uuid

        s3_client = _boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-1"))
        with _tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            s3_client.download_fileobj(_bucket, req.s3_key, tmp)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as fh:
            file_bytes = fh.read()
        file_hash = _hashlib.sha256(file_bytes).hexdigest()

        pool = request.app.state.pool
        async with pool.acquire() as conn:
            existing_hash = await conn.fetchrow(
                "SELECT id, filename FROM silver_aa_internal.raw_sources WHERE file_hash = $1",
                file_hash,
            )
            if existing_hash:
                return {
                    "status":  "blocked",
                    "reason":  "duplicate_file_hash",
                    "dry_run": True,
                    "message": "File hash trùng — nội dung này đã tồn tại trong hệ thống. Vui lòng chọn file khác.",
                }

            parser = _ExcelParser(tmp_path, source_file=req.s3_key)
            records = parser.parse()

            all_names = [r["src_name"] for r in records if r.get("src_name")]
            duplicate_names: set = set()
            if all_names:
                dup_rows = await conn.fetch(
                    "SELECT DISTINCT src_name FROM silver_aa_internal.raw_tours WHERE src_name = ANY($1::text[])",
                    all_names,
                )
                duplicate_names = {r["src_name"] for r in dup_rows}

            ready_tours = []
            blocked_tours = []
            for r in records[:req.max_tours]:
                src_name = r.get("src_name") or "(no name)"
                missing = [f for f in ["src_name", "country", "duration", "price_raw"] if not r.get(f)]
                if src_name in duplicate_names:
                    blocked_tours.append({
                        "src_name": src_name, "country": r.get("country"),
                        "reason": "duplicate_tour", "message": "Tour này đã tồn tại trong hệ thống.",
                    })
                elif missing:
                    blocked_tours.append({
                        "src_name": src_name, "country": r.get("country"),
                        "reason": "missing_fields", "missing_fields": missing,
                        "message": f"Thiếu fields: {', '.join(missing)}",
                    })
                else:
                    ready_tours.append({
                        "tour_id":         str(_uuid.uuid4()),
                        "src_name":        src_name,
                        "country":         r.get("country"),
                        "duration":        r.get("duration"),
                        "price_raw":       r.get("price_raw"),
                        "group_size":      r.get("group_size"),
                        "period":          r.get("period"),
                        "pipeline_status": "preview",
                        "ingest_at":       "",
                        "src_subtitle":    r.get("src_subtitle"),
                        "src_summary":     r.get("src_summary"),
                        "src_highlights":  r.get("src_highlights"),
                        "src_itineraries": r.get("src_itineraries"),
                        "provider":        r.get("provider"),
                        "activities":      r.get("activities"),
                        "inclusions":      r.get("inclusions"),
                        "exclusions":      r.get("exclusions"),
                        "sku":             r.get("sku"),
                        "src_description": r.get("src_description"),
                        "links":           r.get("links"),
                        "feature":         r.get("feature"),
                        "best_time_to_go": r.get("best_time_to_go"),
                    })

            sources = await conn.fetch("""
                SELECT filename, s3_path, row_count, parsed_at, parse_errors, file_hash
                FROM silver_aa_internal.raw_sources
                WHERE tenant_id = $1::uuid
                ORDER BY parsed_at DESC LIMIT 20
            """, UUID("00000000-0000-0000-0000-000000000001"))

            return {
                "status":         "parsed",
                "dry_run":        True,
                "batch_id":       None,
                "ready_count":    len(ready_tours),
                "blocked_count":  len(blocked_tours),
                "tours":          ready_tours,
                "blocked_tours":  blocked_tours,
                "upload_history": [dict(s) for s in sources],
            }

    # ── dry_run=False: insert raw_sources + raw_tours, no pipeline trigger ────
    from services.ingestion.handler import process_file
    result = await process_file(_bucket, req.s3_key, seo_mode=req.seo_mode)
    if result.get("status") == "skipped_duplicate":
        return {"status": "duplicate", "batch_id": None, "tour_count": 0}

    batch_id = result.get("source_id")
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tour_id FROM silver_aa_internal.raw_tours WHERE batch_id = $1::uuid",
            batch_id,
        )

    return {"status": "done", "batch_id": str(batch_id), "tour_count": len(rows)}


# ── GET /admin/upload-history ─────────────────────────────────────────────────

def _count_parse_errors(parse_errors) -> int:
    if not parse_errors:
        return 0
    if isinstance(parse_errors, list):
        return len(parse_errors)
    if isinstance(parse_errors, dict):
        return sum(len(v) if isinstance(v, list) else 1 for v in parse_errors.values())
    try:
        import json as _j
        parsed = _j.loads(parse_errors)
        return len(parsed) if isinstance(parsed, list) else 0
    except Exception:
        return 0


@router.get("/upload-history")
async def get_upload_history(request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        sources = await conn.fetch("""
            SELECT id::text, filename, file_size_kb, row_count, parsed_at,
                   parse_errors, batch_id::text
            FROM silver_aa_internal.raw_sources
            WHERE tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
            ORDER BY parsed_at DESC LIMIT 20
        """)
    return {
        "sources": [
            {
                "id":                s["id"],
                "filename":          s["filename"],
                "file_size_kb":      float(s["file_size_kb"]) if s["file_size_kb"] else None,
                "row_count":         s["row_count"],
                "parsed_at":         str(s["parsed_at"]) if s["parsed_at"] else None,
                "parse_error_count": _count_parse_errors(s["parse_errors"]),
                "batch_id":          s["batch_id"],
            }
            for s in sources
        ],
    }


# ── GET /admin/tours-ready ────────────────────────────────────────────────────

@router.get("/tours-ready")
async def get_tours_ready(request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        tours = await conn.fetch("""
            SELECT t.tour_id::text, t.src_name, t.country, t.ingest_at,
                   t.source_id::text, t.batch_id::text, rs.filename
            FROM silver_aa_internal.raw_tours t
            LEFT JOIN silver_aa_internal.raw_sources rs ON rs.id = t.source_id
            WHERE t.pipeline_status = 'ingested'
            ORDER BY t.ingest_at DESC
        """)
    return {
        "tours": [
            {
                "tour_id":   t["tour_id"],
                "src_name":  t["src_name"],
                "country":   t["country"],
                "ingest_at": str(t["ingest_at"]) if t["ingest_at"] else None,
                "source_id": t["source_id"],
                "batch_id":  t["batch_id"],
                "filename":  t["filename"],
            }
            for t in tours
        ],
        "total": len(tours),
    }


# ── GET /admin/tours — all raw_tours with rewrite_count ──────────────────────

@router.get("/tours")
async def get_all_tours(request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        tours = await conn.fetch("""
            SELECT
                rt.tour_id::text, rt.src_name, rt.country,
                rt.pipeline_status::text, rt.ingest_at,
                rt.batch_id::text, rt.source_id::text,
                rs.filename,
                COUNT(gc.id)         AS rewrite_count,
                MAX(gc.created_at)   AS last_rewritten_at
            FROM silver_aa_internal.raw_tours rt
            LEFT JOIN silver_aa_internal.raw_sources rs ON rs.id = rt.source_id
            LEFT JOIN silver_aa_internal.generated_content gc ON gc.tour_id = rt.tour_id
            GROUP BY rt.tour_id, rt.src_name, rt.country, rt.pipeline_status,
                     rt.ingest_at, rt.batch_id, rt.source_id, rs.filename
            ORDER BY rt.ingest_at DESC
        """)
    return {
        "tours": [
            {
                "tour_id":           t["tour_id"],
                "src_name":          t["src_name"],
                "country":           t["country"],
                "pipeline_status":   t["pipeline_status"],
                "ingest_at":         str(t["ingest_at"]) if t["ingest_at"] else None,
                "source_id":         t["source_id"],
                "batch_id":          t["batch_id"],
                "filename":          t["filename"],
                "rewrite_count":     int(t["rewrite_count"]),
                "last_rewritten_at": str(t["last_rewritten_at"]) if t["last_rewritten_at"] else None,
            }
            for t in tours
        ],
        "total": len(tours),
    }


# ── GET /admin/tours/export ──────────────────────────────────────────────────
# NOTE: /tours/export MUST come before /tours/{tour_id}/... — FastAPI greedy matching

@router.get("/tours/export")
async def export_tours(
    request: Request,
    format: str = "csv",
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    if format not in ("csv", "xlsx"):
        raise HTTPException(status_code=400, detail="format must be csv or xlsx")
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                rt.tour_id::text, rt.src_name, rt.country,
                rt.pipeline_status::text, rt.ingest_at,
                rs.filename,
                COUNT(gc.id)       AS rewrite_count,
                MAX(gc.created_at) AS last_rewritten_at,
                pt.aa_name, pt.aa_subtitle, pt.quality_score, pt.published_at
            FROM silver_aa_internal.raw_tours rt
            LEFT JOIN silver_aa_internal.raw_sources rs ON rs.id = rt.source_id
            LEFT JOIN silver_aa_internal.generated_content gc ON gc.tour_id = rt.tour_id
            LEFT JOIN gold_aa_internal.published_tours pt ON pt.tour_id = rt.tour_id
            GROUP BY rt.tour_id, rt.src_name, rt.country, rt.pipeline_status,
                     rt.ingest_at, rs.filename,
                     pt.aa_name, pt.aa_subtitle, pt.quality_score, pt.published_at
            ORDER BY rt.ingest_at DESC
        """)

    import io
    import pandas as pd
    from fastapi.responses import StreamingResponse

    data = [
        {
            "tour_id":          r["tour_id"],
            "src_name":         r["src_name"],
            "aa_name":          r["aa_name"] or "",
            "aa_subtitle":      r["aa_subtitle"] or "",
            "country":          r["country"] or "",
            "pipeline_status":  r["pipeline_status"],
            "rewrite_count":    int(r["rewrite_count"]),
            "quality_score":    float(r["quality_score"]) if r["quality_score"] else None,
            "filename":         r["filename"] or "",
            "ingest_at":        str(r["ingest_at"]) if r["ingest_at"] else "",
            "last_rewritten_at": str(r["last_rewritten_at"]) if r["last_rewritten_at"] else "",
            "published_at":     str(r["published_at"]) if r["published_at"] else "",
        }
        for r in rows
    ]
    df = pd.DataFrame(data)

    if format == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=master_content_export.csv"},
        )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Master Content")
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=master_content_export.xlsx"},
    )


# ── Review queue (admin alias — no JWT required) ─────────────────────────────

@router.get("/review-queue")
async def admin_review_queue(
    request: Request,
    x_admin_secret: str = Header(None),
    page: int = 1,
    page_size: int = 20,
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    tenant_id = "00000000-0000-0000-0000-000000000001"
    offset = (page - 1) * page_size
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT rq.id, rq.tour_id, rq.generated_content_id,
                   rq.review_status, rq.score_overall, rq.failure_summary, rq.created_at,
                   gc.aa_name, gc.aa_subtitle, gc.aa_summary,
                   gc.seo_title, gc.seo_meta,
                   rt.src_name, rt.country, rt.duration
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
        "data": [
            {k: str(v) if hasattr(v, "hex") else v for k, v in dict(r).items()}
            for r in rows
        ],
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }


# ── Tour version endpoints ────────────────────────────────────────────────────
# NOTE: /versions/{num}/promote MUST come before /versions/{num} — FastAPI greedy matching

@router.post("/tours/{tour_id}/versions/{version_num}/promote")
async def promote_tour_version(
    tour_id: str, version_num: int,
    request: Request, x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        updated = await conn.fetchval("""
            WITH gc AS (
                SELECT gc.id, gc.aa_name, gc.aa_subtitle,
                       qs.score_overall
                FROM silver_aa_internal.generated_content gc
                LEFT JOIN silver_aa_internal.quality_scores qs
                    ON qs.generated_content_id = gc.id
                WHERE gc.tour_id = $1::uuid AND gc.version_num = $2
                LIMIT 1
            )
            UPDATE gold_aa_internal.published_tours pt
            SET generated_content_id = gc.id,
                aa_name              = gc.aa_name,
                aa_subtitle          = gc.aa_subtitle,
                quality_score        = gc.score_overall,
                published_at         = NOW()
            FROM gc
            WHERE pt.tour_id = $1::uuid
            RETURNING pt.id::text
        """, tour_id, version_num)
    if not updated:
        raise HTTPException(status_code=404, detail="Tour or version not found")
    return {"promoted": True, "published_tour_id": updated, "version_num": version_num}



@router.get("/tours/{tour_id}/source")
async def get_tour_source(
    tour_id: str,
    request: Request, x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT rt.tour_id, rt.src_name, rt.src_subtitle, rt.src_summary,
                   rt.src_description, rt.src_highlights, rt.src_itineraries,
                   rt.country, rt.duration, rt.price_raw, rt.ingest_at AS created_at,
                   rt.group_size, rt.period, rt.provider, rt.inclusions, rt.exclusions,
                   sc.top_keywords
            FROM silver_aa_internal.raw_tours rt
            LEFT JOIN LATERAL (
                SELECT top_keywords FROM silver_aa_internal.seo_context
                WHERE tour_id = rt.tour_id
                ORDER BY fetched_at DESC LIMIT 1
            ) sc ON true
            WHERE rt.tour_id = $1::uuid
        """, tour_id)
    if not row:
        raise HTTPException(status_code=404, detail="Source tour not found")
    try:
        highlights = row["src_highlights"]
        if not isinstance(highlights, list):
            highlights = json.loads(highlights) if highlights else []
    except Exception:
        highlights = []
    try:
        keywords = row["top_keywords"]
        if not isinstance(keywords, list):
            keywords = json.loads(keywords) if keywords else []
    except Exception:
        keywords = []
    return {
        "id":             str(row["tour_id"]),
        "version_num":    0,
        "model_id":       "source",
        "quality_score":  None,
        "score_brand":    None,
        "score_seo":      None,
        "score_structure": None,
        "created_at":     row["created_at"].isoformat() if row["created_at"] else None,
        "aa_name":        row["src_name"],
        "aa_subtitle":    row["src_subtitle"],
        "aa_summary":     row["src_summary"],
        "aa_description": row["src_description"],
        "aa_highlights":  highlights,
        "aa_itineraries": row["src_itineraries"],
        "seo_title":      None,
        "seo_meta":       None,
        "brand_name":     "original",
        "seo_mode":       None,
        "dataforseo_used": False,
        "llm_cost_usd":   None,
        "top_keywords":   keywords,
        "country":        row["country"],
        "duration":       row["duration"],
        "group_size":     row["group_size"],
        "price_raw":      row["price_raw"],
        "period":         row["period"],
        "provider":       row["provider"],
        "inclusions":     row["inclusions"],
        "exclusions":     row["exclusions"],
    }

@router.get("/tours/{tour_id}/versions/{version_num}")
async def get_tour_version_detail(
    tour_id: str, version_num: int,
    request: Request, x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT gc.id, gc.version_num, gc.model_editorial AS model_id,
                   qs.score_overall AS quality_score,
                   qs.score_brand, qs.score_seo, qs.score_structure,
                   gc.created_at,
                   gc.aa_name, gc.aa_subtitle, gc.aa_summary, gc.aa_description,
                   gc.aa_highlights, gc.aa_itineraries, gc.seo_title, gc.seo_meta,
                   gc.metadata,
                   tbr.brand_name AS brand_name,
                   sc.top_keywords,
                   rt.country, rt.duration, rt.group_size, rt.price_raw,
                   rt.period, rt.provider, rt.inclusions, rt.exclusions
            FROM silver_aa_internal.generated_content gc
            LEFT JOIN silver_aa_internal.quality_scores qs
                ON qs.generated_content_id = gc.id
            LEFT JOIN shared.tenant_brand_rules tbr
                ON tbr.id = (gc.metadata->>'brand_rule_id')::uuid
            LEFT JOIN silver_aa_internal.raw_tours rt
                ON rt.tour_id = gc.tour_id
            LEFT JOIN LATERAL (
                SELECT top_keywords FROM silver_aa_internal.seo_context
                WHERE tour_id = gc.tour_id
                ORDER BY fetched_at DESC LIMIT 1
            ) sc ON true
            WHERE gc.tour_id = $1::uuid AND gc.version_num = $2
            LIMIT 1
        """, tour_id, version_num)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    meta = {}
    if row["metadata"]:
        try:
            meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else dict(row["metadata"])
        except Exception:
            meta = {}
    highlights = row["aa_highlights"]
    if not isinstance(highlights, list):
        highlights = json.loads(highlights) if highlights else []
    keywords = row["top_keywords"]
    if not isinstance(keywords, list):
        keywords = json.loads(keywords) if keywords else []
    return {
        "id":             str(row["id"]),
        "version_num":    row["version_num"],
        "model_id":       row["model_id"],
        "quality_score":  float(row["quality_score"]) if row["quality_score"] else None,
        "score_brand":    float(row["score_brand"]) if row["score_brand"] else None,
        "score_seo":      float(row["score_seo"]) if row["score_seo"] else None,
        "score_structure": float(row["score_structure"]) if row["score_structure"] else None,
        "created_at":     row["created_at"].isoformat() if row["created_at"] else None,
        "aa_name":        row["aa_name"],
        "aa_subtitle":    row["aa_subtitle"],
        "aa_summary":     row["aa_summary"],
        "aa_description": row["aa_description"],
        "aa_highlights":  highlights,
        "aa_itineraries": row["aa_itineraries"],
        "seo_title":      row["seo_title"],
        "seo_meta":       row["seo_meta"],
        "brand_name":     row["brand_name"] or meta.get("brand_rule_id") and "custom" or "default",
        "seo_mode":       meta.get("seo_mode", "standard"),
        "dataforseo_used": meta.get("dataforseo_used", False),
        "llm_cost_usd":   meta.get("llm_cost_usd"),
        "top_keywords":   keywords,
        "country":        row["country"],
        "duration":       row["duration"],
        "group_size":     row["group_size"],
        "price_raw":      row["price_raw"],
        "period":         row["period"],
        "provider":       row["provider"],
        "inclusions":     row["inclusions"],
        "exclusions":     row["exclusions"],
    }


@router.get("/tours/{tour_id}/versions")
async def list_tour_versions(
    tour_id: str, request: Request, x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT gc.id, gc.version_num, gc.model_editorial AS model_id,
                   qs.score_overall AS quality_score, gc.created_at,
                   (pt.generated_content_id = gc.id) AS is_current
            FROM silver_aa_internal.generated_content gc
            LEFT JOIN silver_aa_internal.quality_scores qs
                ON qs.generated_content_id = gc.id
            LEFT JOIN gold_aa_internal.published_tours pt ON pt.tour_id = gc.tour_id
            WHERE gc.tour_id = $1::uuid
            ORDER BY gc.version_num DESC
        """, tour_id)
    return {"versions": [
        {
            "id":            str(r["id"]),
            "version_num":   r["version_num"],
            "model_id":      r["model_id"],
            "quality_score": float(r["quality_score"]) if r["quality_score"] else None,
            "created_at":    r["created_at"].isoformat() if r["created_at"] else None,
            "is_current":    bool(r["is_current"]),
        }
        for r in rows
    ]}


# ── GET /admin/tours/{tour_id}/history ───────────────────────────────────────

@router.get("/tours/{tour_id}/history")
async def get_tour_history(tour_id: str, request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                gc.id::text, gc.version_num, gc.created_at, gc.status::text,
                gc.model_editorial, gc.brand_rules_version, gc.prompt_version,
                qs.score_overall, qs.score_brand, qs.score_seo, qs.score_structure,
                (gc.metadata->>'llm_cost_usd')::numeric AS cost_usd
            FROM silver_aa_internal.generated_content gc
            LEFT JOIN silver_aa_internal.quality_scores qs
                ON qs.generated_content_id = gc.id
            WHERE gc.tour_id = $1::uuid
            ORDER BY gc.created_at DESC
        """, tour_id)
    return {
        "history": [
            {
                "id":                   r["id"],
                "version_num":          r["version_num"],
                "created_at":           str(r["created_at"]) if r["created_at"] else None,
                "status":               r["status"],
                "model_editorial":      r["model_editorial"],
                "brand_rules_version":  r["brand_rules_version"],
                "prompt_version":       r["prompt_version"],
                "score_overall":        float(r["score_overall"]) if r["score_overall"] is not None else None,
                "score_brand":          float(r["score_brand"])   if r["score_brand"] is not None else None,
                "score_seo":            float(r["score_seo"])     if r["score_seo"] is not None else None,
                "score_structure":      float(r["score_structure"]) if r["score_structure"] is not None else None,
                "llm_model":            r["model_editorial"],
                "cost_usd":             float(r["cost_usd"]) if r["cost_usd"] is not None else None,
            }
            for r in rows
        ]
    }


# ── GET /admin/tours/{tour_id}/detail ────────────────────────────────────────

@router.get("/tours/{tour_id}/detail")
async def get_tour_detail(tour_id: str, request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        raw = await conn.fetchrow("""
            SELECT tour_id::text, src_name, src_subtitle, src_summary, src_description,
                   src_highlights, src_itineraries, country, duration, price_raw,
                   group_size, period, provider, inclusions, exclusions,
                   pipeline_status::text, ingest_at
            FROM silver_aa_internal.raw_tours
            WHERE tour_id = $1::uuid
        """, tour_id)
        if not raw:
            raise HTTPException(status_code=404, detail=f"Tour {tour_id} not found")

        gen = await conn.fetchrow("""
            SELECT gc.id::text, gc.version_num, gc.created_at, gc.status::text,
                   gc.aa_name, gc.aa_subtitle, gc.aa_summary, gc.aa_description,
                   gc.aa_highlights, gc.aa_itineraries, gc.seo_title, gc.seo_meta,
                   gc.seo_keywords_used, gc.model_editorial,
                   qs.score_overall, qs.score_brand, qs.score_seo,
                   qs.score_structure, qs.score_quality
            FROM silver_aa_internal.generated_content gc
            LEFT JOIN silver_aa_internal.quality_scores qs
                ON qs.generated_content_id = gc.id
            WHERE gc.tour_id = $1::uuid
            ORDER BY gc.version_num DESC LIMIT 1
        """, tour_id)

        pub = await conn.fetchrow("""
            SELECT id::text, aa_name, aa_subtitle, quality_score, published_at
            FROM gold_aa_internal.published_tours
            WHERE tour_id = $1::uuid
            ORDER BY published_at DESC LIMIT 1
        """, tour_id)

    def _parse_jsonb(v):
        if v is None:
            return []
        if isinstance(v, (list, dict)):
            return v
        try:
            return __import__("json").loads(v)
        except Exception:
            return []

    return {
        "raw": {
            "tour_id":         raw["tour_id"],
            "src_name":        raw["src_name"],
            "src_subtitle":    raw["src_subtitle"],
            "src_summary":     raw["src_summary"],
            "src_description": raw["src_description"],
            "src_highlights":  _parse_jsonb(raw["src_highlights"]),
            "src_itineraries": raw["src_itineraries"],
            "country":         raw["country"],
            "duration":        raw["duration"],
            "price_raw":       raw["price_raw"],
            "group_size":      raw["group_size"],
            "period":          raw["period"],
            "provider":        raw["provider"],
            "inclusions":      raw["inclusions"],
            "exclusions":      raw["exclusions"],
            "pipeline_status": raw["pipeline_status"],
            "ingest_at":       str(raw["ingest_at"]) if raw["ingest_at"] else None,
        },
        "generated": {
            "id":               gen["id"],
            "version_num":      gen["version_num"],
            "created_at":       str(gen["created_at"]) if gen["created_at"] else None,
            "status":           gen["status"],
            "aa_name":          gen["aa_name"],
            "aa_subtitle":      gen["aa_subtitle"],
            "aa_summary":       gen["aa_summary"],
            "aa_description":   gen["aa_description"],
            "aa_highlights":    _parse_jsonb(gen["aa_highlights"]),
            "aa_itineraries":   gen["aa_itineraries"],
            "seo_title":        gen["seo_title"],
            "seo_meta":         gen["seo_meta"],
            "seo_keywords_used": _parse_jsonb(gen["seo_keywords_used"]),
            "model_editorial":  gen["model_editorial"],
            "score_overall":    float(gen["score_overall"]) if gen["score_overall"] is not None else None,
            "score_brand":      float(gen["score_brand"])   if gen["score_brand"] is not None else None,
            "score_seo":        float(gen["score_seo"])     if gen["score_seo"] is not None else None,
            "score_structure":  float(gen["score_structure"]) if gen["score_structure"] is not None else None,
        } if gen else None,
        "published": {
            "id":            pub["id"],
            "aa_name":       pub["aa_name"],
            "aa_subtitle":   pub["aa_subtitle"],
            "quality_score": float(pub["quality_score"]) if pub["quality_score"] is not None else None,
            "published_at":  str(pub["published_at"]) if pub["published_at"] else None,
        } if pub else None,
    }


# ── PATCH /admin/tours/{tour_id}/country ─────────────────────────────────────

@router.patch("/tours/{tour_id}/country")
async def update_tour_country(
    tour_id: str,
    body: CountryUpdateRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            "UPDATE silver_aa_internal.raw_tours SET country = $1 WHERE tour_id = $2::uuid RETURNING tour_id",
            body.country.strip(), tour_id,
        )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Tour {tour_id} not found")
    return {"tour_id": tour_id, "country": body.country.strip()}


# ── PATCH /admin/tours/{tour_id}/raw ─────────────────────────────────────────

_ALLOWED_RAW_FIELDS = {
    "src_name", "country", "duration", "group_size", "price_raw",
    "period", "provider", "src_summary", "src_highlights",
    "src_itineraries", "src_description", "inclusions", "exclusions",
}
_JSONB_RAW_FIELDS = {"src_highlights"}


@router.patch("/tours/{tour_id}/raw")
async def update_raw_tour_fields(
    tour_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    body = await request.json()
    invalid = set(body.keys()) - _ALLOWED_RAW_FIELDS
    if invalid:
        raise HTTPException(status_code=400, detail=f"Fields not allowed: {sorted(invalid)}")
    if not body:
        raise HTTPException(status_code=400, detail="No fields provided")

    import json as _j_raw
    fields = list(body.keys())
    values = []
    for f in fields:
        v = body[f]
        values.append(_j_raw.dumps(v) if f in _JSONB_RAW_FIELDS and isinstance(v, list) else v)

    set_clause = ", ".join(
        f"{f} = ${i+1}::jsonb" if f in _JSONB_RAW_FIELDS else f"{f} = ${i+1}"
        for i, f in enumerate(fields)
    )
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            f"UPDATE silver_aa_internal.raw_tours SET {set_clause}"
            f" WHERE tour_id = ${len(fields)+1}::uuid RETURNING tour_id",
            *values, tour_id,
        )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Tour {tour_id} not found")
    return {"tour_id": tour_id, "updated": fields}


# ── PATCH /admin/tours/{tour_id}/generated/{content_id} ──────────────────────

_ALLOWED_GC_FIELDS = {
    "aa_name", "aa_subtitle", "aa_summary", "aa_highlights",
    "aa_itineraries", "seo_title", "seo_meta", "seo_keywords_used",
}
_JSONB_GC_FIELDS = {"aa_highlights", "seo_keywords_used"}


@router.patch("/tours/{tour_id}/generated/{content_id}")
async def update_generated_content_fields(
    tour_id: str,
    content_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    body = await request.json()
    invalid = set(body.keys()) - _ALLOWED_GC_FIELDS
    if invalid:
        raise HTTPException(status_code=400, detail=f"Fields not allowed: {sorted(invalid)}")
    if not body:
        raise HTTPException(status_code=400, detail="No fields provided")

    import json as _j_gc
    fields = list(body.keys())
    values = []
    for f in fields:
        v = body[f]
        values.append(_j_gc.dumps(v) if f in _JSONB_GC_FIELDS and isinstance(v, list) else v)

    set_clause = ", ".join(
        f"{f} = ${i+1}::jsonb" if f in _JSONB_GC_FIELDS else f"{f} = ${i+1}"
        for i, f in enumerate(fields)
    )
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            f"UPDATE silver_aa_internal.generated_content SET {set_clause}"
            f" WHERE id = ${len(fields)+1}::uuid AND tour_id = ${len(fields)+2}::uuid RETURNING id",
            *values, content_id, tour_id,
        )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")
    return {"content_id": content_id, "updated": fields}


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
            items = (
                kw_data if isinstance(kw_data, list)
                else (kw_data.get("top_keywords") or [] if isinstance(kw_data, dict) else [])
            )
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


# ── /admin/brands — multi-brand CRUD ─────────────────────────────────────────


class ParseDocxRequest(BaseModel):
    file_base64: str
    filename: str = "brand.docx"


class BrandCreateRequest(BaseModel):
    brand_name: str
    brand_type: Optional[str] = None
    core_idea: Optional[str] = None
    customer_segment: Optional[str] = None
    customer_mindset: Optional[str] = None
    tone_of_voice: Optional[List[str]] = None
    writing_style: Optional[str] = None
    good_examples: Optional[str] = None
    should_write: Optional[str] = None
    forbidden_words: Optional[List[str]] = None
    target_markets: Optional[List[str]] = None
    rewrite_language: str = "en"


def _parse_fw(fw):
    if fw is None:
        return []
    if isinstance(fw, list):
        return fw
    try:
        return json.loads(fw)
    except Exception:
        return []


def _parse_jsonb_list(val) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


@router.get("/brands")
async def list_brands(request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    tenant_id = "00000000-0000-0000-0000-000000000001"
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (COALESCE(brand_name, 'default'))
                    id, brand_name, brand_type, core_idea, version, is_active, updated_at
                FROM shared.tenant_brand_rules
                WHERE tenant_id = $1 AND is_active = true
                ORDER BY COALESCE(brand_name, 'default'), version DESC
            """, tenant_id)
    except Exception as e:
        if "brand_name" in str(e).lower() or "column" in str(e).lower():
            raise HTTPException(
                status_code=503,
                detail="Migration 043 not applied — run 043_add_brand_name_to_brand_rules.sql first",
            )
        raise
    return {"brands": [
        {
            "brand_name":  r["brand_name"] or "default",
            "brand_type":  r["brand_type"],
            "core_idea":   r["core_idea"],
            "version":     r["version"],
            "is_active":   r["is_active"],
            "updated_at":  r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]}


@router.post("/brands/parse-docx")
async def parse_brand_docx(
    body: ParseDocxRequest,
    x_admin_secret: str = Header(None),
):
    """Parse a brand brief DOCX (base64-encoded JSON) and return pre-filled brand fields."""
    verify_admin_secret(x_admin_secret)
    try:
        from docx import Document  # type: ignore
        import io
        content = base64.b64decode(body.file_base64)
        doc = Document(io.BytesIO(content))
    except ImportError:
        raise HTTPException(status_code=501, detail="python-docx not installed on this server")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse DOCX: {e}")

    _FIELD_KEYS = {
        "brand name": "brand_name",
        "brand type": "brand_type",
        "core idea": "core_idea",
        "target market": "target_markets",
        "customer segment": "customer_segment",
        "customer mindset": "customer_mindset",
        "tone of voice": "tone_of_voice",
        "tone": "tone_of_voice",
        "writing style": "writing_style",
        "good example": "good_examples",
        "should write": "should_write",
        "forbidden word": "forbidden_words",
        "forbidden": "forbidden_words",
    }
    _LIST_FIELDS = {"target_markets", "tone_of_voice", "forbidden_words"}

    result: dict = {}
    current_field: str | None = None
    buffer: list[str] = []

    def _flush():
        if current_field and buffer:
            text = "\n".join(buffer).strip()
            if current_field in _LIST_FIELDS:
                items = [line.lstrip("-•·*").strip() for line in text.splitlines() if line.strip()]
                result[current_field] = items or [text]
            else:
                result[current_field] = text

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        lower = text.lower().rstrip(":").strip()
        matched = next((v for k, v in _FIELD_KEYS.items() if lower == k or lower.startswith(k)), None)
        if matched or para.style.name.startswith("Heading"):
            _flush()
            buffer = []
            current_field = matched or current_field
            inline = text.split(":", 1)[1].strip() if ":" in text else ""
            if inline:
                buffer.append(inline)
        else:
            buffer.append(text)

    _flush()

    return {"parsed": result, "filename": body.filename}


@router.get("/brands/{brand_name}")
async def get_brand(brand_name: str, request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    tenant_id = "00000000-0000-0000-0000-000000000001"
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, brand_name, brand_type, core_idea,
                   customer_segment, customer_mindset, voice_examples,
                   style_guide, good_examples, system_prompt, forbidden_words,
                   target_markets, rewrite_language,
                   version, is_active, updated_at, created_at
            FROM shared.tenant_brand_rules
            WHERE tenant_id = $1 AND COALESCE(brand_name, 'default') = $2
            ORDER BY version DESC
        """, tenant_id, brand_name)
    if not rows:
        raise HTTPException(status_code=404, detail=f"Brand '{brand_name}' not found")
    current = rows[0]
    voice = _parse_jsonb_list(current["voice_examples"]) if current["voice_examples"] else []
    history = [
        {
            "version":          r["version"],
            "is_active":        r["is_active"],
            "updated_at":       r["updated_at"].isoformat() if r["updated_at"] else None,
            "brand_type":       r["brand_type"] or "",
            "core_idea":        r["core_idea"] or "",
            "customer_segment": r["customer_segment"] or "",
            "customer_mindset": r["customer_mindset"] or "",
            "tone_of_voice":    _parse_jsonb_list(r["voice_examples"]) if r["voice_examples"] else [],
            "writing_style":    r["style_guide"] or "",
            "should_write":     r["system_prompt"] or "",
            "forbidden_words":  _parse_fw(r["forbidden_words"]),
            "target_markets":   list(r["target_markets"]) if r["target_markets"] else [],
            "rewrite_language": r["rewrite_language"] or "en",
        }
        for r in rows
    ]
    return {
        "brand_name":       current["brand_name"] or "default",
        "brand_type":       current["brand_type"] or "",
        "core_idea":        current["core_idea"] or "",
        "customer_segment": current["customer_segment"] or "",
        "customer_mindset": current["customer_mindset"] or "",
        "tone_of_voice":    voice,
        "writing_style":    current["style_guide"] or "",
        "good_examples":    current["good_examples"] or "",
        "should_write":     current["system_prompt"] or "",
        "forbidden_words":  _parse_fw(current["forbidden_words"]),
        "target_markets":   list(current["target_markets"]) if current["target_markets"] else [],
        "rewrite_language": current["rewrite_language"] or "en",
        "version":          current["version"],
        "is_active":        current["is_active"],
        "updated_at":       current["updated_at"].isoformat() if current["updated_at"] else None,
        "history":          history,
    }


@router.post("/brands")
async def create_brand(
    body: BrandCreateRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    tenant_id = "00000000-0000-0000-0000-000000000001"
    voice = body.tone_of_voice or []
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM shared.tenant_brand_rules WHERE tenant_id=$1 AND brand_name=$2",
            tenant_id, body.brand_name,
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Brand '{body.brand_name}' already exists — use PUT to update")
        await conn.execute(
            "UPDATE shared.tenant_brand_rules SET is_active=false WHERE tenant_id=$1 AND brand_name=$2",
            tenant_id, body.brand_name,
        )
        row = await conn.fetchrow("""
            INSERT INTO shared.tenant_brand_rules
                (tenant_id, brand_name, brand_type, core_idea,
                 customer_segment, customer_mindset, voice_examples,
                 style_guide, good_examples, system_prompt, forbidden_words,
                 target_markets, rewrite_language, version, is_active, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11::jsonb,$12,$13,1,true,NOW())
            RETURNING id, version
        """,
            tenant_id, body.brand_name, body.brand_type, body.core_idea,
            body.customer_segment, body.customer_mindset,
            json.dumps(voice),
            body.writing_style, body.good_examples, body.should_write,
            json.dumps(body.forbidden_words or []),
            body.target_markets or [], body.rewrite_language,
        )
    return {"status": "created", "brand_name": body.brand_name, "version": row["version"]}


@router.put("/brands/{brand_name}")
async def update_brand(
    brand_name: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    body_raw = await request.json()
    pool = request.app.state.pool
    tenant_id = "00000000-0000-0000-0000-000000000001"
    async with pool.acquire() as conn:
        current_ver = await conn.fetchval(
            "SELECT COALESCE(MAX(version),0) FROM shared.tenant_brand_rules WHERE tenant_id=$1 AND brand_name=$2",
            tenant_id, brand_name,
        )
        await conn.execute(
            "UPDATE shared.tenant_brand_rules SET is_active=false WHERE tenant_id=$1 AND brand_name=$2",
            tenant_id, brand_name,
        )
        voice = body_raw.get("tone_of_voice") or []
        row = await conn.fetchrow("""
            INSERT INTO shared.tenant_brand_rules
                (tenant_id, brand_name, brand_type, core_idea,
                 customer_segment, customer_mindset, voice_examples,
                 style_guide, good_examples, system_prompt, forbidden_words,
                 target_markets, rewrite_language, version, is_active, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11::jsonb,$12,$13,$14,true,NOW())
            RETURNING version
        """,
            tenant_id, brand_name,
            body_raw.get("brand_type"), body_raw.get("core_idea"),
            body_raw.get("customer_segment"), body_raw.get("customer_mindset"),
            json.dumps(voice if isinstance(voice, list) else [voice]),
            body_raw.get("writing_style"), body_raw.get("good_examples"),
            body_raw.get("should_write"),
            json.dumps(body_raw.get("forbidden_words") or []),
            body_raw.get("target_markets") or [],
            body_raw.get("rewrite_language", "en"),
            current_ver + 1,
        )
    return {"status": "updated", "brand_name": brand_name, "version": row["version"]}


@router.post("/brands/{brand_name}/activate")
async def activate_brand_version(brand_name: str, request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    body_raw = await request.json()
    version = body_raw.get("version")
    if not version:
        raise HTTPException(status_code=422, detail="version is required")
    pool = request.app.state.pool
    tenant_id = "00000000-0000-0000-0000-000000000001"
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT COUNT(*) FROM shared.tenant_brand_rules"
            " WHERE tenant_id=$1 AND COALESCE(brand_name,'default')=$2 AND version=$3",
            tenant_id, brand_name, int(version),
        )
        if not exists:
            raise HTTPException(status_code=404, detail=f"Brand '{brand_name}' version {version} not found")
        await conn.execute(
            "UPDATE shared.tenant_brand_rules SET is_active=false"
            " WHERE tenant_id=$1 AND COALESCE(brand_name,'default')=$2",
            tenant_id, brand_name,
        )
        await conn.execute(
            "UPDATE shared.tenant_brand_rules SET is_active=true"
            " WHERE tenant_id=$1 AND COALESCE(brand_name,'default')=$2 AND version=$3",
            tenant_id, brand_name, int(version),
        )
    return {"status": "activated", "brand_name": brand_name, "version": version}


@router.delete("/brands/{brand_name}")
async def delete_brand(brand_name: str, request: Request, x_admin_secret: str = Header(None)):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    tenant_id = "00000000-0000-0000-0000-000000000001"
    async with pool.acquire() as conn:
        deleted = await conn.fetchval("""
            DELETE FROM shared.tenant_brand_rules
            WHERE tenant_id=$1 AND brand_name=$2
            RETURNING id
        """, tenant_id, brand_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Brand '{brand_name}' not found")
    return {"status": "deleted", "brand_name": brand_name}


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
