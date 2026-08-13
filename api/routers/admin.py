# api/routers/admin.py
# P2-S5 — Multi-tenant onboarding + billing metrics
import hashlib
import io
import json
import os
import secrets
from datetime import datetime, timezone
from uuid import UUID
from typing import Optional
import asyncpg
import boto3
from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from services.notifications import NotificationService, EventType
from services.acp_planning.quarter import (
    QuarterPlanVersionNotFoundError,
    QuarterPlanVersionNotPendingError,
    approve_quarter_plan_version,
    plan_quarter,
    save_quarter_plan_version,
)
from services.acp_planning.runway import runway_map
from services.acp_planning.tenant_config import (
    TenantNotFoundError,
    fetch_tenant_planning_config,
    save_tenant_planning_config,
)
from services.acp_shared.marketplace_estimates import runway_months

router = APIRouter(prefix="/admin", tags=["admin"])
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

PLAN_LIMITS = {
    "starter":  {"rpm": 60,   "tours_per_month": 100},
    "growth":   {"rpm": 300,  "tours_per_month": 500},
    "business": {"rpm": 1000, "tours_per_month": 2000},
    "internal": {"rpm": 60,   "tours_per_month": 999999},
}

# AA-309 [N1] commercial-decision (Nghiep, confirmed before build, 08/08/2026) — fixed vocabulary
# for tenant_atom_state.assigned_angle (migration 098). 7 angles: the 3 illustrative examples from
# AA-309's original description (culinary_people/physical_terrain/culture_craft) plus 4 more, sized
# to give headroom above AA-332's own cited ceiling of ~3-5 tenants per (destination, source market)
# before a new destination must open -- some destinations won't fit every angle equally well (a
# luxury_leisure framing may not suit a budget trekking country), so slack beyond the exact tenant
# ceiling matters. Each is a generic narrative lens applicable across destinations, not tied to one
# country, so the same underlying atom facts can genuinely read differently depending which angle a
# tenant is assigned. Mirrors migration 098's own CHECK constraint — keep both in sync if this list
# ever changes.
ASSIGNED_ANGLES = {
    "culinary_people":    "Ẩm thực & Con người",
    "physical_terrain":   "Thể lực & Địa hình",
    "culture_craft":      "Văn hoá & Thủ công",
    "nature_wildlife":    "Thiên nhiên & Hoang dã",
    "luxury_leisure":     "Sang trọng & Nghỉ dưỡng",
    "family_group":       "Gia đình & Trải nghiệm nhóm",
    "wellness_spiritual": "Tâm linh & Chữa lành",
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
    # AA-384: caller-chosen posting cadence, no longer implied by plan_tier (was
    # POSTS_PER_WEEK_BY_PLAN_TIER, removed). Required, no default -- every tenant states its own
    # cadence at creation. 1-14 is the validation range confirmed in the AA-384 build task (a
    # generous ceiling, not a real technical limit).
    posts_per_week: int = Field(..., ge=1, le=14)


class CreateTenantResponse(BaseModel):
    tenant_id: str
    name: str
    slug: str
    plan_tier: str
    posts_per_week: int
    api_key: str
    rate_limit_rpm: int
    is_active: bool
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
    """AA-309 [N1] change: `is_active` now starts `false` (was `true`) -- a new tenant stays
    inactive until Gate A approval (`POST /tenants/{id}/gate-a/approve`) flips it, so nothing can
    run production for a tenant that hasn't been reviewed. This function itself never touched
    silver_aa_internal.raw_tours (no code to remove here) -- that "tenant brings its own tours"
    assumption lives only in list_tenants()/get_tenant_details() below, the old ACP v1 shape N1
    deliberately does not extend: a new tenant's tours come from acp_shared.tenant_atom_state
    (seeded from a finalized acp_shared.marketplace_portfolios row via POST .../seed-atoms), never
    from rows the tenant uploads under its own tenant_id."""
    verify_admin_secret(x_admin_secret)

    if body.plan_tier not in PLAN_LIMITS:
        raise HTTPException(status_code=400, detail=f"Invalid plan_tier. Choose: {list(PLAN_LIMITS.keys())}")

    rpm = PLAN_LIMITS[body.plan_tier]["rpm"]
    plaintext = f"cis_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT tenant_id FROM shared.tenants WHERE slug = $1", body.slug
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already exists")

        async with conn.transaction():
            tenant_id = await conn.fetchval("""
                INSERT INTO shared.tenants
                    (name, slug, plan_tier, posts_per_week, api_key_hash, rate_limit_rpm, is_active)
                VALUES ($1, $2, $3::plan_tier_enum, $4, $5, $6, false)
                RETURNING tenant_id
            """, body.name, body.slug, body.plan_tier, body.posts_per_week, key_hash, rpm)

            # Quota ledger — default limits per plan
            plan_limits = PLAN_LIMITS.get(body.plan_tier, PLAN_LIMITS["starter"])
            await conn.execute("""
                INSERT INTO acp_shared.acp_quota_ledger
                    (tenant_id, s2_runs_limit, s3_runs_limit, s4_blogs_limit)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (tenant_id) DO NOTHING
            """, tenant_id, 10, 10, 50)

            # Empty brand rules row — populated later via brand-brief upload
            # ON CONFLICT omitted: no unique constraint on (tenant_id, is_active);
            # duplicate guard relies on the slug uniqueness check above.
            has_rules = await conn.fetchval(
                "SELECT 1 FROM shared.tenant_brand_rules WHERE tenant_id = $1 LIMIT 1",
                tenant_id,
            )
            if not has_rules:
                # AA-309 [N1] live-verify fix (08/08/2026): shared.tenant_brand_rules.brand_name is
                # TEXT NOT NULL with no column default (confirmed live, information_schema) -- this
                # bare INSERT has always violated that constraint, discovered only by actually
                # running create_tenant() against the real dev DB (not visible from reading the code
                # or the schema in isolation). Pre-existing bug in AA-63's own code, not introduced
                # by N1 -- fixed here because N1 categorically depends on create_tenant() succeeding.
                # body.name is a real, already-available value (not a placeholder) -- overwritten
                # later by the real brand-brief upload flow (upload_brand_brief()) if one happens.
                await conn.execute(
                    "INSERT INTO shared.tenant_brand_rules (tenant_id, brand_name) VALUES ($1, $2)",
                    tenant_id, body.name,
                )

            # Onboarding audit trail
            await conn.execute("""
                INSERT INTO acp_shared.audit_log
                    (tenant_id, actor, action, resource_type, resource_id, details)
                VALUES ($1, 'admin_api', 'agency.onboard', 'tenant', $2, $3::jsonb)
            """, str(tenant_id), str(tenant_id), json.dumps({
                "name": body.name, "plan_tier": body.plan_tier, "posts_per_week": body.posts_per_week,
            }))

    return CreateTenantResponse(
        tenant_id=str(tenant_id),
        name=body.name,
        slug=body.slug,
        plan_tier=body.plan_tier,
        posts_per_week=body.posts_per_week,
        api_key=plaintext,
        rate_limit_rpm=rpm,
        is_active=False,
        message="Store this API key securely — it will not be shown again. "
                "Tenant is inactive until Gate A approval (POST /tenants/{tenant_id}/gate-a/approve).",
    )

# ── GET /admin/tenants — List all tenants + usage ────────────────────────────


@router.get("/tenants", summary="List all tenants with usage stats")
async def list_tenants(
    request: Request,
    x_admin_secret: str = Header(None),
):
    """AA-389 (reopened): this endpoint used to return active tenants only (`WHERE t.is_active =
    true`), so a brand-new tenant — is_active=false by design until Gate A approves it — vanished
    from the UI the instant it was created, with no way to click back into it and finish
    onboarding. Now also returns `pending_tenants` (is_active=false) alongside the unchanged
    `tenants` (active) list, each carrying its real onboarding progress (seeded / angle_assigned /
    gate_a_status) read from acp_shared.tenant_atom_state + tenant_onboarding — not inferred from
    is_active alone, since is_active stays false for the entire pending window regardless of which
    step the tenant is actually on."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                t.tenant_id, t.name, t.slug, t.plan_tier::text, t.posts_per_week,
                t.country, t.rate_limit_rpm, t.is_active, t.created_at,
                COALESCE(u.api_calls_used, 0)          AS api_calls_used,
                COALESCE(u.quota_tours_pct, 0)         AS quota_tours_pct,
                COALESCE(u.quota_calls_pct, 0)         AS quota_calls_pct,
                COALESCE(u.tours_overage, 0)           AS tours_overage,
                COALESCE(u.overage_usd, 0)             AS overage_usd,
                COALESCE(u.llm_cost_usd, 0)            AS llm_cost_usd,
                COALESCE(u.tours_quota_monthly, 0)     AS tours_quota_monthly,
                COALESCE(u.api_calls_quota_monthly, 0) AS api_calls_quota_monthly,
                COALESCE(u.price_usd_monthly, 0)       AS price_usd_monthly,
                COUNT(rt.tour_id) FILTER (WHERE rt.source_status::text = 'active')     AS source_active,
                COUNT(rt.tour_id) FILTER (WHERE rt.source_status::text = 'superseded') AS source_superseded,
                COUNT(rt.tour_id) FILTER (WHERE rt.source_status::text = 'trashed')    AS source_trashed,
                COUNT(pt.tour_id) FILTER (WHERE pt.master_status::text = 'active')     AS master_active,
                COUNT(pt.tour_id) FILTER (WHERE pt.master_status::text = 'inactive')   AS master_inactive,
                COUNT(pt.tour_id) FILTER (WHERE pt.master_status::text = 'trashed')    AS master_trashed
            FROM shared.tenants t
            LEFT JOIN shared.v_tenant_monthly_usage u
                ON u.tenant_id = t.tenant_id
            LEFT JOIN silver_aa_internal.raw_tours rt
                ON rt.tenant_id = t.tenant_id
            LEFT JOIN gold_aa_internal.published_tours pt
                ON pt.tenant_id = t.tenant_id
            WHERE t.is_active = true
            GROUP BY t.tenant_id, t.name, t.slug, t.plan_tier, t.posts_per_week, t.country,
                     t.rate_limit_rpm, t.is_active, t.created_at,
                     u.api_calls_used, u.quota_tours_pct, u.quota_calls_pct,
                     u.tours_overage, u.overage_usd, u.llm_cost_usd,
                     u.tours_quota_monthly, u.api_calls_quota_monthly, u.price_usd_monthly
            ORDER BY t.created_at
        """)

        pending_rows = await conn.fetch("""
            SELECT
                t.tenant_id, t.name, t.slug, t.plan_tier::text, t.posts_per_week,
                t.country, t.created_at,
                COUNT(tas.tour_id)                        AS seeded_tour_count,
                BOOL_OR(tas.assigned_angle IS NOT NULL)    AS angle_assigned,
                to_.approval_status
            FROM shared.tenants t
            LEFT JOIN acp_shared.tenant_atom_state tas ON tas.tenant_id = t.tenant_id
            LEFT JOIN acp_shared.tenant_onboarding to_ ON to_.tenant_id = t.tenant_id
            WHERE t.is_active = false
            GROUP BY t.tenant_id, t.name, t.slug, t.plan_tier, t.posts_per_week, t.country,
                     t.created_at, to_.approval_status
            ORDER BY t.created_at
        """)
    return {
        "tenants": [
            {
                "tenant_id":      str(r["tenant_id"]),
                "name":           r["name"],
                "slug":           r["slug"],
                "plan_tier":      str(r["plan_tier"]),
                "posts_per_week": r["posts_per_week"],
                "country":        r["country"],
                "rate_limit_rpm": r["rate_limit_rpm"],
                "is_active":      r["is_active"],
                "created_at":     r["created_at"].isoformat(),
                "plan": {
                    "tours_quota_monthly":     r["tours_quota_monthly"],
                    "api_calls_quota_monthly": r["api_calls_quota_monthly"],
                    "price_usd_monthly":       float(r["price_usd_monthly"]),
                },
                "this_month": {
                    "tours_rewritten":  r["source_active"],
                    "api_calls_used":   r["api_calls_used"],
                    "quota_tours_pct":  float(r["quota_tours_pct"]),
                    "quota_calls_pct":  float(r["quota_calls_pct"]),
                    "tours_overage":    r["tours_overage"],
                    "overage_usd":      float(r["overage_usd"]),
                    "llm_cost_usd":     float(r["llm_cost_usd"]),
                },
                "lifecycle": {
                    "source_active":     r["source_active"],
                    "source_superseded": r["source_superseded"],
                    "source_trashed":    r["source_trashed"],
                    "master_active":     r["master_active"],
                    "master_inactive":   r["master_inactive"],
                    "master_trashed":    r["master_trashed"],
                },
            }
            for r in rows
        ],
        "total": len(rows),
        "pending_tenants": [
            {
                "tenant_id":      str(r["tenant_id"]),
                "name":           r["name"],
                "slug":           r["slug"],
                "plan_tier":      str(r["plan_tier"]),
                "posts_per_week": r["posts_per_week"],
                "country":        r["country"],
                "created_at":     r["created_at"].isoformat(),
                "onboarding": {
                    "seeded":            r["seeded_tour_count"] > 0,
                    "seeded_tour_count": r["seeded_tour_count"],
                    "angle_assigned":    bool(r["angle_assigned"]),
                    "gate_a_status":     r["approval_status"] or "not_started",
                },
            }
            for r in pending_rows
        ],
        "pending_total": len(pending_rows),
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
            # AA-389: this generic route used to be able to activate a tenant that never went
            # through Gate A (no seed-atoms, no assigned_angle, no approval) — a one-click bypass
            # of the "REQUIRED/NEVER-auto" guarantee gate-a/approve exists to enforce. Deactivation
            # (is_active=false, e.g. suspending an existing tenant) stays unrestricted; activation
            # is only allowed here for a tenant that has ALREADY cleared Gate A once (tenant_
            # onboarding.approval_status='approved') — that's a legitimate reactivate-after-suspend,
            # not a bypass, since Gate A's own checks (angle assigned, onboarding reviewed) were
            # already satisfied. A tenant with no onboarding row, or still 'pending', must go
            # through POST .../gate-a/approve instead.
            if is_active:
                approval_status = await conn.fetchval(
                    "SELECT approval_status FROM acp_shared.tenant_onboarding WHERE tenant_id = $1",
                    tenant_id,
                )
                if approval_status != "approved":
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot activate a tenant that has not completed Gate A approval — "
                               "use POST /tenants/{tenant_id}/gate-a/approve.",
                    )
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


# ── DELETE /admin/tenants/{id} — soft delete ─────────────────────────────────


@router.delete("/tenants/{tenant_id}", summary="Soft-delete tenant (is_active=false)")
async def delete_tenant(
    tenant_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        updated = await conn.fetchval("""
            UPDATE shared.tenants SET is_active=false, updated_at=NOW()
            WHERE tenant_id=$1 RETURNING tenant_id
        """, tenant_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"status": "deleted", "tenant_id": str(tenant_id)}


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
        # ORDER BY DESC so we always get the current/most-recent month.
        # COALESCE guards: new tenants have no quota row, producing NULLs.
        usage = await conn.fetchrow("""
            SELECT
                COALESCE(api_calls_used, 0)            AS api_calls_used,
                COALESCE(quota_calls_pct, 0)           AS quota_calls_pct,
                COALESCE(api_calls_quota_monthly, 0)   AS api_calls_quota_monthly
            FROM shared.v_tenant_monthly_usage WHERE tenant_id = $1
            ORDER BY billing_month DESC LIMIT 1
        """, tenant_id)

        if is_internal:
            # Show published_tours for the internal catalog
            tours = await conn.fetch("""
                SELECT pt.id, pt.tour_id, pt.aa_name, rt.country,
                       pt.quality_score, pt.master_status::text AS master_status,
                       (SELECT gc.version_num FROM silver_aa_internal.generated_content gc
                        WHERE gc.tour_id = pt.tour_id ORDER BY gc.created_at DESC LIMIT 1) AS version_number,
                       'published'::text AS status, pt.published_at AS created_at
                FROM gold_aa_internal.published_tours pt
                LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
                ORDER BY pt.published_at DESC LIMIT 200
            """)
        else:
            tours = await conn.fetch("""
                SELECT ttv.id, NULL::uuid AS tour_id, pt.aa_name, rt.country,
                       ttv.quality_score, ttv.version_number, ttv.status,
                       'active'::text AS master_status, ttv.created_at
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
            SELECT
                system_prompt, style_guide, forbidden_words, version, updated_at,
                COALESCE(brand_type, '')         AS brand_type,
                COALESCE(core_idea, '')          AS core_idea,
                COALESCE(customer_segment, '')   AS customer_segment,
                COALESCE(customer_mindset, '')   AS customer_mindset,
                COALESCE(voice_examples, '{}'::jsonb) AS voice_examples,
                COALESCE(rewrite_language, 'en') AS rewrite_language,
                COALESCE(target_markets, ARRAY[]::text[]) AS target_markets
            FROM shared.tenant_brand_rules
            WHERE tenant_id = $1
            ORDER BY version DESC
        """, tenant_id)

    brand         = brand_rows[0] if brand_rows else None
    api_calls     = int(usage["api_calls_used"])            if usage else 0
    quota_total   = int(usage["api_calls_quota_monthly"])   if usage else 0
    quota_pct     = float(usage["quota_calls_pct"])         if usage else 0.0

    last_updated: str | None = None
    if brand and brand["updated_at"]:
        last_updated = brand["updated_at"].isoformat()

    def _parse_jsonb(value) -> dict:
        """Parse JSONB field — asyncpg may return dict or JSON string."""
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            import json as _j
            try:
                parsed = _j.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

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
                "tour_id":        str(r["tour_id"]) if r.get("tour_id") else None,
                "tour_name":      r["aa_name"] or "—",
                "country":        r["country"],
                "quality_score":  float(r["quality_score"]) if r["quality_score"] is not None else None,
                "version_number": r["version_number"],
                "status":         r["status"],
                "master_status":  r["master_status"] if r["master_status"] else "active",
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
            "system_prompt":    brand["system_prompt"]               if brand else None,
            "style_guide":      brand["style_guide"]                 if brand else None,
            "forbidden_words":  _parse_fw(brand["forbidden_words"]) if brand else [],
            "version_count":    len(brand_rows),
            "last_updated":     last_updated,
            "brand_type":       brand["brand_type"]       if brand else "",
            "core_idea":        brand["core_idea"]        if brand else "",
            "customer_segment": brand["customer_segment"] if brand else "",
            "customer_mindset": brand["customer_mindset"] if brand else "",
            "voice_examples":   _parse_jsonb(brand["voice_examples"]) if brand else {},
            "rewrite_language": brand["rewrite_language"] if brand else "en",
            "target_markets":   list(brand["target_markets"]) if brand else [],
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


# ── POST /admin/tenants/{id}/brand-brief ─────────────────────────────────────

_BRAND_BRIEF_BUCKET = "acp-bronze-867490540162"
_BRAND_BRIEF_LAMBDA = "acp-brand-brief-parser"
_MAX_DOCX_BYTES = 5 * 1024 * 1024  # 5 MB


@router.post("/tenants/{tenant_id}/brand-brief", summary="Upload and parse brand brief DOCX")
async def upload_brand_brief(
    tenant_id: str,
    request: Request,
    file: UploadFile = File(...),
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)

    content_type = file.content_type or ""
    if "officedocument.wordprocessingml" not in content_type and not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="File must be a .docx document")

    data = await file.read()
    if len(data) > _MAX_DOCX_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds 5 MB limit")

    iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    s3_key = f"brand-briefs/{tenant_id}/{iso_ts}.docx"

    s3 = boto3.client("s3", region_name="us-west-1")
    try:
        s3.upload_fileobj(io.BytesIO(data), _BRAND_BRIEF_BUCKET, s3_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"S3 upload failed: {e}")

    lam = boto3.client("lambda", region_name="us-west-1")
    payload = json.dumps({
        "tenant_id": tenant_id,
        "s3_bucket": _BRAND_BRIEF_BUCKET,
        "s3_key": s3_key,
    }).encode()
    try:
        resp = lam.invoke(
            FunctionName=_BRAND_BRIEF_LAMBDA,
            InvocationType="RequestResponse",
            Payload=payload,
        )
        result = json.loads(resp["Payload"].read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Lambda invoke failed: {e}")

    if result.get("status") == "error":
        raise HTTPException(status_code=422, detail=result.get("warnings", ["Unknown parse error"]))

    # Persist S3 key for brand brief reuse on next S0 run (M1)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE shared.tenants SET last_brand_brief_s3_key=$2, updated_at=NOW() WHERE tenant_id=$1::uuid",
            tenant_id, s3_key,
        )

    return {**result, "brand_brief_s3_key": s3_key}


# ── POST /admin/tenants/{id}/offboard — GDPR offboard ────────────────────────

class OffboardRequest(BaseModel):
    reason: str


@router.post("/tenants/{tenant_id}/offboard", summary="GDPR offboarding — cancel tenant + revoke key")
async def offboard_tenant(
    tenant_id: str,
    body: OffboardRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    """
    GDPR offboarding: cancel tenant, revoke API key, log for data deletion.
    S3 data deletion must be run manually (Lambda or CLI) after 14 days.
    PRD v1.0 §3.2.
    """
    verify_admin_secret(x_admin_secret)
    if not body.reason.strip():
        raise HTTPException(status_code=400, detail="reason is required for GDPR audit trail")

    try:
        UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid tenant_id UUID")

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        tenant = await conn.fetchrow(
            "SELECT tenant_id, name, cancelled_at FROM shared.tenants WHERE tenant_id=$1::uuid",
            tenant_id,
        )
        if not tenant:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")
        if tenant["cancelled_at"]:
            raise HTTPException(
                status_code=409,
                detail=f"Tenant already offboarded at {tenant['cancelled_at'].isoformat()}",
            )

        async with conn.transaction():
            await conn.execute(
                """
                UPDATE shared.tenants
                SET cancelled_at        = NOW(),
                    cancellation_reason = $2,
                    is_active           = FALSE,
                    api_key_hash        = 'REVOKED_' || tenant_id::text,
                    updated_at          = NOW()
                WHERE tenant_id = $1::uuid
                """,
                tenant_id, body.reason,
            )
            await conn.execute(
                """
                INSERT INTO acp_shared.audit_log
                    (tenant_id, actor, action, resource_type, resource_id, details)
                VALUES ($1, 'admin_api', 'agency.offboard', 'tenant', $1, $2::jsonb)
                """,
                tenant_id, json.dumps({
                    "reason": body.reason,
                    "name": tenant["name"],
                    "note": "S3 data deletion: acp-cis-*/{tenant_id}/ — schedule Lambda after 14d",
                }),
            )

    return {
        "tenant_id": tenant_id,
        "status": "offboarded",
        "api_key": "REVOKED",
        "note": f"S3 prefix acp-cis-bronze-867490540162/{tenant_id}/ must be deleted after 14 days.",
    }


# ── POST /admin/tenants/{id}/seed-atoms — N1 step 2 ──────────────────────────

class SeedAtomsRequest(BaseModel):
    portfolio_id: UUID


@router.post("/tenants/{tenant_id}/seed-atoms", summary="N1 step 2 — seed tenant_atom_state from a finalized portfolio")
async def seed_tenant_atoms(
    tenant_id: UUID,
    body: SeedAtomsRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    """AA-309 [N1] — deliberately a SEPARATE step from create_tenant() (Nghiep, confirmed before
    build): a tenant can be retried here without recreating the tenant row if seeding fails.
    Idempotent re-run with the SAME portfolio_id is a safe no-op (ON CONFLICT DO NOTHING on both
    inserts); a second call with a DIFFERENT portfolio_id is rejected (409) rather than silently
    mixing two portfolios' tour lists into one tenant's atom state."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        tenant = await conn.fetchval("SELECT tenant_id FROM shared.tenants WHERE tenant_id = $1", tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")

        portfolio = await conn.fetchrow(
            "SELECT portfolio_id, tour_ids, status FROM acp_shared.marketplace_portfolios WHERE portfolio_id = $1",
            body.portfolio_id,
        )
        if not portfolio:
            raise HTTPException(status_code=404, detail=f"Portfolio {body.portfolio_id} not found")
        if portfolio["status"] != "finalized":
            raise HTTPException(
                status_code=400,
                detail=f"Portfolio {body.portfolio_id} is '{portfolio['status']}', not 'finalized'",
            )

        existing_onboarding = await conn.fetchrow(
            "SELECT portfolio_id FROM acp_shared.tenant_onboarding WHERE tenant_id = $1", tenant_id,
        )
        if existing_onboarding and existing_onboarding["portfolio_id"] != body.portfolio_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Tenant {tenant_id} already seeded from portfolio "
                    f"{existing_onboarding['portfolio_id']} — cannot reseed from a different portfolio"
                ),
            )

        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO acp_shared.tenant_atom_state (tenant_id, tour_id)
                SELECT $1, unnest($2::uuid[])
                ON CONFLICT (tenant_id, tour_id) DO NOTHING
                """,
                tenant_id, portfolio["tour_ids"],
            )
            await conn.execute(
                """
                INSERT INTO acp_shared.tenant_onboarding (tenant_id, portfolio_id)
                VALUES ($1, $2)
                ON CONFLICT (tenant_id) DO NOTHING
                """,
                tenant_id, body.portfolio_id,
            )

        seeded_count = await conn.fetchval(
            "SELECT count(*) FROM acp_shared.tenant_atom_state WHERE tenant_id = $1", tenant_id,
        )

    return {
        "tenant_id": str(tenant_id),
        "portfolio_id": str(body.portfolio_id),
        "seeded_tour_count": seeded_count,
    }


# ── PATCH /admin/tenants/{id}/angle — N1 step 3 ──────────────────────────────

class AssignAngleRequest(BaseModel):
    assigned_angle: str


@router.patch("/tenants/{tenant_id}/angle", summary="N1 step 3 — assign the tenant's anti-cannibalization angle")
async def assign_tenant_angle(
    tenant_id: UUID,
    body: AssignAngleRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    """Applies to every tenant_atom_state row for this tenant at once (same value on every row —
    AA-309 build task decision: angle is a per-TENANT decision, denormalized onto the per-tour
    table rather than a separate 1-row-per-tenant table). Validated against the fixed
    ASSIGNED_ANGLES vocabulary — never free text."""
    verify_admin_secret(x_admin_secret)
    if body.assigned_angle not in ASSIGNED_ANGLES:
        raise HTTPException(
            status_code=400,
            detail=f"assigned_angle must be one of {list(ASSIGNED_ANGLES.keys())}",
        )

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE acp_shared.tenant_atom_state
            SET assigned_angle = $2, updated_at = now()
            WHERE tenant_id = $1
            """,
            tenant_id, body.assigned_angle,
        )
    updated = int(result.split()[-1])
    if updated == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No tenant_atom_state rows for tenant {tenant_id} — run seed-atoms first",
        )

    return {
        "tenant_id": str(tenant_id),
        "assigned_angle": body.assigned_angle,
        "assigned_angle_label": ASSIGNED_ANGLES[body.assigned_angle],
        "tour_rows_updated": updated,
    }


# ── GET /admin/tenants/{id}/mirror — N1 steps 4+5 ────────────────────────────

@router.get("/tenants/{tenant_id}/mirror", summary="N1 steps 4+5 — Mirror: real atom count + runway info")
async def get_tenant_mirror(
    tenant_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
):
    """AA-384 product-direction change: this endpoint is now PURELY INFORMATIONAL — no upsell
    language, no "next plan tier" suggestion. Pre-paying-customer stage, >700-tour catalog: atom
    scarcity is not a real concern yet, so a tier-upgrade nudge here would be selling against a
    limit that doesn't actually bind. posts_per_week now comes straight from shared.tenants
    (tenant's own free choice at creation, migration 099) — no plan_tier lookup at all.

    Still never reads acp_shared.marketplace_portfolios.atom_snapshot (that's a Marketplace-time
    snapshot that can go stale — atoms starred/deleted/added before onboarding actually happens).
    Always a FRESH COUNT(*) against acp_contract.tour_atoms for this tenant's seeded tour_ids, and
    still calls runway_months() directly (services.acp_shared.marketplace_estimates, AA-330 Phần B)
    with the UNCHANGED formula — AA-384 only changes how the result is presented, not computed."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        tenant = await conn.fetchrow(
            "SELECT tenant_id, plan_tier::text AS plan_tier, posts_per_week "
            "FROM shared.tenants WHERE tenant_id = $1",
            tenant_id,
        )
        if not tenant:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")

        state_rows = await conn.fetch(
            "SELECT tour_id, assigned_angle FROM acp_shared.tenant_atom_state WHERE tenant_id = $1",
            tenant_id,
        )
        if not state_rows:
            raise HTTPException(
                status_code=404,
                detail=f"No tenant_atom_state rows for tenant {tenant_id} — run seed-atoms first",
            )
        tour_ids = [r["tour_id"] for r in state_rows]
        assigned_angle = state_rows[0]["assigned_angle"]

        atom_count = await conn.fetchval(
            """
            SELECT count(*) FROM acp_contract.tour_atoms
            WHERE tour_id = ANY($1) AND NOT deleted AND NOT is_empty_marker
            """,
            tour_ids,
        )

    plan_tier = tenant["plan_tier"]
    posts_per_week = tenant["posts_per_week"]
    months = runway_months(atom_count, posts_per_week)

    message = (
        f"Với nhịp đang chọn ({posts_per_week} bài/tuần), nội dung hiện có đủ dùng khoảng "
        f"{months} tháng."
        if months is not None
        else "Không thể ước tính thời lượng nội dung với nhịp bài hiện tại."
    )

    return {
        "tenant_id": str(tenant_id),
        "plan_tier": plan_tier,
        "posts_per_week": posts_per_week,
        "tour_count": len(tour_ids),
        "atom_count": atom_count,
        "runway_months": months,
        "message": message,
        "assigned_angle": assigned_angle,
        "assigned_angle_label": ASSIGNED_ANGLES.get(assigned_angle) if assigned_angle else None,
    }


# ── GET/PUT /admin/tenants/{id}/config — AA-323 Gap 3: N4-N6 markets/channels/
# capacity config. capacity_posts_per_week reads/writes shared.tenants.posts_per_week
# (AA-384, existing single source of truth) — markets/channels read/write the new
# acp_shared.tenant_config table (migration 101). One combined form since the issue
# asked for a single place to set all three; no duplicate posts_per_week column.

class TenantConfigRequest(BaseModel):
    markets: list[str] = Field(..., min_length=1)
    channels: list[str] = Field(..., min_length=1)
    posts_per_week: int = Field(..., ge=1, le=14)


_VALID_CHANNELS = {"blog", "facebook", "tiktok", "email"}


@router.get("/tenants/{tenant_id}/config", summary="AA-323 — N4-N6 markets/channels/capacity for one tenant")
async def get_tenant_config(
    tenant_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    try:
        cfg = await fetch_tenant_planning_config(tenant_id, pool)
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return {
        "tenant_id": str(tenant_id),
        "markets": cfg.markets,
        "channels": cfg.channels,
        "posts_per_week": cfg.capacity_posts_per_week,
    }


@router.put("/tenants/{tenant_id}/config", summary="AA-323 — set N4-N6 markets/channels/capacity for one tenant")
async def update_tenant_config(
    tenant_id: UUID,
    body: TenantConfigRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    invalid = [c for c in body.channels if c not in _VALID_CHANNELS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel(s): {invalid} — must be one of {sorted(_VALID_CHANNELS)}",
        )
    pool = request.app.state.pool
    try:
        await save_tenant_planning_config(
            tenant_id, body.markets, body.channels, body.posts_per_week, pool,
        )
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_id}")
    return {
        "tenant_id": str(tenant_id),
        "markets": body.markets,
        "channels": body.channels,
        "posts_per_week": body.posts_per_week,
    }


# ── POST /admin/tenants/{id}/gate-a/approve — N1 step 6 ──────────────────────

class GateAApproveRequest(BaseModel):
    approved_by: str


@router.post("/tenants/{tenant_id}/gate-a/approve", summary="N1 step 6 — Gate A approval, tenant becomes active")
async def approve_gate_a(
    tenant_id: UUID,
    body: GateAApproveRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    """Mirrors acp_shared.quarter_plan_version's real approve pattern (AA-320) exactly:
    SELECT...FOR UPDATE row lock, reject a non-'pending' status (409, never a silent no-op on a
    second approve call), UPDATE approval_status/approved_by/approved_at. Only on success does
    shared.tenants.is_active flip to true — never earlier. Requires assigned_angle to already be
    set (step 3 must precede step 6, per the 6-step spec) — rejects an incomplete onboarding rather
    than approving a tenant with no angle assigned."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT approval_status FROM acp_shared.tenant_onboarding WHERE tenant_id = $1 FOR UPDATE",
                tenant_id,
            )
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No tenant_onboarding row for tenant {tenant_id} — run seed-atoms first",
                )
            if row["approval_status"] != "pending":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Tenant {tenant_id} onboarding is '{row['approval_status']}', "
                        "not 'pending' — cannot approve"
                    ),
                )

            has_angle = await conn.fetchval(
                """
                SELECT 1 FROM acp_shared.tenant_atom_state
                WHERE tenant_id = $1 AND assigned_angle IS NOT NULL LIMIT 1
                """,
                tenant_id,
            )
            if not has_angle:
                raise HTTPException(
                    status_code=400,
                    detail=f"Tenant {tenant_id} has no assigned_angle yet — run PATCH .../angle first",
                )

            await conn.execute(
                """
                UPDATE acp_shared.tenant_onboarding
                SET approval_status = 'approved', approved_by = $2, approved_at = now()
                WHERE tenant_id = $1
                """,
                tenant_id, body.approved_by,
            )
            await conn.execute(
                "UPDATE shared.tenants SET is_active = true, updated_at = now() WHERE tenant_id = $1",
                tenant_id,
            )

        result = await conn.fetchrow(
            """
            SELECT tenant_id, portfolio_id, approval_status, approved_by, approved_at, created_at
            FROM acp_shared.tenant_onboarding WHERE tenant_id = $1
            """,
            tenant_id,
        )

    return {
        "tenant_id": str(result["tenant_id"]),
        "portfolio_id": str(result["portfolio_id"]),
        "approval_status": result["approval_status"],
        "approved_by": result["approved_by"],
        "approved_at": result["approved_at"].isoformat() if result["approved_at"] else None,
        "created_at": result["created_at"].isoformat(),
        "tenant_is_active": True,
    }


# ── GET /admin/tenants/{id}/gate-a/status — review before approval ──────────

@router.get("/tenants/{tenant_id}/gate-a/status", summary="N1 — Gate A approval status")
async def get_gate_a_status(
    tenant_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT to_.tenant_id, to_.portfolio_id, to_.approval_status, to_.approved_by,
                   to_.approved_at, to_.created_at, t.is_active
            FROM acp_shared.tenant_onboarding to_
            JOIN shared.tenants t ON t.tenant_id = to_.tenant_id
            WHERE to_.tenant_id = $1
            """,
            tenant_id,
        )
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No tenant_onboarding row for tenant {tenant_id} — run seed-atoms first",
        )

    return {
        "tenant_id": str(row["tenant_id"]),
        "portfolio_id": str(row["portfolio_id"]),
        "approval_status": row["approval_status"],
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
        "created_at": row["created_at"].isoformat(),
        "tenant_is_active": row["is_active"],
    }


# ── PATCH /admin/master/{tour_id}/status — Toggle master active/inactive ──────

AA_INTERNAL_TENANT = "00000000-0000-0000-0000-000000000001"


@router.patch("/master/{tour_id}/status", summary="Toggle master tour active/inactive")
async def toggle_master_status(
    tour_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    body = await request.json()
    status = body.get("master_status")
    if status not in ("active", "inactive"):
        raise HTTPException(400, "master_status must be 'active' or 'inactive'")

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT aa_name FROM gold_aa_internal.published_tours WHERE tour_id=$1::uuid",
            tour_id,
        )
        if not row:
            raise HTTPException(404, "Tour not found")

        event_type = (
            EventType.MASTER_ACTIVATED if status == "active"
            else EventType.MASTER_DEACTIVATED
        )

        async with conn.transaction():
            result = await conn.execute(
                """
                UPDATE gold_aa_internal.published_tours
                SET master_status = $1::gold_aa_internal.master_status_enum
                WHERE tour_id = $2::uuid
                """,
                status, tour_id,
            )
            if result == "UPDATE 0":
                raise HTTPException(404, "Tour not found or not updated")

            await NotificationService(conn).emit(
                event_type=event_type,
                entity_type="tour",
                entity_id=tour_id,
                tenant_id=AA_INTERNAL_TENANT,
                payload={"tour_name": row["aa_name"], "new_status": status, "changed_by": "admin"},
                actor_type="admin",
            )

    return {"tour_id": tour_id, "master_status": status}


# ── PATCH /admin/tours/{tour_id}/trash — Soft-delete source tour ───────────────


@router.patch("/tours/{tour_id}/trash", summary="Soft-delete source tour (source_status=trashed)")
async def trash_source_tour(
    tour_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT src_name, tenant_id FROM silver_aa_internal.raw_tours
               WHERE tour_id=$1::uuid AND source_status != 'trashed'""",
            tour_id,
        )
        if not row:
            raise HTTPException(404, "Tour not found or already trashed")

        async with conn.transaction():
            result = await conn.fetchrow(
                """
                UPDATE silver_aa_internal.raw_tours
                SET source_status = 'trashed'::silver_aa_internal.source_status_enum,
                    deleted_at = NOW(),
                    deleted_by = 'admin'
                WHERE tour_id = $1::uuid AND source_status != 'trashed'
                RETURNING tour_id, source_status::text, deleted_at
                """,
                tour_id,
            )
            if not result:
                raise HTTPException(404, "Tour not found or already trashed")

            await NotificationService(conn).emit(
                event_type=EventType.SOURCE_TRASHED,
                entity_type="tour",
                entity_id=tour_id,
                tenant_id=str(row["tenant_id"]),
                payload={"tour_name": row["src_name"], "changed_by": "admin"},
                actor_type="admin",
            )

    return {
        "tour_id": tour_id,
        "source_status": "trashed",
        "deleted_at": result["deleted_at"].isoformat(),
    }


# ── PATCH /admin/tours/{tour_id}/restore — Restore trashed source tour ─────────


@router.patch("/tours/{tour_id}/restore", summary="Restore trashed source tour (source_status=active)")
async def restore_source_tour(
    tour_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT src_name, tenant_id FROM silver_aa_internal.raw_tours
               WHERE tour_id=$1::uuid AND source_status='trashed'""",
            tour_id,
        )
        if not row:
            raise HTTPException(404, "Tour not found or not in trashed state")

        async with conn.transaction():
            try:
                result = await conn.fetchrow(
                    """
                    UPDATE silver_aa_internal.raw_tours
                    SET source_status = 'active'::silver_aa_internal.source_status_enum,
                        deleted_at = NULL,
                        deleted_by = NULL
                    WHERE tour_id = $1::uuid AND source_status = 'trashed'
                    RETURNING tour_id, source_status::text
                    """,
                    tour_id,
                )
            except asyncpg.UniqueViolationError:
                raise HTTPException(
                    409,
                    "Another active tour exists in the same source group. "
                    "Set it to superseded first, then restore.",
                )
            if not result:
                raise HTTPException(404, "Tour not found or not in trashed state")

            await NotificationService(conn).emit(
                event_type=EventType.SOURCE_RESTORED,
                entity_type="tour",
                entity_id=tour_id,
                tenant_id=str(row["tenant_id"]),
                payload={"tour_name": row["src_name"], "changed_by": "admin"},
                actor_type="admin",
            )

    return {"tour_id": tour_id, "source_status": "active"}


# ── PATCH /admin/master/{tour_id}/trash — Soft-delete master tour ─────────────


@router.patch("/master/{tour_id}/trash", summary="Soft-delete master tour (master_status=trashed)")
async def trash_master_tour(
    tour_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT aa_name FROM gold_aa_internal.published_tours
               WHERE tour_id=$1::uuid AND master_status != 'trashed'""",
            tour_id,
        )
        if not row:
            raise HTTPException(404, "Tour not found or already trashed")

        async with conn.transaction():
            result = await conn.fetchrow(
                """
                UPDATE gold_aa_internal.published_tours
                SET master_status = 'trashed'::gold_aa_internal.master_status_enum,
                    deleted_at = NOW(),
                    deleted_by = 'admin'
                WHERE tour_id = $1::uuid AND master_status != 'trashed'
                RETURNING tour_id, master_status::text, deleted_at
                """,
                tour_id,
            )
            if not result:
                raise HTTPException(404, "Tour not found or already trashed")

            await NotificationService(conn).emit(
                event_type=EventType.MASTER_TRASHED,
                entity_type="tour",
                entity_id=tour_id,
                tenant_id=AA_INTERNAL_TENANT,
                payload={"tour_name": row["aa_name"], "changed_by": "admin"},
                actor_type="admin",
            )

    return {
        "tour_id": tour_id,
        "master_status": "trashed",
        "deleted_at": result["deleted_at"].isoformat(),
    }


# ── PATCH /admin/master/{tour_id}/restore — Restore trashed master tour ────────


@router.patch("/master/{tour_id}/restore", summary="Restore trashed master tour (master_status=inactive)")
async def restore_master_tour(
    tour_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT aa_name FROM gold_aa_internal.published_tours
               WHERE tour_id=$1::uuid AND master_status='trashed'""",
            tour_id,
        )
        if not row:
            raise HTTPException(404, "Tour not found or not in trashed state")

        async with conn.transaction():
            result = await conn.fetchrow(
                """
                UPDATE gold_aa_internal.published_tours
                SET master_status = 'inactive'::gold_aa_internal.master_status_enum,
                    deleted_at = NULL,
                    deleted_by = NULL
                WHERE tour_id = $1::uuid AND master_status = 'trashed'
                RETURNING tour_id, master_status::text
                """,
                tour_id,
            )
            if not result:
                raise HTTPException(404, "Tour not found or not in trashed state")

            await NotificationService(conn).emit(
                event_type=EventType.MASTER_RESTORED,
                entity_type="tour",
                entity_id=tour_id,
                tenant_id=AA_INTERNAL_TENANT,
                payload={
                    "tour_name": row["aa_name"],
                    "new_status": "inactive",
                    "changed_by": "admin",
                },
                actor_type="admin",
            )

    return {"tour_id": tour_id, "master_status": "inactive"}


# ── PATCH /admin/master/{tour_id}/activate ────────────────────────────────────


@router.patch("/master/{tour_id}/activate", summary="Set master tour to active")
async def activate_master_tour(
    tour_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT aa_name FROM gold_aa_internal.published_tours WHERE tour_id=$1::uuid",
            tour_id,
        )
        if not row:
            raise HTTPException(404, "Tour not found")

        async with conn.transaction():
            result = await conn.execute(
                """
                UPDATE gold_aa_internal.published_tours
                SET master_status = 'active'::gold_aa_internal.master_status_enum
                WHERE tour_id = $1::uuid
                """,
                tour_id,
            )
            if result == "UPDATE 0":
                raise HTTPException(404, "Tour not found or not updated")

            await NotificationService(conn).emit(
                event_type=EventType.MASTER_ACTIVATED,
                entity_type="tour",
                entity_id=tour_id,
                tenant_id=AA_INTERNAL_TENANT,
                payload={
                    "tour_name": row["aa_name"], "new_status": "active", "changed_by": "admin",
                },
                actor_type="admin",
            )

    return {"tour_id": tour_id, "master_status": "active"}


# ── PATCH /admin/master/{tour_id}/deactivate ──────────────────────────────────


@router.patch("/master/{tour_id}/deactivate", summary="Set master tour to inactive")
async def deactivate_master_tour(
    tour_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT aa_name FROM gold_aa_internal.published_tours WHERE tour_id=$1::uuid",
            tour_id,
        )
        if not row:
            raise HTTPException(404, "Tour not found")

        async with conn.transaction():
            result = await conn.execute(
                """
                UPDATE gold_aa_internal.published_tours
                SET master_status = 'inactive'::gold_aa_internal.master_status_enum
                WHERE tour_id = $1::uuid
                """,
                tour_id,
            )
            if result == "UPDATE 0":
                raise HTTPException(404, "Tour not found or not updated")

            await NotificationService(conn).emit(
                event_type=EventType.MASTER_DEACTIVATED,
                entity_type="tour",
                entity_id=tour_id,
                tenant_id=AA_INTERNAL_TENANT,
                payload={
                    "tour_name": row["aa_name"], "new_status": "inactive", "changed_by": "admin",
                },
                actor_type="admin",
            )

    return {"tour_id": tour_id, "master_status": "inactive"}


# ── GET /admin/notifications/count ────────────────────────────────────────────


@router.get("/notifications/count", summary="Count unread notifications")
async def notification_count(
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS unread FROM shared.notifications WHERE is_read = FALSE"
        )
    return {"unread": int(row["unread"])}


# ── PUT /admin/notifications/read-all ────────────────────────────────────────


@router.put("/notifications/read-all", summary="Mark all notifications read")
async def mark_all_read(
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE shared.notifications SET is_read = TRUE WHERE is_read = FALSE"
        )
    cleared = int(result.split()[-1])
    return {"cleared": cleared}


# ── GET /admin/notifications ──────────────────────────────────────────────────


@router.get("/notifications", summary="List notifications")
async def list_notifications(
    request: Request,
    x_admin_secret: str = Header(None),
    unread_only: bool = False,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    verify_admin_secret(x_admin_secret)
    where = "WHERE is_read = FALSE" if unread_only else ""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, event_type, entity_type, entity_id,
                   payload, target_roles, is_read, dispatched_at, created_at
            FROM shared.notifications
            {where}
            ORDER BY created_at DESC LIMIT $1 OFFSET $2
            """,
            limit, offset,
        )
    _event_labels = {
        "tour.pipeline.completed":  "Pipeline completed",
        "tour.pipeline.failed":     "Pipeline failed",
        "tour.brand_audit.flagged": "Brand audit flagged",
        "tour.brand_audit.fixed":   "Brand audit fixed",
        "tour.dedup.staged":        "Duplicate staged for review",
        "tour.dedup.promoted":      "Duplicate promoted",
        "tour.source.trashed":      "Source tour trashed",
        "tour.source.restored":     "Source tour restored",
        "tour.master.activated":    "Master tour activated",
        "tour.master.deactivated":  "Master tour deactivated",
        "tour.master.trashed":      "Master tour trashed",
        "tour.master.restored":     "Master tour restored",
    }

    items = []
    for r in rows:
        item = dict(r)
        item["id"] = int(item["id"])
        payload = dict(item["payload"]) if item["payload"] else {}
        item["payload"] = payload
        item["target_roles"] = list(item["target_roles"]) if item["target_roles"] else []
        item["dispatched_at"] = item["dispatched_at"].isoformat()
        item["created_at"] = item["created_at"].isoformat()
        item["title"] = _event_labels.get(item["event_type"], item["event_type"])
        item["message"] = payload.get("tour_name") or payload.get("message") or ""
        items.append(item)
    return {"items": items, "total": len(items)}


# ── PUT /admin/notifications/{notif_id}/read ─────────────────────────────────


@router.put("/notifications/{notif_id}/read", summary="Mark one notification read")
async def mark_read(
    notif_id: int,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE shared.notifications SET is_read = TRUE WHERE id = $1",
            notif_id,
        )
    return {"id": notif_id, "is_read": True}


# ── POST /admin/quarter-plan — N5 Gate B persist: compute + save pending version ──


class CreateQuarterPlanRequest(BaseModel):
    tenant_id: UUID
    year: int
    quarter: int
    markets: list[str]
    capacity_posts_per_week: int
    specials: list[str] = []
    # AA-323 Gap 1 (decision #3) — manual N5 removal. specials[] already covers
    # "force add"; this is the missing "remove" side. Never changes scoring
    # weights, only which trips are eligible for selection.
    excluded_trip_ids: list[UUID] = []


@router.post("/quarter-plan", summary="Compute a quarter plan and persist it as a pending version (AA-320)")
async def create_quarter_plan(
    body: CreateQuarterPlanRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    runway = await runway_map(body.tenant_id, body.year, body.markets, pool)
    plan = await plan_quarter(
        body.tenant_id, body.year, body.quarter, body.markets,
        body.capacity_posts_per_week, body.specials, runway, pool,
        set(body.excluded_trip_ids),
    )
    version_id = await save_quarter_plan_version(plan, pool, source="standard")

    return {
        "version_id": str(version_id),
        "approval_status": "pending",
        "plan": plan.model_dump(mode="json"),
    }


# ── POST /admin/quarter-plan/preview — AA-323 Gap 1: read-only N5 preview ──────
# Same computation as create_quarter_plan() above, but never calls
# save_quarter_plan_version() — nothing is persisted. Powers the create-plan UI's
# live checkbox override (add via specials[], remove via excluded_trip_ids) so a
# human can see the effect of a change before committing to a pending version.


@router.post("/quarter-plan/preview", summary="Compute a quarter plan without persisting it (AA-323)")
async def preview_quarter_plan(
    body: CreateQuarterPlanRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    runway = await runway_map(body.tenant_id, body.year, body.markets, pool)
    plan = await plan_quarter(
        body.tenant_id, body.year, body.quarter, body.markets,
        body.capacity_posts_per_week, body.specials, runway, pool,
        set(body.excluded_trip_ids),
    )
    return {"plan": plan.model_dump(mode="json")}


# ── GET /admin/quarter-plan/pending — Gate B queue: all pending versions ──────


@router.get("/quarter-plan/pending", summary="Gate B — list all pending quarter plan versions (AA-388)")
async def list_pending_quarter_plans(
    request: Request,
    x_admin_secret: str = Header(None),
):
    """No prior endpoint listed pending versions across tenants (AA-320 only shipped
    a per-tenant/year/quarter GET) -- confirmed with Nghiep during AA-388 STEP 0
    before adding this. Lists newest-first; joins shared.tenants for a display name
    since quarter_plan_version has no tenant column of its own (tenant_id lives on
    quarter_plan)."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT qpv.version_id, qpv.plan_id, qpv.version_no, qpv.source, qpv.created_at,
                   qp.tenant_id, qp.year, qp.quarter, t.name AS tenant_name
            FROM acp_shared.quarter_plan_version qpv
            JOIN acp_shared.quarter_plan qp ON qp.plan_id = qpv.plan_id
            JOIN shared.tenants t ON t.tenant_id = qp.tenant_id
            WHERE qpv.approval_status = 'pending'
            ORDER BY qpv.created_at DESC
            """
        )
    return {
        "items": [
            {
                "version_id": str(r["version_id"]),
                "plan_id": str(r["plan_id"]),
                "version_no": r["version_no"],
                "source": r["source"],
                "created_at": r["created_at"].isoformat(),
                "tenant_id": str(r["tenant_id"]),
                "tenant_name": r["tenant_name"],
                "year": r["year"],
                "quarter": r["quarter"],
            }
            for r in rows
        ]
    }


# ── GET /admin/quarter-plan/{tenant_id}/{year}/{quarter} — latest version for review ──


@router.get("/quarter-plan/{tenant_id}/{year}/{quarter}",
            summary="Get the latest quarter plan version (pending or approved) for review (AA-320)")
async def get_quarter_plan(
    tenant_id: UUID,
    year: int,
    quarter: int,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT qpv.version_id, qpv.version_no, qpv.payload, qpv.source,
                   qpv.approval_status, qpv.approved_by, qpv.approved_at, qpv.created_at
            FROM acp_shared.quarter_plan qp
            JOIN acp_shared.quarter_plan_version qpv ON qpv.plan_id = qp.plan_id
            WHERE qp.tenant_id = $1 AND qp.year = $2 AND qp.quarter = $3
            ORDER BY qpv.version_no DESC
            LIMIT 1
            """,
            tenant_id, year, quarter,
        )
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No quarter plan for tenant={tenant_id} year={year} quarter={quarter}",
        )

    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    return {
        "version_id": str(row["version_id"]),
        "version_no": row["version_no"],
        "source": row["source"],
        "approval_status": row["approval_status"],
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
        "created_at": row["created_at"].isoformat(),
        "plan": payload,
    }


# ── POST /admin/quarter-plan/{version_id}/approve — Gate B human approval ──────


class ApproveQuarterPlanRequest(BaseModel):
    approved_by: str


@router.post("/quarter-plan/{version_id}/approve", summary="Gate B — human approval of a quarter plan version (AA-320)")
async def approve_quarter_plan_endpoint(
    version_id: UUID,
    body: ApproveQuarterPlanRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    try:
        await approve_quarter_plan_version(version_id, body.approved_by, pool)
    except QuarterPlanVersionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except QuarterPlanVersionNotPendingError as e:
        raise HTTPException(status_code=409, detail=str(e))

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT version_id, plan_id, version_no, source,
                   approval_status, approved_by, approved_at, created_at
            FROM acp_shared.quarter_plan_version
            WHERE version_id = $1
            """,
            version_id,
        )

    return {
        "version_id": str(row["version_id"]),
        "plan_id": str(row["plan_id"]),
        "version_no": row["version_no"],
        "source": row["source"],
        "approval_status": row["approval_status"],
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
        "created_at": row["created_at"].isoformat(),
    }
