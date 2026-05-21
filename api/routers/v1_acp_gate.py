"""
B2B Gate Self-Approval endpoints — AA-89.

Routes:
  POST /v1/acp/gate/{stage}/approve  — tenant_admin self-approves their run
  POST /v1/acp/gate/{stage}/reject   — tenant_admin self-rejects (notes required)
  GET  /v1/acp/gate/{stage}/run/{run_id} — load run summary for portal display

Stage values: s2 | s3 | s4  (maps to integer 2 | 3 | 4 in DB)

Auth:
  - Standard tenant JWT (role=tenant) or admin secret
  - RLS: JWT sub (tenant_id) must match the run's tenant_id — no cross-tenant approval

Gate rules (NON-NEGOTIABLE):
  - NEVER auto-approve: endpoint only reached by explicit human action in portal
  - audit_log mandatory on every approve or reject — no exceptions
  - actor_type='tenant_admin' recorded in details JSONB
  - Double-submit guard: 409 if hitl_request already resolved
"""
import json
import os
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from pydantic import BaseModel, field_validator

from api.routers.auth import verify_jwt as _verify_jwt

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/acp/gate", tags=["acp-gate"])

_STAGE_MAP = {"s2": 2, "s3": 3, "s4": 4}


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_tenant_actor(
    request: Request,
    credentials: Optional[_Creds] = Depends(_HTTPBearer(auto_error=False)),
) -> dict:
    """Accept admin secret OR tenant JWT. Returns payload with tenant_id and actor."""
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    x_admin = request.headers.get("X-Admin-Secret", "")
    if admin_secret and x_admin == admin_secret:
        return {
            "sub": "00000000-0000-0000-0000-000000000001",
            "role": "admin",
            "actor": "admin",
        }
    if credentials:
        try:
            payload = _verify_jwt(credentials.credentials)
            role = payload.get("role", "")
            if role in ("tenant", "admin"):
                return {
                    **payload,
                    "actor": payload.get("name") or payload.get("sub") or "tenant_admin",
                }
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_stage(stage: str) -> int:
    s = stage.lower()
    if s not in _STAGE_MAP:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid stage '{stage}'. Must be one of: s2, s3, s4",
        )
    return _STAGE_MAP[s]


def _safe_uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail=f"Invalid UUID for {field}: {value!r}")


# ── Pydantic models ───────────────────────────────────────────────────────────

class GateApproveRequest(BaseModel):
    run_id: str
    notes: str = ""


class GateRejectRequest(BaseModel):
    run_id: str
    notes: str

    @field_validator("notes")
    @classmethod
    def notes_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("notes must not be empty")
        return v.strip()


# ── POST /v1/acp/gate/{stage}/approve ────────────────────────────────────────

@router.post("/{stage}/approve")
async def gate_approve(
    stage: str,
    body: GateApproveRequest,
    request: Request,
    tenant=Depends(_get_tenant_actor),
):
    """
    B2B self-approval — tenant_admin approves their own run at a given gate.

    NON-NEGOTIABLE:
    - NEVER auto-approve: only reached by explicit human action
    - audit_log mandatory: every call writes a record — no exceptions
    - tenant_id in JWT must match run's tenant_id
    """
    stage_int = _parse_stage(stage)
    run_id = _safe_uuid(body.run_id, "run_id")
    jwt_tenant_id = tenant.get("sub", "")
    actor = tenant.get("actor", "tenant_admin")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        run_row = await conn.fetchrow(
            "SELECT tenant_id FROM acp_shared.acp_runs WHERE run_id = $1::uuid",
            run_id,
        )
        if not run_row:
            raise HTTPException(status_code=404, detail=f"run_id {run_id} not found")

        # RLS: tenant can only approve their own run
        run_tenant = str(run_row["tenant_id"])
        is_admin = tenant.get("role") == "admin"
        if not is_admin and run_tenant != jwt_tenant_id:
            raise HTTPException(status_code=403, detail="Not authorised to approve this run")

        hitl_row = await conn.fetchrow(
            """
            SELECT hitl_id, status FROM acp_shared.acp_hitl_requests
            WHERE run_id = $1::uuid AND stage = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
            stage_int,
        )
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
            await conn.execute(
                """
                UPDATE acp_shared.acp_hitl_requests
                SET status = 'approved', resolved_at = NOW(), reviewer_id = $2
                WHERE hitl_id = $1
                """,
                hitl_row["hitl_id"],
                actor,
            )
            # audit_log — MANDATORY, no exceptions
            await conn.execute(
                """
                INSERT INTO acp_shared.audit_log
                    (tenant_id, actor, action, resource_type, resource_id, details)
                VALUES ($1, $2, $3, 'acp_hitl_request', $4, $5::jsonb)
                """,
                run_tenant,
                actor,
                f"hitl.gate{stage_int}.approve",
                run_id,
                json.dumps({
                    "actor_type": "tenant_admin",
                    "stage": stage,
                    "hitl_id": str(hitl_row["hitl_id"]),
                    "notes": body.notes.strip(),
                }),
            )

    logger.info("gate_approved", run_id=run_id, stage=stage, actor=actor)
    return {"run_id": run_id, "stage": stage, "status": "approved"}


# ── POST /v1/acp/gate/{stage}/reject ─────────────────────────────────────────

@router.post("/{stage}/reject")
async def gate_reject(
    stage: str,
    body: GateRejectRequest,
    request: Request,
    tenant=Depends(_get_tenant_actor),
):
    """
    B2B self-rejection — tenant_admin rejects their run at a given gate.

    NON-NEGOTIABLE:
    - notes required (enforced by GateRejectRequest validator)
    - audit_log mandatory: every call writes a record — no exceptions
    - tenant_id in JWT must match run's tenant_id
    """
    stage_int = _parse_stage(stage)
    run_id = _safe_uuid(body.run_id, "run_id")
    jwt_tenant_id = tenant.get("sub", "")
    actor = tenant.get("actor", "tenant_admin")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        run_row = await conn.fetchrow(
            "SELECT tenant_id FROM acp_shared.acp_runs WHERE run_id = $1::uuid",
            run_id,
        )
        if not run_row:
            raise HTTPException(status_code=404, detail=f"run_id {run_id} not found")

        run_tenant = str(run_row["tenant_id"])
        is_admin = tenant.get("role") == "admin"
        if not is_admin and run_tenant != jwt_tenant_id:
            raise HTTPException(status_code=403, detail="Not authorised to reject this run")

        hitl_row = await conn.fetchrow(
            """
            SELECT hitl_id, status FROM acp_shared.acp_hitl_requests
            WHERE run_id = $1::uuid AND stage = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
            stage_int,
        )
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
            await conn.execute(
                """
                UPDATE acp_shared.acp_hitl_requests
                SET status = 'rejected', resolved_at = NOW(),
                    reviewer_id = $2, reviewer_notes = $3
                WHERE hitl_id = $1
                """,
                hitl_row["hitl_id"],
                actor,
                body.notes,
            )
            # audit_log — MANDATORY, no exceptions
            await conn.execute(
                """
                INSERT INTO acp_shared.audit_log
                    (tenant_id, actor, action, resource_type, resource_id, details)
                VALUES ($1, $2, $3, 'acp_hitl_request', $4, $5::jsonb)
                """,
                run_tenant,
                actor,
                f"hitl.gate{stage_int}.reject",
                run_id,
                json.dumps({
                    "actor_type": "tenant_admin",
                    "stage": stage,
                    "hitl_id": str(hitl_row["hitl_id"]),
                    "notes": body.notes,
                }),
            )

    logger.info("gate_rejected", run_id=run_id, stage=stage, actor=actor, notes_len=len(body.notes))
    return {"run_id": run_id, "stage": stage, "status": "rejected", "notes": body.notes}


# ── GET /v1/acp/gate/{stage}/run/{run_id} ────────────────────────────────────

@router.get("/{stage}/run/{run_id}")
async def get_gate_run(
    stage: str,
    run_id: str,
    request: Request,
    tenant=Depends(_get_tenant_actor),
):
    """
    Load run summary for portal display — called by B2B approve/reject pages.
    Returns run metadata + current HITL status for this stage.
    """
    stage_int = _parse_stage(stage)
    run_id = _safe_uuid(run_id, "run_id")
    jwt_tenant_id = tenant.get("sub", "")
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

        run_tenant = str(run_row["tenant_id"])
        is_admin = tenant.get("role") == "admin"
        if not is_admin and run_tenant != jwt_tenant_id:
            raise HTTPException(status_code=403, detail="Not authorised to view this run")

        hitl_row = await conn.fetchrow(
            """
            SELECT status, expires_at, reviewer_id, reviewer_notes, resolved_at
            FROM acp_shared.acp_hitl_requests
            WHERE run_id = $1::uuid AND stage = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
            stage_int,
        )

    return {
        "run_id": run_id,
        "tenant_id": run_tenant,
        "country": run_row["country"],
        "status": run_row["status"],
        "started_at": run_row["started_at"].isoformat() if run_row["started_at"] else None,
        "completed_at": run_row["completed_at"].isoformat() if run_row["completed_at"] else None,
        "stage": stage,
        "hitl_status": hitl_row["status"] if hitl_row else None,
        "hitl_expires_at": hitl_row["expires_at"].isoformat() if hitl_row and hitl_row["expires_at"] else None,
        "hitl_notes": hitl_row["reviewer_notes"] if hitl_row else None,
        "hitl_resolved_at": hitl_row["resolved_at"].isoformat() if hitl_row and hitl_row["resolved_at"] else None,
    }
