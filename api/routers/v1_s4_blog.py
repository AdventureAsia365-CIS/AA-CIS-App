"""
/v1/acp/s4/blog — S4 Blog Engine API (AA-46).

Routes (specific before parameterized):
  POST  /v1/acp/s4/blog/runs                      → trigger pipeline
  GET   /v1/acp/s4/blog/runs/{run_id}             → poll run status
  GET   /v1/acp/s4/blog/drafts                    → list drafts
  GET   /v1/acp/s4/blog/drafts/{draft_id}         → get draft
  PATCH /v1/acp/s4/blog/drafts/{draft_id}/hitl    → HITL approve/reject
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from pydantic import BaseModel

from api.routers.auth import verify_jwt as _verify_jwt
from services.acp_s4_blog.cms.publisher import publish_draft_to_cms as _cms_publish

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/acp/s4/blog", tags=["S4 Blog Engine"])


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_admin(
    request: Request,
    credentials: Optional[_Creds] = Depends(_HTTPBearer(auto_error=False)),
):
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    if admin_secret and request.headers.get("X-Admin-Secret") == admin_secret:
        return {"sub": "00000000-0000-0000-0000-000000000001", "role": "admin"}
    if credentials:
        try:
            return _verify_jwt(credentials.credentials)
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


def _get_pool(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="DB not ready")
    return pool


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
    return d


# ── Pydantic models ───────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    tenant_id: str
    primary_keyword: str
    outline: list[str] = []
    target_keywords: list[str] = []
    title: str
    calendar_item_id: Optional[str] = None


class HitlRequest(BaseModel):
    status: str           # "approved" | "rejected"
    reviewer_id: str
    reviewer_role: str = "trang"  # "trang" | "ms_thu"
    notes: Optional[str] = None


# ── Background pipeline task ──────────────────────────────────────────────────

async def _run_pipeline(run_id: str, pool: asyncpg.Pool, initial_state: dict) -> None:
    """Background task: run S4 graph and update acp_runs on completion."""
    from services.acp_s4.graph import build_s4_graph

    try:
        async with pool.acquire() as db:
            db_rules_rows = await db.fetch(
                "SELECT rule_id::text, rule_type, pattern, action_value "
                "FROM acp_shared.acp_output_rules WHERE is_active = TRUE AND stage IS NULL"
            )
            db_rules = [dict(r) for r in db_rules_rows]

            state = {
                **initial_state,
                "db": db,
                "db_rules": db_rules,
                "content_md": "",
                "seo_title": "",
                "seo_meta": "",
                "slug": "",
                "review_flags": [],
                "rules_applied": [],
                "evaluator_score": None,
                "evaluator_input_hash": None,
                "validation_passed": None,
                "validation_score": None,
                "failing_checks": [],
                "repair_targets": [],
                "seo_score": None,
                "seo_issues": [],
                "rewrite_count": 0,
                "rewrite_feedback": "",
                "error": "",
                "status": "briefing",
                "draft_id": None,
            }

            graph = build_s4_graph()
            final = await graph.ainvoke(state)
            outcome = final.get("status", "unknown")
            draft_id = final.get("draft_id")
            error_msg = final.get("error", "")

            await db.execute(
                "UPDATE acp_shared.acp_runs SET status=$1, s4_blog_key=$2, "
                "completed_at=$3, error_message=$4 WHERE run_id=$5::uuid",
                "completed" if outcome == "done" else "failed",
                draft_id,
                datetime.now(timezone.utc),
                error_msg or None,
                run_id,
            )
            logger.info("s4_pipeline_done", run_id=run_id, status=outcome, draft_id=draft_id)
    except Exception as e:
        logger.error("s4_pipeline_error", run_id=run_id, error=str(e))
        async with pool.acquire() as db:
            await db.execute(
                "UPDATE acp_shared.acp_runs SET status='failed', completed_at=$1, error_message=$2 "
                "WHERE run_id=$3::uuid",
                datetime.now(timezone.utc), str(e), run_id,
            )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/runs", status_code=202)
async def create_run(
    request: Request,
    body: RunRequest,
    _auth=Depends(_get_admin),
):
    pool = _get_pool(request)
    run_id = str(uuid4())
    calendar_item_id = body.calendar_item_id or str(uuid4())

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO acp_shared.acp_runs (run_id, tenant_id, country, status, started_at) "
            "VALUES ($1::uuid, $2, 'S4', 'running', NOW())",
            run_id, body.tenant_id,
        )

    initial_state = {
        "run_id": run_id,
        "tenant_id": body.tenant_id,
        "calendar_item_id": calendar_item_id,
        "primary_keyword": body.primary_keyword,
        "outline": body.outline,
        "target_keywords": body.target_keywords,
        "title": body.title,
    }
    asyncio.create_task(_run_pipeline(run_id, pool, initial_state))
    logger.info("s4_run_queued", run_id=run_id, keyword=body.primary_keyword)
    return {"run_id": run_id, "status": "queued"}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
    _auth=Depends(_get_admin),
):
    try:
        UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid run_id UUID")

    pool = _get_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT run_id::text, tenant_id, status, s4_blog_key, "
            "started_at, completed_at, error_message "
            "FROM acp_shared.acp_runs WHERE run_id=$1::uuid",
            run_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return _row_to_dict(row)


@router.get("/drafts")
async def list_drafts(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    hitl_gate3_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _auth=Depends(_get_admin),
):
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        q = (
            "SELECT draft_id::text, run_id::text, tenant_id, title, slug, word_count, "
            "evaluator_score, validation_passed, validation_score, hitl_gate3_status, "
            "rewrite_count, status, created_at "
            "FROM acp_silver_s4.blog_drafts WHERE 1=1"
        )
        params: list = []
        if tenant_id:
            params.append(tenant_id)
            q += f" AND tenant_id = ${len(params)}"
        if hitl_gate3_status:
            params.append(hitl_gate3_status)
            q += f" AND hitl_gate3_status = ${len(params)}"
        params.append(limit)
        q += f" ORDER BY created_at DESC LIMIT ${len(params)}"
        rows = await conn.fetch(q, *params)
    return [_row_to_dict(r) for r in rows]


@router.get("/drafts/{draft_id}")
async def get_draft(
    draft_id: str,
    request: Request,
    _auth=Depends(_get_admin),
):
    try:
        UUID(draft_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid draft_id UUID")

    pool = _get_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT draft_id::text, run_id::text, tenant_id, calendar_item_id::text, "
            "title, slug, content_md, word_count, seo_title, seo_meta, target_keywords, "
            "status, evaluator_score, evaluator_input_hash, review_flags, rules_applied, "
            "validation_passed, validation_score, failing_checks, repair_targets, "
            "seo_score, seo_issues, hitl_gate3_status, hitl_reviewer_id, hitl_decided_at, "
            "rewrite_count, pipeline_version, created_at, updated_at "
            "FROM acp_silver_s4.blog_drafts WHERE draft_id=$1::uuid",
            draft_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _row_to_dict(row)


@router.patch("/drafts/{draft_id}/hitl")
async def hitl_decision(
    draft_id: str,
    request: Request,
    body: HitlRequest,
    _auth=Depends(_get_admin),
):
    if body.status not in ("approved", "rejected"):
        raise HTTPException(status_code=422, detail="status must be 'approved' or 'rejected'")
    if body.reviewer_role not in ("trang", "ms_thu"):
        raise HTTPException(status_code=422, detail="reviewer_role must be 'trang' or 'ms_thu'")
    try:
        UUID(draft_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid draft_id UUID")

    # Map reviewer_role + decision → Gate 3 status
    _status_map = {
        ("trang",  "approved"): "trang_approved",
        ("trang",  "rejected"): "trang_rejected",
        ("ms_thu", "approved"): "msthy_approved",
        ("ms_thu", "rejected"): "msthy_rejected",
    }
    new_hitl_status = _status_map[(body.reviewer_role, body.status)]

    pool = _get_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE acp_silver_s4.blog_drafts "
            "SET hitl_gate3_status=$1, hitl_reviewer_id=$2, hitl_decided_at=NOW() "
            "WHERE draft_id=$3::uuid "
            "RETURNING draft_id::text, run_id::text, tenant_id, "
            "hitl_gate3_status, hitl_reviewer_id, hitl_decided_at",
            new_hitl_status, body.reviewer_id, draft_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Draft not found")

        run_id = str(row["run_id"])
        tenant_id = str(row["tenant_id"])

        # Audit log — mandatory on every decision
        await conn.execute(
            """
            INSERT INTO acp_shared.audit_log
                (tenant_id, actor, action, resource_type, resource_id, details)
            VALUES ($1, $2, $3, 'blog_draft', $4, $5::jsonb)
            """,
            tenant_id,
            body.reviewer_id,
            f"hitl.gate3.{body.status}",
            draft_id,
            json.dumps({"notes": body.notes, "reviewer_id": body.reviewer_id}),
        )

        if new_hitl_status == "msthy_approved":
            queue_id = str(uuid4())
            cms_secret_key = f"acp/cms/{tenant_id}"
            await conn.execute(
                """
                INSERT INTO acp_shared.acp_cms_publish_queue
                    (queue_id, run_id, tenant_id, draft_id, cms_secret_key, status)
                VALUES ($1, $2::uuid, $3, $4::uuid, $5, 'pending')
                """,
                queue_id, run_id, tenant_id, draft_id, cms_secret_key,
            )
            await conn.execute(
                "UPDATE acp_silver_s4.blog_drafts SET cms_publish_status='enqueued' WHERE draft_id=$1::uuid",
                draft_id,
            )
            asyncio.create_task(_cms_publish(pool, queue_id, draft_id, tenant_id, cms_secret_key))

    logger.info("s4_hitl_decision", draft_id=draft_id, status=body.status, reviewer=body.reviewer_id)
    return _row_to_dict(row)
