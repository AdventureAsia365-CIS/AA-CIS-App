"""
/v1/social — Social content read API (AA-83).

Routes (specific before parameterized):
  GET /v1/social              → list rows (filter by tenant_id, tour_id)
  GET /v1/social/{social_id}  → get single row
"""
import json
import os
from typing import Optional
from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds

from api.routers.auth import verify_jwt as _verify_jwt

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/social", tags=["Social Content"])


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_admin(
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


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_social_content(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    tour_id: Optional[str] = Query(None),
    validation_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _auth=Depends(_get_admin),
):
    pool = _get_pool(request)
    async with pool.acquire() as conn:
        query = (
            "SELECT social_id::text, run_id::text, tenant_id, tour_id::text, "
            "tour_name, tiktok, facebook_post, facebook_ad, strategy_notes, "
            "validation_status, validation_issues, rewrite_attempt, "
            "hitl_gate_3_social_status, hitl_reviewer_id, hitl_decided_at, created_at "
            "FROM acp_silver_s4.social_content WHERE 1=1"
        )
        params: list = []
        if tenant_id:
            params.append(tenant_id)
            query += f" AND tenant_id = ${len(params)}"
        if tour_id:
            try:
                UUID(tour_id)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid tour_id UUID")
            params.append(tour_id)
            query += f" AND tour_id = ${len(params)}::uuid"
        if validation_status:
            params.append(validation_status)
            query += f" AND validation_status = ${len(params)}"
        params.append(limit)
        query += f" ORDER BY created_at DESC LIMIT ${len(params)}"
        rows = await conn.fetch(query, *params)

    return [_row_to_dict(r) for r in rows]


@router.get("/{social_id}")
async def get_social_content(
    social_id: str,
    request: Request,
    _auth=Depends(_get_admin),
):
    try:
        UUID(social_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid social_id UUID")

    pool = _get_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT social_id::text, run_id::text, tenant_id, tour_id::text, "
            "tour_name, tiktok, facebook_post, facebook_ad, strategy_notes, "
            "validation_status, validation_issues, rewrite_attempt, "
            "hitl_gate_3_social_status, hitl_reviewer_id, hitl_decided_at, created_at "
            "FROM acp_silver_s4.social_content WHERE social_id = $1::uuid",
            social_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Social content not found")
    return _row_to_dict(row)
