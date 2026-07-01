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
import bcrypt
import jwt  # PyJWT
from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
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

@router.post("/tenant-login", response_model=TenantLoginResponse, deprecated=True)
async def tenant_login(
    body: TenantLoginRequest,
    pool=Depends(lambda: None),  # replaced by app-level pool injection below
):
    """
    DEPRECATED (AA-181): ACP tenant routes now authenticate with a single
    X-API-Key header (see verify_tenant_api_key) instead of a JWT obtained here.
    Kept for now for any remaining non-ACP callers; do not add new dependents.

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


# ── verify_tenant_api_key — AA-181 single-header ACP tenant auth ──────────────
#
# Replaces the per-router HTTPBearer(JWT) + X-Admin-Secret combo on all
# /acp/* tenant routes. Accepts EXACTLY ONE of:
#   - X-Admin-Secret: <ADMIN_SECRET>  -> AA internal staff (reviewer_type=aa_internal)
#   - X-API-Key: <raw cis_... key>    -> tenant partner (reviewer_type=tenant_self),
#     hashed with sha256 and matched against shared.tenants.api_key_hash
#
# AA_INTERNAL_ADMIN_SUB matches the long-standing admin sentinel used by the
# old _get_tenant()/_get_admin() dependencies (see AA-22 tech debt note).
AA_INTERNAL_ADMIN_SUB = "00000000-0000-0000-0000-000000000001"

# auto_error=False: these only register the headers in the OpenAPI schema
# (Swagger "Authorize" + per-route docs). The actual lookup/validation reads
# request.headers directly below, so a request can omit one and still pass
# via the other.
_api_key_header_scheme = APIKeyHeader(
    name="X-API-Key",
    scheme_name="TenantApiKey",
    auto_error=False,
    description="Raw tenant API key (cis_...), hashed and matched against shared.tenants.api_key_hash.",
)
_admin_secret_header_scheme = APIKeyHeader(
    name="X-Admin-Secret",
    scheme_name="AdminSecret",
    auto_error=False,
    description="AA internal admin secret (ADMIN_SECRET env var) — for AA staff/internal callers.",
)


async def verify_tenant_api_key(
    request: Request,
    _api_key: str = Security(_api_key_header_scheme),
    _admin_secret: str = Security(_admin_secret_header_scheme),
) -> dict:
    """
    Single-header ACP tenant auth dependency (AA-181).

    Send EXACTLY ONE of:
      - X-API-Key: <raw cis_... key>   (tenant partner)
      - X-Admin-Secret: <ADMIN_SECRET> (AA internal staff)

    Returns a dict with: sub, tenant_id, role, actor, reviewer_type, name, plan_tier.
    Raises 401 if neither X-Admin-Secret nor a valid X-API-Key is present.
    """
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    x_admin = request.headers.get("X-Admin-Secret", "")
    if admin_secret and x_admin == admin_secret:
        return {
            "sub": AA_INTERNAL_ADMIN_SUB,
            "tenant_id": AA_INTERNAL_ADMIN_SUB,
            "role": "admin",
            "actor": "aa_internal_admin",
            "reviewer_type": "aa_internal",
            "name": "AA Internal",
            "plan_tier": "internal",
        }

    raw_key = request.headers.get("X-API-Key", "")
    if raw_key:
        pool: asyncpg.Pool = request.app.state.pool
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT tenant_id::text, name, plan_tier
                FROM shared.tenants
                WHERE api_key_hash = $1
                  AND is_active = true
                """,
                _hash_api_key(raw_key),
            )
        if row:
            return {
                "sub": row["tenant_id"],
                "tenant_id": row["tenant_id"],
                "role": "tenant",
                "actor": row["name"] or row["tenant_id"],
                "reviewer_type": "tenant_self",
                "name": row["name"],
                "plan_tier": row["plan_tier"],
            }

    raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


# ── AA-232 — Per-user admin JWT auth ────────────────────────────────────────
#
# Flow:
#   POST /auth/admin-login  { username, password }
#   → bcrypt verify against shared.admin_users.password_hash
#   → if match + is_active: return signed JWT { sub: admin_users.id, username,
#     role, exp }
#   → frontend (middleware.ts) stores JWT, verifies via POST /auth/verify-admin
#     on each protected admin/internal request (mirrors tenant verify pattern)
#
# Deliberately mirrors tenant_login/verify_tenant_token shape (same JWT_SECRET,
# same HS256, same verify_jwt() helper) but:
#   - verifies bcrypt password_hash, not sha256 api_key_hash
#   - sub = admin_users.id (UUID), role = admin_users.role ('admin'|'reviewer')
#   - uses request.app.state.pool directly (tenant_login's Depends(lambda: None)
#     is broken/deprecated — do not copy that pattern, per S86 discovery)


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    token: str
    admin_id: str
    username: str
    role: str


def _verify_password(raw_password: str, password_hash: str) -> bool:
    """bcrypt compare. Returns False (not raise) on any malformed-hash error —
    a corrupt/legacy hash should fail closed, not 500."""
    try:
        return bcrypt.checkpw(raw_password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def _create_admin_jwt(admin_id: str, username: str, role: str) -> str:
    payload = {
        "sub":      admin_id,
        "username": username,
        "role":     role,
        "iat":      datetime.now(timezone.utc),
        "exp":      datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_H),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


@router.post("/admin-login", response_model=AdminLoginResponse)
async def admin_login(body: AdminLoginRequest, request: Request):
    """
    Verify admin/reviewer username+password against shared.admin_users.
    Returns signed JWT on success. Constant-shape response on failure
    (401 whether username doesn't exist or password is wrong — no
    enumeration signal).
    """
    if not body.username or not body.password:
        raise HTTPException(status_code=400, detail="Username and password required")

    pool: asyncpg.Pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id::text, username, password_hash, role::text, is_active
            FROM shared.admin_users
            WHERE username = $1
            """,
            body.username,
        )

    # Always run bcrypt compare (even on no-row) to keep response timing
    # consistent — avoids leaking "username exists" via fast-path timing.
    dummy_hash = "$2b$12$" + "0" * 53  # syntactically valid bcrypt hash, never matches
    hash_to_check = row["password_hash"] if row else dummy_hash
    password_ok = _verify_password(body.password, hash_to_check)

    if not row or not row["is_active"] or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = _create_admin_jwt(
        admin_id=row["id"],
        username=row["username"],
        role=row["role"],
    )

    return AdminLoginResponse(
        token=token,
        admin_id=row["id"],
        username=row["username"],
        role=row["role"],
    )


class VerifyAdminResponse(BaseModel):
    admin_id: str
    username: str
    role: str
    valid: bool


@router.post("/verify-admin", response_model=VerifyAdminResponse)
async def verify_admin_token(token: str):
    """
    Verify an admin JWT. Used by Next.js middleware (server-side), mirrors
    /auth/verify-tenant. Returns 401 if invalid/expired.

    NOTE: does not re-check shared.admin_users.is_active on every call
    (stateless JWT, same trade-off as verify-tenant) — a deactivated admin
    stays valid until their token expires (JWT_EXPIRY_H = 24h). Acceptable
    for now (small trusted user set); revisit if that window matters later.
    """
    payload = verify_jwt(token)
    if payload.get("role") not in ("admin", "reviewer"):
        # Explicit whitelist — same secret/alg means any token minted with
        # a different role (e.g. tenant) would otherwise decode fine here.
        raise HTTPException(status_code=401, detail="Not an admin token")
    return VerifyAdminResponse(
        admin_id=payload["sub"],
        username=payload["username"],
        role=payload["role"],
        valid=True,
    )
