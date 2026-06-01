"""
GET /v1/acp/s1-keywords — keywords used in S1 for a country (S2 dedup input).
GET /v1/acp/runs         — list all ACP pipeline runs with gate summary.
GET /v1/acp/runs/{run_id}/context — full stage I/O for one run (S0→S3 + S4 blog drafts).
GET /v1/acp/runs/{run_id}         — run detail with all gate decisions.

NOTE: /runs/{run_id}/context MUST be declared before /runs/{run_id} — FastAPI greedy match.
"""
import json as _json
import os
import structlog
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from typing import Optional

from api.routers.auth import verify_jwt as _verify_jwt
from api.services.run_context_db import get_run_context_validated
from api.schemas.run_context import RunContextValidationError

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/acp", tags=["acp"])


def _get_tenant(
    request: Request,
    credentials: Optional[_Creds] = Depends(_HTTPBearer(auto_error=False)),
):
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


@router.get("/s1-keywords")
async def get_s1_keywords(
    country: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """
    Return deduplicated keywords used in S1 for the given country.
    S2 calls this to avoid keyword cannibalization across runs.
    """
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT sc.top_keywords, sc.keyword_search
            FROM silver_aa_internal.seo_context sc
            JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = sc.tour_id
            WHERE LOWER(rt.country) = LOWER($1)
              AND sc.top_keywords IS NOT NULL
            ORDER BY sc.fetched_at DESC
            LIMIT 20
        """, country)

    keywords: list = []
    seen: set = set()
    for row in rows:
        kw_data = row["top_keywords"]
        if isinstance(kw_data, str):
            try:
                kw_data = _json.loads(kw_data)
            except Exception:
                continue
        if isinstance(kw_data, list):
            items = kw_data
        elif isinstance(kw_data, dict):
            items = kw_data.get("top_keywords") or []
        else:
            items = []
        for item in items:
            kw = item.get("keyword") if isinstance(item, dict) else str(item)
            if kw and kw not in seen:
                seen.add(kw)
                keywords.append({
                    "keyword":       kw,
                    "search_volume": item.get("search_volume") if isinstance(item, dict) else None,
                })

    logger.info("s1_keywords_fetched", country=country, keyword_count=len(keywords))
    return {
        "country":       country,
        "keyword_count": len(keywords),
        "keywords":      keywords,
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _validate_uuid(value: str, field: str = "run_id") -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail=f"Invalid UUID for {field}: {value!r}")


def _dec(v):
    """Convert Decimal/None to float/None for JSON."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _iso(v):
    return v.isoformat() if v else None


def _jparse(v):
    """asyncpg returns jsonb as dict/list already; handle str fallback."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    try:
        return _json.loads(v)
    except Exception:
        return v


# ── GET /v1/acp/runs ──────────────────────────────────────────────────────────

@router.get("/runs")
async def list_acp_runs(
    request: Request,
    status: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    tenant=Depends(_get_tenant),
):
    """List ACP pipeline runs with per-gate summary (gate1=stage2, gate2=stage3, gate3=stage4)."""
    pool = request.app.state.pool
    offset = (page - 1) * limit

    conditions = ["1=1"]
    params: list = []

    if status:
        params.append(status)
        conditions.append(f"r.status = ${len(params)}")
    if tenant_id:
        params.append(tenant_id)
        conditions.append(f"r.tenant_id = ${len(params)}")
    if country:
        params.append(country)
        conditions.append(f"LOWER(r.country) = LOWER(${len(params)})")

    params.extend([limit, offset])
    lp, op = len(params) - 1, len(params)
    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT
                r.run_id::text, r.tenant_id, r.country, r.status,
                r.tour_count, r.quality_avg, r.cost_usd,
                r.started_at, r.completed_at, r.error_message,
                json_agg(
                    json_build_object(
                        'stage', h.stage,
                        'status', h.status,
                        'auto_approved', h.auto_approved,
                        'confidence_score', h.confidence_score,
                        'reviewer_id', h.reviewer_id
                    ) ORDER BY h.stage
                ) FILTER (WHERE h.hitl_id IS NOT NULL) AS gates_raw
            FROM acp_shared.acp_runs r
            LEFT JOIN acp_shared.acp_hitl_requests h ON h.run_id = r.run_id
            WHERE {where}
            GROUP BY r.run_id, r.started_at
            ORDER BY r.started_at DESC NULLS LAST
            LIMIT ${lp} OFFSET ${op}
        """, *params)

    def _gate(gate_map, stage_int):
        g = gate_map.get(stage_int)
        if not g:
            return None
        return {
            "status": g.get("status"),
            "auto_approved": g.get("auto_approved"),
            "confidence_score": _dec(g.get("confidence_score")),
            "reviewer_id": g.get("reviewer_id"),
        }

    result = []
    for row in rows:
        gates_raw = _jparse(row["gates_raw"])
        gate_map = {g["stage"]: g for g in (gates_raw or [])}
        result.append({
            "run_id":      row["run_id"],
            "tenant_id":   row["tenant_id"],
            "country":     row["country"],
            "status":      row["status"],
            "tour_count":  row["tour_count"],
            "quality_avg": _dec(row["quality_avg"]),
            "cost_usd":    _dec(row["cost_usd"]),
            "started_at":  _iso(row["started_at"]),
            "completed_at": _iso(row["completed_at"]),
            "error_message": row["error_message"],
            "gate_summary": {
                "gate1": _gate(gate_map, 2),
                "gate2": _gate(gate_map, 3),
                "gate3": _gate(gate_map, 4),
            },
        })

    logger.info("list_acp_runs", count=len(result), page=page)
    return result


# ── GET /v1/acp/runs/{run_id}/context — MUST be before /runs/{run_id} ────────

@router.get("/runs/{run_id}/context")
async def get_run_context(
    run_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """
    Full stage I/O for one pipeline run — S0→S3 from acp_run_context + S4 blog drafts.
    CIS tours for S1 panel queried by run country from silver/gold_aa_internal.
    Returns null for any stage not yet reached.
    """
    run_id = _validate_uuid(run_id)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        run_row = await conn.fetchrow(
            "SELECT run_id::text, tenant_id, country FROM acp_shared.acp_runs WHERE run_id=$1::uuid",
            run_id,
        )
        if not run_row:
            raise HTTPException(status_code=404, detail=f"run_id {run_id} not found")

        try:
            ctx = await get_run_context_validated(conn, run_id)
        except RunContextValidationError:
            ctx = None

        country = run_row["country"]

        # CIS tours for S1 panel — latest version per tour for this country
        cis_rows = []
        if country:
            cis_rows = await conn.fetch("""
                SELECT
                    rt.tour_id::text, rt.src_name, rt.country, rt.duration, rt.price_raw,
                    pt.aa_name, pt.quality_score, pt.published_at, pt.s3_gold_path,
                    gc.model_editorial, gc.version_num, gc.brand_rules_version,
                    qs.score_overall, qs.score_brand, qs.score_seo
                FROM silver_aa_internal.raw_tours rt
                JOIN gold_aa_internal.published_tours pt ON pt.tour_id = rt.tour_id
                LEFT JOIN silver_aa_internal.generated_content gc
                    ON gc.tour_id = rt.tour_id
                    AND gc.version_num = (
                        SELECT MAX(gc2.version_num)
                        FROM silver_aa_internal.generated_content gc2
                        WHERE gc2.tour_id = rt.tour_id
                    )
                LEFT JOIN silver_aa_internal.quality_scores qs
                    ON qs.generated_content_id = gc.id
                WHERE LOWER(rt.country) = LOWER($1)
                ORDER BY pt.quality_score DESC NULLS LAST
            """, country)

        # S4 blog drafts for this run
        draft_rows = await conn.fetch("""
            SELECT draft_id::text, run_id::text, title, slug, word_count,
                   evaluator_score, validation_passed, hitl_gate3_status,
                   cms_publish_status, featured_image_url, status, created_at
            FROM acp_silver_s4.blog_drafts
            WHERE run_id=$1::uuid
            ORDER BY created_at
        """, run_id)

    def _ctx_field(field):
        return getattr(ctx, field, None) if ctx else None

    cis_tours = [
        {
            "tour_id":            r["tour_id"],
            "src_name":           r["src_name"],
            "country":            r["country"],
            "duration":           r["duration"],
            "price_raw":          r["price_raw"],
            "aa_name":            r["aa_name"],
            "quality_score":      _dec(r["quality_score"]),
            "score_brand":        _dec(r["score_brand"]),
            "score_seo":          _dec(r["score_seo"]),
            "model_editorial":    r["model_editorial"],
            "version_num":        r["version_num"],
            "brand_rules_version": r["brand_rules_version"],
            "published_at":       _iso(r["published_at"]),
            "s3_gold_path":       r["s3_gold_path"],
        }
        for r in cis_rows
    ]

    blog_drafts = [
        {
            "draft_id":          r["draft_id"],
            "title":             r["title"],
            "slug":              r["slug"],
            "word_count":        r["word_count"],
            "evaluator_score":   _dec(r["evaluator_score"]),
            "validation_passed": r["validation_passed"],
            "hitl_gate3_status": r["hitl_gate3_status"],
            "cms_publish_status": r["cms_publish_status"],
            "featured_image_url": r["featured_image_url"],
            "status":            r["status"],
            "created_at":        _iso(r["created_at"]),
        }
        for r in draft_rows
    ]

    return {
        "run_id":    run_row["run_id"],
        "tenant_id": run_row["tenant_id"],
        "country":   country,
        "s0": {
            "brand_brief": _ctx_field("brand_brief"),
        },
        "s1": {
            "keywords_used": _ctx_field("s1_keywords_used"),
            "cis_tours":     cis_tours,
        },
        "s2": {
            "keyword_research":  _ctx_field("s2_keyword_research"),
            "visibility_report": _ctx_field("s2_visibility_report"),
            "keyword_clusters":  _ctx_field("s2_keyword_clusters"),
            "market_preference": _ctx_field("s2_market_preference"),
            "aa_tour_matches":   _ctx_field("s2_aa_tour_matches"),
            "confidence_score":  _dec(ctx.s2_confidence_score) if ctx else None,
        },
        "s3": {
            "content_calendar": _ctx_field("s3_content_calendar"),
            "ads_plan":         _ctx_field("s3_ads_plan"),
            "funnel_mix":       _ctx_field("s3_funnel_mix"),
        },
        "s4": {
            "blog_drafts": blog_drafts,
        },
    }


# ── GET /v1/acp/runs/{run_id} ─────────────────────────────────────────────────

@router.get("/runs/{run_id}")
async def get_acp_run(
    run_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Full run detail with all gate decisions."""
    run_id = _validate_uuid(run_id)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                r.run_id::text, r.tenant_id, r.country, r.status,
                r.tour_count, r.quality_avg, r.cost_usd,
                r.started_at, r.completed_at, r.error_message,
                r.metadata, r.run_config,
                r.s1_manifest_key, r.s2_report_key, r.s3_plan_key, r.s4_blog_key
            FROM acp_shared.acp_runs r
            WHERE r.run_id = $1::uuid
        """, run_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"run_id {run_id} not found")

        gate_rows = await conn.fetch("""
            SELECT
                hitl_id::text, stage, gate_type, status,
                auto_approved, confidence_score,
                reviewer_id, reviewer_notes,
                rejection_note_structured, rule_created_id::text,
                reviewer_type, created_at, resolved_at
            FROM acp_shared.acp_hitl_requests
            WHERE run_id = $1::uuid
            ORDER BY stage, created_at
        """, run_id)

    gates = [
        {
            "hitl_id":                   g["hitl_id"],
            "stage":                     g["stage"],
            "gate_type":                 g["gate_type"],
            "status":                    g["status"],
            "auto_approved":             g["auto_approved"],
            "confidence_score":          _dec(g["confidence_score"]),
            "reviewer_id":               g["reviewer_id"],
            "reviewer_notes":            g["reviewer_notes"],
            "rejection_note_structured": _jparse(g["rejection_note_structured"]),
            "rule_created_id":           g["rule_created_id"],
            "reviewer_type":             g["reviewer_type"],
            "created_at":                _iso(g["created_at"]),
            "resolved_at":               _iso(g["resolved_at"]),
        }
        for g in gate_rows
    ]

    return {
        "run_id":          row["run_id"],
        "tenant_id":       row["tenant_id"],
        "country":         row["country"],
        "status":          row["status"],
        "tour_count":      row["tour_count"],
        "quality_avg":     _dec(row["quality_avg"]),
        "cost_usd":        _dec(row["cost_usd"]),
        "started_at":      _iso(row["started_at"]),
        "completed_at":    _iso(row["completed_at"]),
        "error_message":   row["error_message"],
        "metadata":        _jparse(row["metadata"]),
        "run_config":      _jparse(row["run_config"]),
        "s1_manifest_key": row["s1_manifest_key"],
        "s2_report_key":   row["s2_report_key"],
        "s3_plan_key":     row["s3_plan_key"],
        "s4_blog_key":     row["s4_blog_key"],
        "gates":           gates,
    }
