"""
/acp/s2 — S2 LangGraph Research Agent endpoints.

Routes (all under prefix /acp/s2):
  POST /run              — trigger S2, idempotency check, semaphore guard
  GET  /status/{run_id}  — poll acp_shared.acp_runs
  POST /resume/{run_id}  — HITL resume (approve acp_hitl_requests)
  GET  /report/{run_id}  — return visibility_report from acp_silver_s2.visibility_reports

Concurrency: max 2 concurrent runs per tenant via acpcore semaphore.
Pre-check is synchronous (TOCTOU-safe for scaffold); background task holds the slot.

Graph lifecycle: compiled graph is stored on app.state.s2_graph by the lifespan handler.
"""
import asyncio
import json
import os
import structlog
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from pydantic import BaseModel

from acpcore.concurrency import _get_semaphore, _MAX_CONCURRENT
from acpcore.errors import ACPErrorCode

logger = structlog.get_logger()
router = APIRouter(tags=["S2 Research"])


def _get_s2_graph(request: Request):
    graph = getattr(request.app.state, "s2_graph", None)
    if graph is None:
        raise HTTPException(status_code=503, detail="S2 graph not initialized")
    return graph


# ── Auth ──────────────────────────────────────────────────────────────────────

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
            from api.routers.auth import verify_jwt as _verify_jwt
            return _verify_jwt(credentials.credentials)
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


def _safe_uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail=f"Invalid UUID for {field}: {value!r}")


# ── Pydantic models ───────────────────────────────────────────────────────────

class RunS2Request(BaseModel):
    country: str
    idempotency_key: Optional[str] = None


# ── POST /run ─────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_s2(
    body: RunS2Request,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Trigger a S2 visibility research run. Returns immediately; graph runs in background."""
    pool = request.app.state.pool
    tenant_id = str(tenant.get("sub", ""))

    # Semaphore pre-check (synchronous; prevents 3rd concurrent run returning 200)
    sem = _get_semaphore(tenant_id)
    if sem._value <= 0:
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": ACPErrorCode.CONCURRENCY_LIMIT,
                "message": f"Tenant '{tenant_id}' already has {_MAX_CONCURRENT} active runs. Retry after current run completes.",
                "retry_after": 300,
            },
        )

    # Idempotency check
    idem_key = body.idempotency_key or f"{tenant_id}:{body.country}"
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("""
            SELECT run_id FROM acp_shared.idempotency_keys
            WHERE key = $1 AND expires_at > NOW()
        """, idem_key)

    if existing:
        logger.info("s2_idempotent_duplicate", idem_key=idem_key, run_id=str(existing["run_id"]))
        return {"run_id": str(existing["run_id"]), "status": "existing", "idempotency_key": idem_key}

    # Create acp_runs row
    async with pool.acquire() as conn:
        run_row = await conn.fetchrow("""
            INSERT INTO acp_shared.acp_runs (tenant_id, country, status, run_config)
            VALUES ($1, $2, 'running', $3)
            RETURNING run_id
        """, tenant_id, body.country, json.dumps({"stage": "s2", "country": body.country}))
        run_id = str(run_row["run_id"])

        await conn.execute("""
            INSERT INTO acp_shared.idempotency_keys (key, run_id)
            VALUES ($1, $2::uuid)
            ON CONFLICT (key) DO NOTHING
        """, idem_key, run_id)

    graph = _get_s2_graph(request)
    initial_state = {
        "run_id": run_id,
        "country": body.country,
        "tenant_id": tenant_id,
        "keywords_s3_key": None,
        "competitors_s3_key": None,
        "trends_s3_key": None,
        "reddit_s3_key": None,
        "gsc_s3_key": None,
        "keyword_count": 0,
        "informational_intent_pct": None,
        "confidence_score": None,
        "iteration": 0,
        "completed_tools": [],
        "error": None,
        "existing_content_risk": False,
    }
    config = {"configurable": {"thread_id": run_id}}

    async def _background():
        async with sem:
            try:
                await graph.ainvoke(initial_state, config=config)
            except Exception as exc:
                logger.error("s2_graph_error", run_id=run_id, error=str(exc))
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE acp_shared.acp_runs SET status='failed' WHERE run_id=$1::uuid",
                        run_id,
                    )

    asyncio.create_task(_background())
    logger.info("s2_run_started", run_id=run_id, country=body.country, tenant_id=tenant_id)
    return {"run_id": run_id, "status": "running", "country": body.country}


# ── GET /status/{run_id} ──────────────────────────────────────────────────────

@router.get("/status/{run_id}")
async def get_s2_status(
    run_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    _safe_uuid(run_id, "run_id")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT run_id, status, country, created_at, completed_at
            FROM acp_shared.acp_runs
            WHERE run_id = $1::uuid
        """, run_id)

    if not row:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return {
        "run_id":       str(row["run_id"]),
        "status":       row["status"],
        "country":      row["country"],
        "created_at":   row["created_at"].isoformat() if row["created_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
    }


# ── POST /resume/{run_id} ─────────────────────────────────────────────────────

@router.post("/resume/{run_id}")
async def resume_s2(
    run_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Approve a pending HITL request and resume the paused graph."""
    _safe_uuid(run_id, "run_id")
    pool = request.app.state.pool
    tenant_id = str(tenant.get("sub", ""))

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE acp_shared.acp_hitl_requests
            SET status = 'approved', resolved_at = NOW()
            WHERE run_id = $1::uuid AND status = 'pending'
        """, run_id)

    graph = _get_s2_graph(request)
    config = {"configurable": {"thread_id": run_id}}
    sem = _get_semaphore(tenant_id)

    async def _resume():
        async with sem:
            try:
                await graph.ainvoke(None, config=config)
            except Exception as exc:
                logger.error("s2_resume_error", run_id=run_id, error=str(exc))

    asyncio.create_task(_resume())
    logger.info("s2_run_resumed", run_id=run_id, tenant_id=tenant_id)
    return {"run_id": run_id, "status": "resuming"}


# ── GET /report/{run_id} ──────────────────────────────────────────────────────

@router.get("/report/{run_id}")
async def get_s2_report(
    run_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    _safe_uuid(run_id, "run_id")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT run_id, tenant_id, country, visibility_report,
                   confidence_score, keyword_count, existing_content_risk, fetched_at
            FROM acp_silver_s2.visibility_reports
            WHERE run_id = $1::uuid
        """, run_id)

    if not row:
        raise HTTPException(status_code=404, detail=f"Report for run {run_id} not found")

    report = row["visibility_report"]
    if isinstance(report, str):
        report = json.loads(report)

    return {
        "run_id":                str(row["run_id"]),
        "tenant_id":             str(row["tenant_id"]),
        "country":               row["country"],
        "visibility_report":     report,
        "confidence_score":      float(row["confidence_score"]) if row["confidence_score"] is not None else None,
        "keyword_count":         row["keyword_count"],
        "existing_content_risk": row["existing_content_risk"],
        "fetched_at":            row["fetched_at"].isoformat() if row["fetched_at"] else None,
    }
