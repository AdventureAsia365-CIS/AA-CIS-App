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
from api.services.run_context_db import get_run_context_validated
from api.schemas.run_context import RunContextValidationError
from services.acp_shared.errors import S1ContextNotReadyError

logger = structlog.get_logger()
router = APIRouter(tags=["S2 Research"])


async def _do_resume_run(run_id: str, tenant_id: str, pool, graph) -> None:
    """Core S2 resume logic — reused by HTTP handler and startup crash-recovery."""
    config = {"configurable": {"thread_id": run_id}}
    sem = _get_semaphore(tenant_id)
    async with sem:
        try:
            state = await graph.aget_state(config)
            iteration = (
                state.values.get("iteration", 0)
                if state and state.values else 0
            )
            async with pool.acquire() as conn:
                try:
                    await conn.execute(
                        """
                        INSERT INTO acp_shared.acp_stage_runs (run_id, stage, metadata)
                        VALUES ($1::uuid, 's2', $2::jsonb)
                        ON CONFLICT (run_id, stage) DO UPDATE
                        SET metadata = COALESCE(acp_stage_runs.metadata, '{}') || EXCLUDED.metadata
                        """,
                        run_id,
                        json.dumps({"resume_from_iteration": iteration,
                                    "checkpointer": "AsyncPostgresSaver"}),
                    )
                except Exception as e:
                    logger.error("acp_stage_runs_upsert_failed", error=str(e), run_id=run_id)
                    raise
            await graph.ainvoke(None, config=config)
        except Exception as exc:
            logger.error("s2_resume_error", run_id=run_id, error=str(exc))

GATE1_AUTO_APPROVE_THRESHOLD = 0.85  # PRD v1.3 §2.2: aa_internal + confidence >= 0.85


async def _handle_gate1(pool, run_id: str, tenant_id: str) -> dict:
    """
    Gate 1 post-S2: auto-approve for aa_internal if confidence >= 0.85.
    B2B tenants always get a pending HITL request (self-approve via portal).
    gate1_override='manual_required' blocks auto-approve even when score >= threshold (AA-113).
    PRD v1.3 §2.2.
    """
    async with pool.acquire() as conn:
        try:
            ctx = await get_run_context_validated(conn, run_id, require_stages=("s2",))
            confidence = ctx.s2_confidence_score or 0.0
            gate1_override = None
            if ctx.s2_visibility_report:
                gate1_override = ctx.s2_visibility_report.get("gate1_override")
        except RunContextValidationError as exc:
            logger.error("gate1_context_missing", run_id=run_id, missing=exc.missing_path)
            confidence = 0.0
            gate1_override = None
    is_aa_internal = (tenant_id == "00000000-0000-0000-0000-000000000001")
    override_blocks = (gate1_override == "manual_required")
    auto_approved = is_aa_internal and confidence >= GATE1_AUTO_APPROVE_THRESHOLD and not override_blocks
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
            json.dumps({"confidence": confidence, "threshold": GATE1_AUTO_APPROVE_THRESHOLD,
                        "gate1_override": gate1_override}),
            status, auto_approved, confidence, reviewer_type,
        )
        await conn.execute(
            """
            INSERT INTO acp_shared.audit_log
                (tenant_id, actor, actor_type, action, resource_type, resource_id, details)
            VALUES ($1, 'system', 'tenant_admin', 'hitl.gate1', 'acp_run', $2,
                    $3::jsonb)
            """,
            tenant_id, run_id,
            json.dumps({"auto_approved": auto_approved, "confidence": confidence,
                        "threshold": GATE1_AUTO_APPROVE_THRESHOLD,
                        "gate1_override": gate1_override}),
        )

    logger.info("gate1_evaluated", run_id=run_id, auto_approved=auto_approved,
                confidence=confidence, gate1_override=gate1_override, tenant_id=tenant_id)
    return {"auto_approved": auto_approved, "confidence_score": confidence,
            "threshold": GATE1_AUTO_APPROVE_THRESHOLD,
            "gate1_override": gate1_override,
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
    s1_run_id: Optional[str] = None  # S1 batch run_id; required at runtime for guard


def _guard_s1_context(context: dict, run_id: str) -> None:
    """Raise S1ContextNotReadyError if s1_keywords_used is absent or empty."""
    kws = context.get("s1_keywords_used")
    if not kws or len(kws) == 0:
        raise S1ContextNotReadyError(
            f"S1_CONTEXT_NOT_READY: s1_keywords_used is empty or missing for run_id={run_id}"
        )


# ── POST /run ─────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_s2(
    body: RunS2Request,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Trigger a S2 visibility research run. Returns immediately; graph runs in background."""
    if not body.s1_run_id:
        raise HTTPException(
            status_code=422,
            detail="s1_run_id is required: S2 requires S1 context for anti-cannibalization",
        )

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
        logger.info("s2_idempotent_duplicate", idem_key=idem_key,
                    run_id=str(existing["run_id"]))
        return {"run_id": str(existing["run_id"]), "status": "existing",
                "idempotency_key": idem_key}

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
        "competitor_count": 0,
        "informational_intent_pct": None,
        "confidence_score": None,
        "dataforseo_cache_hit": False,
        "apify_cache_hit": False,
        "gsc_data_present": False,
        "expand_attempts": 0,
        "gate1_override": None,
        "data_quality": None,
        "iteration": 0,
        "completed_tools": [],
        "error": None,
        "existing_content_risk": False,
    }
    config = {"configurable": {"thread_id": run_id}}
    s1_run_id = body.s1_run_id

    async def _background():
        async with sem:
            try:
                async with pool.acquire() as conn:
                    try:
                        await conn.execute(
                            """
                            INSERT INTO acp_shared.acp_stage_runs (run_id, stage, metadata)
                            VALUES ($1::uuid, 's2', $2::jsonb)
                            ON CONFLICT (run_id, stage) DO UPDATE
                            SET metadata = COALESCE(acp_stage_runs.metadata, '{}') || EXCLUDED.metadata
                            """,
                            run_id,
                            json.dumps({"resume_from_iteration": 0,
                                        "checkpointer": "AsyncPostgresSaver"}),
                        )
                    except Exception as e:
                        logger.error("acp_stage_runs_upsert_failed", error=str(e), run_id=run_id)
                        raise

                # Guard: verify S1 wrote s1_keywords_used before S2 proceeds.
                # s1_run_id is validated non-null before _background() is created.
                async with pool.acquire() as conn:
                    ctx_row = await conn.fetchrow(
                        "SELECT s1_keywords_used "
                        "FROM acp_shared.acp_run_context "
                        "WHERE run_id=$1::uuid",
                        s1_run_id,
                    )
                raw_kws = ctx_row["s1_keywords_used"] if ctx_row else None
                if isinstance(raw_kws, str):
                    raw_kws = json.loads(raw_kws)
                ctx_dict = {"s1_keywords_used": raw_kws}
                logger.info("s2_s1_context_check", run_id=run_id, s1_run_id=s1_run_id,
                            keyword_count=len(raw_kws) if raw_kws else 0)
                _guard_s1_context(ctx_dict, s1_run_id)

                result = await graph.ainvoke(initial_state, config=config)
                # Write cache savings ratio to monitoring metadata
                dfs_hit = bool((result or {}).get("dataforseo_cache_hit", False))
                apify_hit = bool((result or {}).get("apify_cache_hit", False))
                cache_hits = int(dfs_hit) + int(apify_hit)
                compute_saved_pct = round((cache_hits / 2) * 100)
                async with pool.acquire() as conn:
                    try:
                        await conn.execute(
                            """
                            UPDATE acp_shared.acp_stage_runs
                            SET metadata = COALESCE(acp_stage_runs.metadata, '{}') ||
                                           jsonb_build_object('compute_saved_pct', $1::text),
                                updated_at = NOW()
                            WHERE run_id = $2::uuid AND stage = 's2'
                            """,
                            str(compute_saved_pct), run_id,
                        )
                    except Exception as e:
                        logger.warning("compute_saved_pct_write_failed", error=str(e), run_id=run_id)
                await _handle_gate1(pool, run_id, tenant_id)
            except S1ContextNotReadyError as exc:
                logger.error("s2_s1_context_not_ready", run_id=run_id,
                             s1_run_id=s1_run_id, error=str(exc))
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE acp_shared.acp_runs SET status='failed', "
                        "error_message=$1 WHERE run_id=$2::uuid",
                        str(exc), run_id,
                    )
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
                state = await graph.aget_state(config)
                iteration = (
                    state.values.get("iteration", 0)
                    if state and state.values else 0
                )
                async with pool.acquire() as conn:
                    try:
                        await conn.execute(
                            """
                            INSERT INTO acp_shared.acp_stage_runs (run_id, stage, metadata)
                            VALUES ($1::uuid, 's2', $2::jsonb)
                            ON CONFLICT (run_id, stage) DO UPDATE
                            SET metadata = COALESCE(acp_stage_runs.metadata, '{}') || EXCLUDED.metadata
                            """,
                            run_id,
                            json.dumps({"resume_from_iteration": iteration,
                                        "checkpointer": "AsyncPostgresSaver"}),
                        )
                    except Exception as e:
                        logger.error("acp_stage_runs_upsert_failed", error=str(e), run_id=run_id)
                        raise
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
        "confidence_score":  (
            float(row["confidence_score"]) if row["confidence_score"] is not None else None
        ),
        "fetched_at":        row["fetched_at"].isoformat() if row["fetched_at"] else None,
    }
