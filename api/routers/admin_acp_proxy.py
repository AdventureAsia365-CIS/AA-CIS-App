# api/routers/admin_acp_proxy.py
# Admin-auth mirror of /v1/acp/* endpoints — mounted under /admin/acp/*.
# Bypasses API Gateway Lambda Authorizer; auth is x-admin-secret only.
# All DB logic mirrors v1_acp.py / v1_acp_gate.py / v1_s4_blog.py / v1_social.py.
import asyncio
import json
import os
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from api.routers.admin import verify_admin_secret

logger = structlog.get_logger()
router = APIRouter(prefix="/admin/acp", tags=["admin-acp"])

_STAGE_MAP = {"s2": 2, "s3": 3, "s4": 4}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dec(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _iso(v):
    return v.isoformat() if v else None


def _jparse(v):
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return v


def _validate_uuid(value: str, field: str = "id") -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail=f"Invalid UUID for {field}: {value!r}")


def _parse_stage(stage: str) -> int:
    s = stage.lower()
    if s not in _STAGE_MAP:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid stage '{stage}'. Must be one of: s2, s3, s4",
        )
    return _STAGE_MAP[s]


# ── Pydantic models ───────────────────────────────────────────────────────────

class GateApproveRequest(BaseModel):
    run_id: str
    notes: str = ""


class GateRejectRequest(BaseModel):
    run_id: str
    reason: str = ""


class BlogHitlRequest(BaseModel):
    action: str  # "approve" | "reject" | "rewrite"
    feedback: Optional[str] = None


class SocialBatchReviewRequest(BaseModel):
    run_id: str
    approved_ids: List[str] = []
    rejected_ids: List[str] = []


# ── GET /admin/acp/runs ───────────────────────────────────────────────────────

@router.get("/runs")
async def list_acp_runs(
    request: Request,
    status: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    offset = (page - 1) * limit

    conditions = ["1=1"]
    params: list = []

    if status:
        params.append(status)
        conditions.append(f"r.status = ${len(params)}")
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
            "status":           g.get("status"),
            "auto_approved":    g.get("auto_approved"),
            "confidence_score": _dec(g.get("confidence_score")),
            "reviewer_id":      g.get("reviewer_id"),
        }

    result = []
    for row in rows:
        gates_raw = _jparse(row["gates_raw"])
        gate_map = {g["stage"]: g for g in (gates_raw or [])}
        result.append({
            "run_id":        row["run_id"],
            "tenant_id":     str(row["tenant_id"]) if row["tenant_id"] else None,
            "country":       row["country"],
            "status":        row["status"],
            "tour_count":    row["tour_count"],
            "quality_avg":   _dec(row["quality_avg"]),
            "cost_usd":      _dec(row["cost_usd"]),
            "started_at":    _iso(row["started_at"]),
            "completed_at":  _iso(row["completed_at"]),
            "error_message": row["error_message"],
            "gate_summary": {
                "gate1": _gate(gate_map, 2),
                "gate2": _gate(gate_map, 3),
                "gate3": _gate(gate_map, 4),
            },
        })

    return result


# ── GET /admin/acp/runs/{run_id}/context — MUST be before /runs/{run_id} ──────

@router.get("/runs/{run_id}/context")
async def get_run_context(
    run_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    run_id = _validate_uuid(run_id, "run_id")
    pool = request.app.state.pool

    from api.services.run_context_db import get_run_context_validated
    from api.schemas.run_context import RunContextValidationError

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
            "tour_id":             r["tour_id"],
            "src_name":            r["src_name"],
            "country":             r["country"],
            "duration":            r["duration"],
            "price_raw":           r["price_raw"],
            "aa_name":             r["aa_name"],
            "quality_score":       _dec(r["quality_score"]),
            "score_brand":         _dec(r["score_brand"]),
            "score_seo":           _dec(r["score_seo"]),
            "model_editorial":     r["model_editorial"],
            "version_num":         r["version_num"],
            "brand_rules_version": r["brand_rules_version"],
            "published_at":        _iso(r["published_at"]),
            "s3_gold_path":        r["s3_gold_path"],
        }
        for r in cis_rows
    ]

    blog_drafts = [
        {
            "draft_id":           r["draft_id"],
            "title":              r["title"],
            "slug":               r["slug"],
            "word_count":         r["word_count"],
            "evaluator_score":    _dec(r["evaluator_score"]),
            "validation_passed":  r["validation_passed"],
            "hitl_gate3_status":  r["hitl_gate3_status"],
            "cms_publish_status": r["cms_publish_status"],
            "featured_image_url": r["featured_image_url"],
            "status":             r["status"],
            "created_at":         _iso(r["created_at"]),
        }
        for r in draft_rows
    ]

    return {
        "run_id":    run_row["run_id"],
        "tenant_id": str(run_row["tenant_id"]) if run_row["tenant_id"] else None,
        "country":   country,
        "s0": {"brand_brief": _ctx_field("brand_brief")},
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
        "s4": {"blog_drafts": blog_drafts},
    }


# ── GET /admin/acp/runs/{run_id} ──────────────────────────────────────────────

@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    run_id = _validate_uuid(run_id, "run_id")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                r.run_id::text, r.tenant_id, r.country, r.status,
                r.tour_count, r.quality_avg, r.cost_usd, r.total_llm_cost_usd,
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
        "run_id":             row["run_id"],
        "tenant_id":          str(row["tenant_id"]) if row["tenant_id"] else None,
        "country":            row["country"],
        "status":             row["status"],
        "tour_count":         row["tour_count"],
        "quality_avg":        _dec(row["quality_avg"]),
        "cost_usd":           _dec(row["cost_usd"]),
        "total_llm_cost_usd": _dec(row["total_llm_cost_usd"]),
        "started_at":         _iso(row["started_at"]),
        "completed_at":       _iso(row["completed_at"]),
        "error_message":      row["error_message"],
        "metadata":           _jparse(row["metadata"]),
        "run_config":         _jparse(row["run_config"]),
        "s1_manifest_key":    row["s1_manifest_key"],
        "s2_report_key":      row["s2_report_key"],
        "s3_plan_key":        row["s3_plan_key"],
        "s4_blog_key":        row["s4_blog_key"],
        "gates":              gates,
    }


# ── GET /admin/acp/s4/blog/drafts ────────────────────────────────────────────

@router.get("/s4/blog/drafts")
async def list_blog_drafts(
    request: Request,
    run_id: Optional[str] = Query(None),
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        if run_id:
            run_id = _validate_uuid(run_id, "run_id")
            rows = await conn.fetch("""
                SELECT draft_id::text, run_id::text, title, slug, word_count,
                       evaluator_score, validation_passed, hitl_gate3_status,
                       seo_score, review_flags::text, status, created_at
                FROM acp_silver_s4.blog_drafts
                WHERE run_id = $1::uuid
                ORDER BY created_at
            """, run_id)
        else:
            rows = await conn.fetch("""
                SELECT draft_id::text, run_id::text, title, slug, word_count,
                       evaluator_score, validation_passed, hitl_gate3_status,
                       seo_score, review_flags::text, status, created_at
                FROM acp_silver_s4.blog_drafts
                ORDER BY created_at DESC LIMIT 50
            """)

    return [
        {
            "draft_id":          r["draft_id"],
            "run_id":            r["run_id"],
            "title":             r["title"],
            "slug":              r["slug"],
            "word_count":        r["word_count"],
            "evaluator_score":   _dec(r["evaluator_score"]),
            "validation_passed": r["validation_passed"],
            "hitl_gate3_status": r["hitl_gate3_status"],
            "seo_score":         _dec(r["seo_score"]),
            "review_flags":      _jparse(r["review_flags"]),
            "status":            r["status"],
            "created_at":        _iso(r["created_at"]),
        }
        for r in rows
    ]


# ── PATCH /admin/acp/s4/blog/drafts/{draft_id}/hitl ──────────────────────────
# NOTE: this specific path must come before any /{draft_id} catch-all

@router.patch("/s4/blog/drafts/{draft_id}/hitl")
async def blog_hitl_decision(
    draft_id: str,
    body: BlogHitlRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    draft_id = _validate_uuid(draft_id, "draft_id")

    _status_map = {
        "approve": "msthy_approved",
        "reject":  "rejected",
        "rewrite": "rewrite_requested",
    }
    if body.action not in _status_map:
        raise HTTPException(
            status_code=422,
            detail=f"action must be one of: {list(_status_map)}",
        )
    new_status = _status_map[body.action]

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        updated = await conn.fetchval("""
            UPDATE acp_silver_s4.blog_drafts
            SET hitl_gate3_status = $1,
                hitl_reviewer_id  = 'admin',
                hitl_decided_at   = NOW()
            WHERE draft_id = $2::uuid
            RETURNING draft_id::text
        """, new_status, draft_id)

    if not updated:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")

    logger.info("admin_blog_hitl", draft_id=draft_id, action=body.action, new_status=new_status)
    return {"success": True, "draft_id": updated, "new_status": new_status}


# ── GET /admin/acp/s4/social ──────────────────────────────────────────────────

@router.get("/s4/social")
async def list_social_content(
    request: Request,
    run_id: Optional[str] = Query(None),
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        if run_id:
            run_id = _validate_uuid(run_id, "run_id")
            rows = await conn.fetch("""
                SELECT social_id::text AS id, run_id::text, tour_name, channel,
                       hitl_gate_3_social_status AS status,
                       formula_used AS formula, mode,
                       validation_status, content_text AS content, quality_score,
                       created_at
                FROM acp_silver_s4.social_content
                WHERE run_id = $1::uuid
                ORDER BY created_at
            """, run_id)
        else:
            rows = await conn.fetch("""
                SELECT social_id::text AS id, run_id::text, tour_name, channel,
                       hitl_gate_3_social_status AS status,
                       formula_used AS formula, mode,
                       validation_status, content_text AS content, quality_score,
                       created_at
                FROM acp_silver_s4.social_content
                ORDER BY created_at DESC LIMIT 50
            """)

    return [
        {
            "id":                r["id"],
            "run_id":            r["run_id"],
            "tour_name":         r["tour_name"],
            "channel":           r["channel"],
            "status":            r["status"],
            "formula":           r["formula"],
            "mode":              r["mode"],
            "validation_status": r["validation_status"],
            "content":           r["content"],
            "quality_score":     _dec(r["quality_score"]),
            "created_at":        _iso(r["created_at"]),
        }
        for r in rows
    ]


# ── POST /admin/acp/s4/social/batch-review ───────────────────────────────────

@router.post("/s4/social/batch-review")
async def social_batch_review(
    body: SocialBatchReviewRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    approved_count = len(body.approved_ids)
    rejected_count = len(body.rejected_ids)

    async with pool.acquire() as conn:
        async with conn.transaction():
            if body.approved_ids:
                await conn.execute("""
                    UPDATE acp_silver_s4.social_content
                    SET hitl_gate_3_social_status = 'approved',
                        hitl_reviewer_id           = 'admin',
                        hitl_decided_at            = NOW()
                    WHERE social_id = ANY($1::uuid[])
                """, body.approved_ids)
            if body.rejected_ids:
                await conn.execute("""
                    UPDATE acp_silver_s4.social_content
                    SET hitl_gate_3_social_status = 'rejected',
                        hitl_reviewer_id           = 'admin',
                        hitl_decided_at            = NOW()
                    WHERE social_id = ANY($1::uuid[])
                """, body.rejected_ids)

    logger.info("admin_social_batch_review", approved=approved_count, rejected=rejected_count)
    return {"approved": approved_count, "rejected": rejected_count}


# ── POST /admin/acp/gate/{stage}/approve ─────────────────────────────────────

@router.post("/gate/{stage}/approve")
async def gate_approve(
    stage: str,
    body: GateApproveRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    stage_int = _parse_stage(stage)
    run_id = _validate_uuid(body.run_id, "run_id")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        run_row = await conn.fetchrow(
            "SELECT tenant_id FROM acp_shared.acp_runs WHERE run_id = $1::uuid",
            run_id,
        )
        if not run_row:
            raise HTTPException(status_code=404, detail=f"run_id {run_id} not found")
        run_tenant = str(run_row["tenant_id"])

        hitl_row = await conn.fetchrow("""
            SELECT hitl_id, status FROM acp_shared.acp_hitl_requests
            WHERE run_id = $1::uuid AND stage = $2
            ORDER BY created_at DESC LIMIT 1
        """, run_id, stage_int)
        if not hitl_row:
            raise HTTPException(
                status_code=404,
                detail=f"No Gate {stage_int} HITL request for run_id {run_id}",
            )
        if hitl_row["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"HITL request is already '{hitl_row['status']}' — cannot approve",
            )

        async with conn.transaction():
            await conn.execute("""
                UPDATE acp_shared.acp_hitl_requests
                SET status = 'approved', resolved_at = NOW(), reviewer_id = 'admin'
                WHERE hitl_id = $1
            """, hitl_row["hitl_id"])
            await conn.execute("""
                INSERT INTO acp_shared.audit_log
                    (tenant_id, actor, action, resource_type, resource_id, actor_type, details)
                VALUES ($1, $2, $3, 'acp_hitl_request', $4,
                        'tenant_admin'::acp_shared.audit_actor_type, $5::jsonb)
            """,
                run_tenant, "admin", f"hitl.gate{stage_int}.approve", run_id,
                json.dumps({
                    "stage":   stage,
                    "hitl_id": str(hitl_row["hitl_id"]),
                    "notes":   body.notes,
                }),
            )

    logger.info("admin_gate_approved", run_id=run_id, stage=stage)
    return {"run_id": run_id, "stage": stage, "status": "approved"}


# ── POST /admin/acp/gate/{stage}/reject ──────────────────────────────────────

@router.post("/gate/{stage}/reject")
async def gate_reject(
    stage: str,
    body: GateRejectRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    stage_int = _parse_stage(stage)
    run_id = _validate_uuid(body.run_id, "run_id")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        run_row = await conn.fetchrow(
            "SELECT tenant_id FROM acp_shared.acp_runs WHERE run_id = $1::uuid",
            run_id,
        )
        if not run_row:
            raise HTTPException(status_code=404, detail=f"run_id {run_id} not found")
        run_tenant = str(run_row["tenant_id"])

        hitl_row = await conn.fetchrow("""
            SELECT hitl_id, status FROM acp_shared.acp_hitl_requests
            WHERE run_id = $1::uuid AND stage = $2
            ORDER BY created_at DESC LIMIT 1
        """, run_id, stage_int)
        if not hitl_row:
            raise HTTPException(
                status_code=404,
                detail=f"No Gate {stage_int} HITL request for run_id {run_id}",
            )
        if hitl_row["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"HITL request is already '{hitl_row['status']}' — cannot reject",
            )

        async with conn.transaction():
            await conn.execute("""
                UPDATE acp_shared.acp_hitl_requests
                SET status = 'rejected', resolved_at = NOW(),
                    reviewer_id = 'admin', reviewer_notes = $2
                WHERE hitl_id = $1
            """, hitl_row["hitl_id"], body.reason)
            await conn.execute("""
                INSERT INTO acp_shared.audit_log
                    (tenant_id, actor, action, resource_type, resource_id, actor_type, details)
                VALUES ($1, $2, $3, 'acp_hitl_request', $4,
                        'tenant_admin'::acp_shared.audit_actor_type, $5::jsonb)
            """,
                run_tenant, "admin", f"hitl.gate{stage_int}.reject", run_id,
                json.dumps({
                    "stage":   stage,
                    "hitl_id": str(hitl_row["hitl_id"]),
                    "notes":   body.reason,
                }),
            )

    if body.reason:
        from services.acp_shared import h3_rule_extractor as _h3
        asyncio.create_task(
            _h3.extract_and_save_rule(
                pool=pool,
                hitl_id=str(hitl_row["hitl_id"]),
                run_id=run_id,
                gate_number=stage_int,
                reviewer_notes=body.reason,
            )
        )

    logger.info("admin_gate_rejected", run_id=run_id, stage=stage)
    return {"run_id": run_id, "stage": stage, "status": "rejected", "reason": body.reason}
