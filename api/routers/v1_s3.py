"""
S3 Campaign Planner + Gate 2 HITL endpoints.

Routes:
  POST /v1/s3/run                          → async Lambda invoke → {run_id, status: "running"}
  GET  /v1/s3/runs/{run_id}                → poll status from acp_runs + content_calendars
  POST /v1/hitl/gate2/{run_id}/approve     → HITL approve (audit_log mandatory, NEVER auto)
  POST /v1/hitl/gate2/{run_id}/reject      → HITL reject (notes required, audit_log mandatory)

Gate 2 rules (NON-NEGOTIABLE):
  - Reviewer: Ms. Thu / hitl_reviewer role only
  - Auto-approve: NEVER
  - actor_type in audit_log: always 'hitl_reviewer'
  - audit_log: mandatory on every approve or reject — no exceptions
  - SLA: 24h (expires_at = created_at + 24h)

Lambda: aa-cis-dev-acp-s3-campaign-planner
  Invoked async (Event) — 15-minute max runtime, response is fire-and-forget.
  Spec says RequestResponse but that would block the API for 15 min — Event is correct.

audit_log schema (migration 030):
  actor         VARCHAR(64)  — reviewer identifier
  action        VARCHAR(64)  — hitl.gate2.approve | hitl.gate2.reject
  resource_type VARCHAR(32)  — 'acp_hitl_request'
  resource_id   TEXT         — run_id
  details       JSONB        — {"actor_type": "hitl_reviewer", "notes": "..."}
  Note: spec uses actor_type as a column but migration 030 uses actor + details JSONB.
"""
import asyncio
import json
import os
from typing import Optional
from uuid import UUID

import boto3 as _boto3
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from pydantic import BaseModel, field_validator

from api.routers.auth import verify_jwt as _verify_jwt
from services.acp_shared import h3_rule_extractor as _h3

logger = structlog.get_logger()
router = APIRouter(tags=["S3 Campaign Planner"])

_S3_LAMBDA = os.environ.get("ACP_S3_LAMBDA", "aa-cis-dev-acp-s3-campaign-planner")
_AWS_REGION = os.environ.get("AWS_REGION", "us-west-1")
_EB_BUS = os.environ.get("ACP_EVENT_BUS", "aa-cis-dev-acp-events")


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
            return _verify_jwt(credentials.credentials)
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


def _get_hitl_reviewer(
    request: Request,
    credentials: Optional[_Creds] = Depends(_HTTPBearer(auto_error=False)),
):
    """HITL reviewer auth — accepts admin secret OR jwt with role hitl_reviewer/admin."""
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    x_admin = request.headers.get("X-Admin-Secret", "")
    if admin_secret and x_admin == admin_secret:
        return {"sub": "00000000-0000-0000-0000-000000000001", "role": "hitl_reviewer", "actor": "admin"}
    if credentials:
        try:
            payload = _verify_jwt(credentials.credentials)
            role = payload.get("role", "")
            if role in ("hitl_reviewer", "admin"):
                return {**payload, "actor": payload.get("email") or payload.get("sub") or "hitl_reviewer"}
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="hitl_reviewer role required")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail=f"Invalid UUID for {field}: {value!r}")


# ── Pydantic models ───────────────────────────────────────────────────────────

class RunS3Request(BaseModel):
    run_id: str
    tenant_id: str


class RejectRequest(BaseModel):
    notes: str

    @field_validator("notes")
    @classmethod
    def notes_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("notes must not be empty")
        return v.strip()


# ── POST /v1/s3/run ───────────────────────────────────────────────────────────

@router.post("/v1/s3/run")
async def trigger_s3_run(body: RunS3Request, tenant=Depends(_get_tenant)):
    """
    Async Lambda invoke — returns immediately.
    Lambda runs up to 15 min; poll /v1/s3/runs/{run_id} for completion.
    """
    run_id = _safe_uuid(body.run_id, "run_id")
    tenant_id = body.tenant_id.strip()
    if not tenant_id:
        raise HTTPException(status_code=422, detail="tenant_id must not be empty")

    lam = _boto3.client("lambda", region_name=_AWS_REGION)
    payload = json.dumps({"run_id": run_id, "tenant_id": tenant_id}).encode()
    try:
        lam.invoke(
            FunctionName=_S3_LAMBDA,
            InvocationType="Event",
            Payload=payload,
        )
    except Exception as e:
        logger.error("s3_lambda_invoke_failed", run_id=run_id, error=str(e))
        raise HTTPException(status_code=502, detail=f"Lambda invoke failed: {e}")

    logger.info("s3_run_triggered", run_id=run_id, tenant_id=tenant_id)
    return {"run_id": run_id, "status": "running"}


# ── GET /v1/s3/runs/{run_id} ──────────────────────────────────────────────────

@router.get("/v1/s3/runs/{run_id}")
async def get_s3_run(run_id: str, request: Request, tenant=Depends(_get_tenant)):
    """Poll S3 run status and summary."""
    run_id = _safe_uuid(run_id, "run_id")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        run_row = await conn.fetchrow(
            """
            SELECT run_id, tenant_id, country, status, started_at, completed_at
            FROM acp_shared.acp_runs
            WHERE run_id = $1::uuid
            """,
            run_id,
        )
        if not run_row:
            raise HTTPException(status_code=404, detail=f"run_id {run_id} not found")

        cal_row = await conn.fetchrow(
            """
            SELECT calendar_id, funnel_mix, validation_errors,
                   expanded_markdown, input_tokens, output_tokens
            FROM acp_silver_s3.content_calendars
            WHERE run_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
        )
        ads_row = await conn.fetchrow(
            """
            SELECT ads_plan_id, pdf_s3_key, campaigns,
                   input_tokens AS ads_input_tokens
            FROM acp_silver_s3.ads_plan
            WHERE run_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
        )
        hitl_row = await conn.fetchrow(
            """
            SELECT status AS hitl_status, expires_at, reviewer_id
            FROM acp_shared.acp_hitl_requests
            WHERE run_id = $1::uuid AND stage = 2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
        )

    validation_errors: list = []
    if cal_row and cal_row["validation_errors"]:
        ve = cal_row["validation_errors"]
        validation_errors = ve if isinstance(ve, list) else json.loads(ve)

    calendar_summary = None
    if cal_row:
        fm = cal_row["funnel_mix"]
        calendar_summary = {
            "calendar_id": str(cal_row["calendar_id"]),
            "funnel_mix": fm if isinstance(fm, dict) else json.loads(fm or "{}"),
            "expanded_markdown": cal_row["expanded_markdown"] or "",
            "input_tokens": cal_row["input_tokens"],
            "output_tokens": cal_row["output_tokens"],
        }

    ads_summary = None
    if ads_row:
        camps = ads_row["campaigns"]
        ads_summary = {
            "ads_plan_id": str(ads_row["ads_plan_id"]),
            "pdf_s3_key": ads_row["pdf_s3_key"],
            "campaigns": camps if isinstance(camps, list) else json.loads(camps or "[]"),
        }

    return {
        "run_id": run_id,
        "status": run_row["status"],
        "country": run_row["country"],
        "started_at": run_row["started_at"].isoformat() if run_row["started_at"] else None,
        "completed_at": run_row["completed_at"].isoformat() if run_row["completed_at"] else None,
        "calendar_summary": calendar_summary,
        "ads_summary": ads_summary,
        "validation_errors": validation_errors,
        "hitl_status": hitl_row["hitl_status"] if hitl_row else None,
        "hitl_expires_at": hitl_row["expires_at"].isoformat() if hitl_row and hitl_row["expires_at"] else None,
    }


# ── POST /v1/hitl/gate2/{run_id}/approve ─────────────────────────────────────

@router.post("/v1/hitl/gate2/{run_id}/approve")
async def hitl_gate2_approve(
    run_id: str,
    request: Request,
    reviewer=Depends(_get_hitl_reviewer),
):
    """
    Gate 2 HITL approve.

    NON-NEGOTIABLE:
    - NEVER auto-approve: this endpoint must only be reached by explicit human action
    - audit_log mandatory: every call writes a record — no exceptions
    - actor_type = 'hitl_reviewer' always recorded in details JSONB
    """
    run_id = _safe_uuid(run_id, "run_id")
    pool = request.app.state.pool
    actor = reviewer.get("actor", "hitl_reviewer")

    async with pool.acquire() as conn:
        hitl_row = await conn.fetchrow(
            """
            SELECT hitl_id, status FROM acp_shared.acp_hitl_requests
            WHERE run_id = $1::uuid AND stage = 2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
        )
        if not hitl_row:
            raise HTTPException(status_code=404, detail=f"No Gate 2 HITL request for run_id {run_id}")
        if hitl_row["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"HITL request is already '{hitl_row['status']}' — cannot approve",
            )

        async with conn.transaction():
            await conn.execute(
                """
                UPDATE acp_shared.acp_hitl_requests
                SET status = 'approved', resolved_at = NOW()
                WHERE hitl_id = $1
                """,
                hitl_row["hitl_id"],
            )
            # audit_log — MANDATORY, no exceptions
            await conn.execute(
                """
                INSERT INTO acp_shared.audit_log
                    (tenant_id, actor, action, resource_type, resource_id, details)
                SELECT r.tenant_id, $2, 'hitl.gate2.approve', 'acp_hitl_request', $3,
                       $4::jsonb
                FROM acp_shared.acp_runs r
                WHERE r.run_id = $1::uuid
                """,
                run_id,
                actor,
                run_id,
                json.dumps({"actor_type": "hitl_reviewer", "hitl_id": str(hitl_row["hitl_id"])}),
            )

    # EventBridge
    try:
        eb = _boto3.client("events", region_name=_AWS_REGION)
        eb.put_events(Entries=[{
            "Source": "acp.s3",
            "DetailType": "acp.s3.gate2.approved",
            "Detail": json.dumps({"run_id": run_id, "actor": actor}),
            "EventBusName": _EB_BUS,
        }])
    except Exception as e:
        logger.warning("s3_gate2_eventbridge_failed", run_id=run_id, error=str(e))

    logger.info("s3_gate2_approved", run_id=run_id, actor=actor)
    return {"run_id": run_id, "status": "approved"}


# ── POST /v1/hitl/gate2/{run_id}/reject ──────────────────────────────────────

@router.post("/v1/hitl/gate2/{run_id}/reject")
async def hitl_gate2_reject(
    run_id: str,
    body: RejectRequest,
    request: Request,
    reviewer=Depends(_get_hitl_reviewer),
):
    """
    Gate 2 HITL reject.

    NON-NEGOTIABLE:
    - notes required — 422 if empty (enforced by RejectRequest validator)
    - audit_log mandatory: every call writes a record — no exceptions
    - actor_type = 'hitl_reviewer' always recorded in details JSONB
    """
    run_id = _safe_uuid(run_id, "run_id")
    pool = request.app.state.pool
    actor = reviewer.get("actor", "hitl_reviewer")

    async with pool.acquire() as conn:
        hitl_row = await conn.fetchrow(
            """
            SELECT hitl_id, status FROM acp_shared.acp_hitl_requests
            WHERE run_id = $1::uuid AND stage = 2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
        )
        if not hitl_row:
            raise HTTPException(status_code=404, detail=f"No Gate 2 HITL request for run_id {run_id}")
        if hitl_row["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"HITL request is already '{hitl_row['status']}' — cannot reject",
            )

        async with conn.transaction():
            await conn.execute(
                """
                UPDATE acp_shared.acp_hitl_requests
                SET status = 'rejected', resolved_at = NOW(), reviewer_notes = $2
                WHERE hitl_id = $1
                """,
                hitl_row["hitl_id"],
                body.notes,
            )
            # audit_log — MANDATORY, no exceptions
            await conn.execute(
                """
                INSERT INTO acp_shared.audit_log
                    (tenant_id, actor, action, resource_type, resource_id, details)
                SELECT r.tenant_id, $2, 'hitl.gate2.reject', 'acp_hitl_request', $3,
                       $4::jsonb
                FROM acp_shared.acp_runs r
                WHERE r.run_id = $1::uuid
                """,
                run_id,
                actor,
                run_id,
                json.dumps({
                    "actor_type": "hitl_reviewer",
                    "notes": body.notes,
                    "hitl_id": str(hitl_row["hitl_id"]),
                }),
            )

    # H-3: extract rule from rejection note (fire-and-forget, does not block response)
    asyncio.create_task(
        _h3.extract_and_save_rule(
            pool=pool,
            hitl_id=str(hitl_row["hitl_id"]),
            run_id=run_id,
            gate_number=2,
            reviewer_notes=body.notes,
        )
    )

    logger.info("s3_gate2_rejected", run_id=run_id, actor=actor, notes_len=len(body.notes))
    return {"run_id": run_id, "status": "rejected", "notes": body.notes}
