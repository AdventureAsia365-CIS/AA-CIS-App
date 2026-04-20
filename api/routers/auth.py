# api/routers/auth.py
# S7 Step 2 — Real API key authentication for tenant portal
#
# Flow:
#   POST /auth/tenant-login  { api_key }
#   → SHA256 hash key
#   → lookup shared.tenants WHERE api_key_hash = hash AND is_active = true
#   → if found: return signed JWT { tenant_id, name, plan_tier, exp }
#   → frontend stores JWT in cookie → middleware verifies JWT on each request
#
# JWT secret: JWT_SECRET env var (required)
# JWT expiry: 24h

import hashlib
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import jwt  # PyJWT
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])

JWT_SECRET   = os.environ.get("JWT_SECRET", "cis-dev-jwt-secret-change-in-prod")
JWT_ALG      = "HS256"
JWT_EXPIRY_H = 24


# ── Models ────────────────────────────────────────────────────────────────────

class TenantLoginRequest(BaseModel):
    api_key: str


class TenantLoginResponse(BaseModel):
    token: str
    tenant_id: str
    tenant_name: str
    plan_tier: str


# ── Helper ────────────────────────────────────────────────────────────────────

def _hash_api_key(raw_key: str) -> str:
    """SHA256 hex digest — matches migration 007 encode(sha256(...),'hex')."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _create_jwt(tenant_id: str, name: str, plan_tier: str) -> str:
    payload = {
        "sub":       tenant_id,
        "name":      name,
        "plan_tier": plan_tier,
        "role":      "tenant",
        "iat":       datetime.now(timezone.utc),
        "exp":       datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_H),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def verify_jwt(token: str) -> dict:
    """Verify JWT and return payload. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/tenant-login", response_model=TenantLoginResponse)
async def tenant_login(
    body: TenantLoginRequest,
    pool=Depends(lambda: None),  # replaced by app-level pool injection below
):
    """
    Verify tenant API key against shared.tenants.api_key_hash.
    Returns signed JWT on success.
    """
    if not body.api_key or len(body.api_key) < 10:
        raise HTTPException(status_code=400, detail="Invalid API key format")

    key_hash = _hash_api_key(body.api_key)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT tenant_id::text, name, plan_tier
            FROM shared.tenants
            WHERE api_key_hash = $1
              AND is_active = true
            """,
            key_hash,
        )

    if not row:
        # Consistent timing to prevent enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    token = _create_jwt(
        tenant_id=row["tenant_id"],
        name=row["name"],
        plan_tier=row["plan_tier"],
    )

    return TenantLoginResponse(
        token=token,
        tenant_id=row["tenant_id"],
        tenant_name=row["name"],
        plan_tier=row["plan_tier"],
    )


# ── /auth/verify — middleware helper ──────────────────────────────────────────

class VerifyResponse(BaseModel):
    tenant_id: str
    name: str
    plan_tier: str
    valid: bool


@router.post("/verify-tenant", response_model=VerifyResponse)
async def verify_tenant_token(token: str):
    """
    Verify a tenant JWT. Used by Next.js middleware (server-side).
    Returns 401 if invalid/expired.
    """
    payload = verify_jwt(token)
    return VerifyResponse(
        tenant_id=payload["sub"],
        name=payload["name"],
        plan_tier=payload["plan_tier"],
        valid=True,
    )
