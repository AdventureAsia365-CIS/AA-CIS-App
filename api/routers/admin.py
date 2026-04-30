# api/routers/admin.py
# P2-S5 — Multi-tenant onboarding + billing metrics
import hashlib
import os
import secrets
from uuid import UUID
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/admin", tags=["admin"])
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

PLAN_LIMITS = {
    "starter":  {"rpm": 60,   "tours_per_month": 100},
    "growth":   {"rpm": 300,  "tours_per_month": 500},
    "business": {"rpm": 1000, "tours_per_month": 2000},
    "internal": {"rpm": 60,   "tours_per_month": 999999},
}

# ── Auth guard ────────────────────────────────────────────────────────────────


def verify_admin_secret(x_admin_secret: str = Header(None)):
    if not ADMIN_SECRET:
        raise HTTPException(status_code=503, detail="Admin secret not configured")
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

# ── Models ────────────────────────────────────────────────────────────────────


class CreateTenantRequest(BaseModel):
    name: str
    slug: str
    plan_tier: str = "starter"


class CreateTenantResponse(BaseModel):
    tenant_id: str
    name: str
    slug: str
    plan_tier: str
    api_key: str
    rate_limit_rpm: int
    message: str


class GenerateKeyResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    api_key: str
    message: str

# ── POST /admin/tenants — Create tenant ───────────────────────────────────────


@router.post("/tenants", response_model=CreateTenantResponse, summary="Create new tenant")
async def create_tenant(
    body: CreateTenantRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)

    if body.plan_tier not in PLAN_LIMITS:
        raise HTTPException(status_code=400, detail=f"Invalid plan_tier. Choose: {list(PLAN_LIMITS.keys())}")

    rpm = PLAN_LIMITS[body.plan_tier]["rpm"]
    plaintext = f"cis_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        # Check slug unique
        existing = await conn.fetchval(
            "SELECT tenant_id FROM shared.tenants WHERE slug = $1", body.slug
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already exists")

        tenant_id = await conn.fetchval("""
            INSERT INTO shared.tenants (name, slug, plan_tier, api_key_hash, rate_limit_rpm, is_active)
            VALUES ($1, $2, $3::plan_tier_enum, $4, $5, true)
            RETURNING tenant_id
        """, body.name, body.slug, body.plan_tier, key_hash, rpm)

    return CreateTenantResponse(
        tenant_id=str(tenant_id),
        name=body.name,
        slug=body.slug,
        plan_tier=body.plan_tier,
        api_key=plaintext,
        rate_limit_rpm=rpm,
        message="Store this API key securely — it will not be shown again.",
    )

# ── GET /admin/tenants — List all tenants + usage ────────────────────────────


@router.get("/tenants", summary="List all tenants with usage stats")
async def list_tenants(
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                t.tenant_id, t.name, t.slug, t.plan_tier,
                t.rate_limit_rpm, t.is_active, t.created_at,
                COALESCE(u.total_calls, 0)      AS total_calls,
                COALESCE(u.successful_calls, 0) AS successful_calls,
                COALESCE(u.avg_response_ms, 0)  AS avg_response_ms
            FROM shared.tenants t
            LEFT JOIN shared.v_tenant_monthly_usage u
                ON u.tenant_id = t.tenant_id
                AND DATE_TRUNC('month', u.month) = DATE_TRUNC('month', NOW())
            ORDER BY t.created_at
        """)
    return {
        "tenants": [
            {
                "tenant_id":       str(r["tenant_id"]),
                "name":            r["name"],
                "slug":            r["slug"],
                "plan_tier":       str(r["plan_tier"]),
                "rate_limit_rpm":  r["rate_limit_rpm"],
                "is_active":       r["is_active"],
                "created_at":      r["created_at"].isoformat(),
                "this_month": {
                    "total_calls":      r["total_calls"],
                    "successful_calls": r["successful_calls"],
                    "avg_response_ms":  float(r["avg_response_ms"]),
                },
            }
            for r in rows
        ],
        "total": len(rows),
    }

# ── GET /admin/tenants/{id}/usage — Billing metrics ──────────────────────────


@router.get("/tenants/{tenant_id}/usage", summary="Tenant billing metrics")
async def get_tenant_usage(
    tenant_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
    months: int = 3,
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        tenant = await conn.fetchrow(
            "SELECT name, slug, plan_tier, rate_limit_rpm FROM shared.tenants WHERE tenant_id = $1",
            tenant_id,
        )
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        usage = await conn.fetch("""
            SELECT
                DATE_TRUNC('month', month) AS month,
                total_calls, successful_calls,
                rate_limited_calls, avg_response_ms
            FROM shared.v_tenant_monthly_usage
            WHERE tenant_id = $1
              AND month >= NOW() - ($2 || ' months')::interval
            ORDER BY month DESC
        """, tenant_id, str(months))

        tours_published = await conn.fetchval("""
            SELECT COUNT(*) FROM gold_aa_internal.published_tours
            WHERE tenant_id = $1
        """, tenant_id)

    plan = str(tenant["plan_tier"])
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["starter"])

    return {
        "tenant_id":   str(tenant_id),
        "name":        tenant["name"],
        "slug":        tenant["slug"],
        "plan_tier":   plan,
        "limits": {
            "rate_limit_rpm":    tenant["rate_limit_rpm"],
            "tours_per_month":   limits["tours_per_month"],
        },
        "tours_published": tours_published,
        "monthly_usage": [
            {
                "month":               r["month"].strftime("%Y-%m"),
                "total_calls":         r["total_calls"],
                "successful_calls":    r["successful_calls"],
                "rate_limited_calls":  r["rate_limited_calls"],
                "avg_response_ms":     float(r["avg_response_ms"]),
            }
            for r in usage
        ],
    }

# ── PATCH /admin/tenants/{id} — Update plan/status ───────────────────────────


@router.patch("/tenants/{tenant_id}", summary="Update tenant plan or status")
async def update_tenant(
    tenant_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
    plan_tier: Optional[str] = None,
    is_active: Optional[bool] = None,
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        if plan_tier:
            if plan_tier not in PLAN_LIMITS:
                raise HTTPException(status_code=400, detail="Invalid plan_tier")
            rpm = PLAN_LIMITS[plan_tier]["rpm"]
            await conn.execute("""
                UPDATE shared.tenants
                SET plan_tier = $2::plan_tier_enum, rate_limit_rpm = $3, updated_at = NOW()
                WHERE tenant_id = $1
            """, tenant_id, plan_tier, rpm)

        if is_active is not None:
            await conn.execute("""
                UPDATE shared.tenants
                SET is_active = $2, updated_at = NOW()
                WHERE tenant_id = $1
            """, tenant_id, is_active)

    return {"status": "updated", "tenant_id": str(tenant_id)}

# ── POST /admin/tenants/{id}/generate-key ────────────────────────────────────


@router.post("/tenants/{tenant_id}/generate-key", response_model=GenerateKeyResponse)
async def generate_api_key(
    tenant_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tenant_id, name FROM shared.tenants WHERE tenant_id = $1", tenant_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        plaintext = f"cis_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        await conn.execute("""
            UPDATE shared.tenants
            SET api_key_hash = $1, updated_at = NOW()
            WHERE tenant_id = $2
        """, key_hash, tenant_id)

    return GenerateKeyResponse(
        tenant_id=str(row["tenant_id"]),
        tenant_name=row["name"],
        api_key=plaintext,
        message="Store this key securely — it will not be shown again.",
    )
