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

GATE1_AUTO_APPROVE_THRESHOLD = 0.85  # PRD v1.3 §2.2: aa_internal + confidence >= 0.85


async def _handle_gate1(pool, run_id: str, tenant_id: str) -> dict:
    """
    Gate 1 post-S2: auto-approve for aa_internal if confidence >= 0.85.
    B2B tenants always get a pending HITL request (self-approve via portal).
    PRD v1.3 §2.2.
    """
    async with pool.acquire() as conn:
        ctx = await conn.fetchrow(
            "SELECT s2_confidence_score FROM acp_shared.acp_run_context WHERE run_id = $1::uuid",
            run_id,
        )

    confidence = float(ctx["s2_confidence_score"] or 0) if ctx else 0.0
    is_aa_internal = (tenant_id == "00000000-0000-0000-0000-000000000001")
    auto_approved = is_aa_internal and confidence >= GATE1_AUTO_APPROVE_THRESHOLD
    status = "approved" if auto_approved else "pending"
    reviewer_type = "aa_internal" if is_aa_internal else "tenant_admin"

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO acp_shared.acp_hitl_requests
                (run_id, stage, gate_type, payload, status,
                 auto_approved, confidence_score, reviewer_type)
            VALUES ($1::uuid, 2, 'gate1', $2::jsonb, $3, $4, $5, $6)
            ON CONFLICT DO NOTHING
            """,
            run_id,
            json.dumps({"confidence": confidence, "threshold": GATE1_AUTO_APPROVE_THRESHOLD}),
            status, auto_approved, confidence, reviewer_type,
        )
        await conn.execute(
            """
            INSERT INTO acp_shared.audit_log
                (tenant_id, actor, actor_type, action, resource_type, resource_id, details)
            VALUES ($1, 'system', 'system', 'hitl.gate1', 'acp_run', $2,
                    $3::jsonb)
            """,
            tenant_id, run_id,
            json.dumps({"auto_approved": auto_approved, "confidence": confidence,
                        "threshold": GATE1_AUTO_APPROVE_THRESHOLD}),
        )

    logger.info("gate1_evaluated", run_id=run_id, auto_approved=auto_approved,
                confidence=confidence, tenant_id=tenant_id)
    return {"auto_approved": auto_approved, "confidence_score": confidence,
            "threshold": GATE1_AUTO_APPROVE_THRESHOLD,
            "next": "trigger_s3" if auto_approved else "await_manual_approval"}


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
                "message": (
                    f"Tenant '{tenant_id}' already has {_MAX_CONCURRENT} active runs. "
                    "Retry after current run completes."
                ),
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
            INSERT INTO acp_shared.idempotency_keys (key, run_id, tenant_id)
            VALUES ($1, $2::uuid, $3::uuid)
            ON CONFLICT (key) DO NOTHING
        """, idem_key, run_id, tenant_id)

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
                await _handle_gate1(pool, run_id, tenant_id)
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
            SELECT run_id, status, country, started_at, completed_at
            FROM acp_shared.acp_runs
            WHERE run_id = $1::uuid
        """, run_id)

    if not row:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return {
        "run_id":       str(row["run_id"]),
        "status":       row["status"],
        "country":      row["country"],
        "started_at":   row["started_at"].isoformat() if row["started_at"] else None,
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
        row = await conn.fetchrow(
            """
            SELECT run_id, tenant_id, country,
                   keyword_gaps, top_opportunities, competitor_data,
                   google_trends, reddit_insights, gsc_data,
                   confidence_score, primary_keywords, fetched_at
            FROM acp_silver_s2.visibility_reports
            WHERE run_id = $1::uuid
            """,
            run_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail=f"Report for run {run_id} not found")

    def _jsonb(val):
        if val is None:
            return None
        return val if isinstance(val, (list, dict)) else json.loads(val)

    return {
        "run_id":            str(row["run_id"]),
        "tenant_id":         str(row["tenant_id"]),
        "country":           row["country"],
        "top_opportunities": _jsonb(row["top_opportunities"]),
        "keyword_gaps":      _jsonb(row["keyword_gaps"]),
        "primary_keywords":  _jsonb(row["primary_keywords"]),
        "competitor_data":   row["competitor_data"],
        "google_trends":     row["google_trends"],
        "reddit_insights":   row["reddit_insights"],
        "gsc_data":          row["gsc_data"],
        "confidence_score":  float(row["confidence_score"]) if row["confidence_score"] is not None else None,
        "fetched_at":        row["fetched_at"].isoformat() if row["fetched_at"] else None,
    }
