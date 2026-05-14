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
                t.tenant_id, t.name, t.slug, t.plan_tier::text,
                t.rate_limit_rpm, t.is_active, t.created_at,
                COALESCE(u.tours_rewritten, 0)      AS tours_rewritten,
                COALESCE(u.api_calls_used, 0)       AS api_calls_used,
                COALESCE(u.quota_tours_pct, 0)      AS quota_tours_pct,
                COALESCE(u.quota_calls_pct, 0)      AS quota_calls_pct,
                COALESCE(u.tours_overage, 0)        AS tours_overage,
                COALESCE(u.overage_usd, 0)          AS overage_usd,
                COALESCE(u.llm_cost_usd, 0)         AS llm_cost_usd,
                COALESCE(u.tours_quota_monthly, 0)  AS tours_quota_monthly,
                COALESCE(u.api_calls_quota_monthly, 0) AS api_calls_quota_monthly,
                COALESCE(u.price_usd_monthly, 0)    AS price_usd_monthly
            FROM shared.tenants t
            LEFT JOIN shared.v_tenant_monthly_usage u
                ON u.tenant_id = t.tenant_id
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
                "plan": {
                    "tours_quota_monthly":    r["tours_quota_monthly"],
                    "api_calls_quota_monthly": r["api_calls_quota_monthly"],
                    "price_usd_monthly":      float(r["price_usd_monthly"]),
                },
                "this_month": {
                    "tours_rewritten":   r["tours_rewritten"],
                    "api_calls_used":    r["api_calls_used"],
                    "quota_tours_pct":   float(r["quota_tours_pct"]),
                    "quota_calls_pct":   float(r["quota_calls_pct"]),
                    "tours_overage":     r["tours_overage"],
                    "overage_usd":       float(r["overage_usd"]),
                    "llm_cost_usd":      float(r["llm_cost_usd"]),
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

def _parse_fw(value) -> list:
    """Parse forbidden_words from asyncpg — may be list (pg array) or JSON string (JSONB)."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        import json as _j
        try:
            parsed = _j.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return list(value)


# ── GET /admin/tenants/{id}/details — 4-tab detail view ─────────────────────


@router.get("/tenants/{tenant_id}/details", summary="Tenant 4-tab detail view")
async def get_tenant_details(
    tenant_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        tenant = await conn.fetchrow("""
            SELECT name, slug, plan_tier::text, rate_limit_rpm, created_at
            FROM shared.tenants WHERE tenant_id = $1
        """, tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        is_internal = tenant["plan_tier"] == "internal"

        if is_internal:
            total_rewrites = await conn.fetchval(
                "SELECT COUNT(*) FROM gold_aa_internal.published_tours"
            )
        else:
            total_rewrites = await conn.fetchval("""
                SELECT COUNT(*) FROM gold_aa_internal.tenant_tour_versions
                WHERE tenant_id = $1
            """, tenant_id)

        total_cost = await conn.fetchval("""
            SELECT COALESCE(SUM(cost_usd), 0)
            FROM shared.pipeline_runs WHERE tenant_id = $1
        """, tenant_id)

        # v_tenant_monthly_usage has one row per tenant per billing_month;
        # ORDER BY DESC so we always get the current/most-recent month
        usage = await conn.fetchrow("""
            SELECT api_calls_used, quota_calls_pct, api_calls_quota_monthly
            FROM shared.v_tenant_monthly_usage WHERE tenant_id = $1
            ORDER BY billing_month DESC LIMIT 1
        """, tenant_id)

        if is_internal:
            # Show published_tours for the internal catalog
            tours = await conn.fetch("""
                SELECT pt.id, pt.aa_name, rt.country,
                       pt.quality_score, NULL::int AS version_number,
                       'published'::text AS status, pt.published_at AS created_at
                FROM gold_aa_internal.published_tours pt
                LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
                ORDER BY pt.published_at DESC LIMIT 50
            """)
        else:
            tours = await conn.fetch("""
                SELECT ttv.id, pt.aa_name, rt.country,
                       ttv.quality_score, ttv.version_number, ttv.status, ttv.created_at
                FROM gold_aa_internal.tenant_tour_versions ttv
                JOIN gold_aa_internal.published_tours pt ON pt.id = ttv.published_tour_id
                LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
                WHERE ttv.tenant_id = $1
                ORDER BY ttv.created_at DESC LIMIT 50
            """, tenant_id)

        # UNION: direct tenant runs + runs containing this tenant's tours (covers B2B tenants
        # whose tours were processed under aa_internal pipeline)
        runs = await conn.fetch("""
            SELECT * FROM (
                SELECT pr.batch_id, pr.started_at, pr.tours_total, pr.tours_passed,
                       pr.llm_model, pr.cost_usd, pr.status
                FROM shared.pipeline_runs pr
                WHERE pr.tenant_id = $1
                UNION
                SELECT pr.batch_id, pr.started_at, pr.tours_total, pr.tours_passed,
                       pr.llm_model, pr.cost_usd, pr.status
                FROM shared.pipeline_runs pr
                JOIN silver_aa_internal.raw_tours rt ON rt.batch_id = pr.batch_id
                JOIN gold_aa_internal.published_tours pt ON pt.tour_id = rt.tour_id
                JOIN gold_aa_internal.tenant_tour_versions ttv ON ttv.published_tour_id = pt.id
                WHERE ttv.tenant_id = $1
            ) _combined
            ORDER BY started_at DESC LIMIT 20
        """, tenant_id)

        brand_rows = await conn.fetch("""
            SELECT system_prompt, style_guide, forbidden_words,
                   version, updated_at, created_at
            FROM shared.tenant_brand_rules
            WHERE tenant_id = $1
            ORDER BY version DESC
        """, tenant_id)

    brand         = brand_rows[0] if brand_rows else None
    api_calls     = int(usage["api_calls_used"])            if usage else 0
    quota_total   = int(usage["api_calls_quota_monthly"])   if usage else 0
    quota_pct     = float(usage["quota_calls_pct"])         if usage else 0.0

    return {
        "summary": {
            "total_rewrites":       int(total_rewrites or 0),
            "total_llm_cost_usd":   float(total_cost or 0),
            "api_calls_this_month": api_calls,
            "quota_pct":            quota_pct,
            "plan_name":            str(tenant["plan_tier"]).title(),
            "member_since":         tenant["created_at"].isoformat()[:10],
            "tours_view":           "published" if is_internal else "rewrites",
            "pipeline_note":        None if is_internal else "Showing pipeline runs for tours in your catalog",
        },
        "rewritten_tours": [
            {
                "version_id":     str(r["id"]),
                "tour_name":      r["aa_name"] or "—",
                "country":        r["country"],
                "quality_score":  float(r["quality_score"]) if r["quality_score"] is not None else None,
                "version_number": r["version_number"],
                "status":         r["status"],
                "created_at":     r["created_at"].isoformat(),
            }
            for r in tours
        ],
        "pipeline_runs": [
            {
                "run_id":          str(r["batch_id"]),
                "started_at":      r["started_at"].isoformat(),
                "tours_processed": int(r["tours_total"] or 0),
                "tours_passed":    int(r["tours_passed"] or 0),
                "llm_model":       r["llm_model"],
                "llm_cost_usd":    float(r["cost_usd"] or 0),
                "status":          r["status"],
            }
            for r in runs
        ],
        "api_usage": {
            "total_calls":        api_calls,
            "quota_used":         api_calls,
            "quota_total":        quota_total,
            "rate_limit_per_min": tenant["rate_limit_rpm"],
        },
        "brand_rules": {
            "system_prompt":   brand["system_prompt"]               if brand else None,
            "style_guide":     brand["style_guide"]                 if brand else None,
            "forbidden_words": _parse_fw(brand["forbidden_words"]) if brand else [],
            "version_count":   len(brand_rows),
            "last_updated":    (brand["updated_at"] or brand["created_at"]).isoformat() if brand else None,
        },
    }


# ── GET /admin/tenants/{id}/rewrite-activity ─────────────────────────────────


@router.get("/tenants/{tenant_id}/rewrite-activity")
async def get_rewrite_activity(
    tenant_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                ttv.id,
                pt.aa_name AS tour_name,
                rt.country,
                ttv.version_number,
                ttv.status,
                ttv.quality_score,
                ttv.edit_source,
                ttv.created_at
            FROM gold_aa_internal.tenant_tour_versions ttv
            JOIN gold_aa_internal.published_tours pt ON pt.id = ttv.published_tour_id
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE ttv.tenant_id = $1
            ORDER BY ttv.created_at DESC
        """, tenant_id)

    return {
        "rewrite_activity": [
            {
                "version_id":     str(r["id"]),
                "tour_name":      r["tour_name"] or "—",
                "country":        r["country"],
                "version_number": r["version_number"],
                "status":         r["status"],
                "quality_score":  float(r["quality_score"]) if r["quality_score"] is not None else None,
                "edit_source":    r["edit_source"],
                "created_at":     r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


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
