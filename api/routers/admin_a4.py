"""
api/routers/admin_a4.py — AA-437 [A4] Cross-Tenant Oversight v1.

STEP0 (docs/claude_audit/AA-437-01-a4-step0-audit.md) confirmed: A4 was 0% built, and neither
existing `review_queue` reader (`admin_pipeline.py`'s `/admin/review-queue`,
`v1_pipeline.py`'s `/v1/pipeline/review-queue`) can serve T3 rows — both `INNER JOIN
generated_content`, which is NULL by design for every T3 (tenant QA-gate escalate) row (AA-425).
This router is deliberately new/separate rather than a patch to either — those two are wired to
the older N0-N6 admin HITL flow (approve/reject, step_fn_task_token) with actions that don't
apply to a T3 row.

v1 scope, per Nghiep's 5 decisions (Linear AA-437, 23/08/2026):
  1. Both use cases (review-log + trust-ramp) built together, read-only.
  2. Trust ramp shows CURRENT state only — no suggest_ramp_transition() automation, no
     engagement_ok/weeks_active formula (STEP0 confirmed neither is computed anywhere).
  3. No per-tenant single ramp "level" — ramp state lives on acp_deliver.packets.publish_mode,
     per-PACKET (STEP0 finding: nothing in the schema aggregates this to one tenant-level value,
     and packets for the same tenant CAN sit at different modes) — so this returns every packet
     with its own level, never collapsed.
  4/5. Route `/admin/a4-oversight` (FE), endpoints `/admin/a4/review-log` + `/admin/a4/trust-ramp`.

No flag/suspend/force-unpublish here — explicitly out of scope (AA-437's own Linear text),
deferred to the Command Center backlog (AA-255->259) if/when that gets built.
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Header, Query, Request

from api.routers.admin import verify_admin_secret

logger = structlog.get_logger()
router = APIRouter(prefix="/admin/a4", tags=["admin-a4"])


def _parse_jsonb(val, default):
    """escalate_detail arrives as a raw JSON-encoded string on this app's connections (no jsonb
    codec registered — same gap AA-314/AA-425 already found/fixed elsewhere, e.g. v1_tours.py's
    forbidden_words handling). Parse defensively rather than assume asyncpg decoded it."""
    if val is None:
        return default
    if isinstance(val, (list, dict)):
        return val
    import json
    try:
        return json.loads(val)
    except (TypeError, ValueError):
        return default


@router.get("/review-log")
async def get_review_log(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    x_admin_secret: str = Header(None),
):
    """T3 QA-gate escalation log (silver_aa_internal.review_queue, tenant_tour_version_id NOT
    NULL rows only — the N0-N6 admin-pipeline rows, keyed by generated_content_id, are a
    different flow and excluded here, same distinction STEP0 confirmed matters).

    Returns raw rows, not a server-side check_id aggregate — STEP0 already confirmed a plain
    GROUP BY over escalate_detail is enough at current volume (52 total rows, 11 T3-style) and
    the task's own guidance was to pick whichever side needs less BE logic; the FE groups
    client-side (same flat-list-first approach AA-436's own STEP0 recommended, modeled on
    AtomsTab.tsx).
    """
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    conditions = ["rq.tenant_tour_version_id IS NOT NULL"]
    params: list = []
    if tenant_id:
        params.append(tenant_id)
        conditions.append(f"rq.tenant_id = ${len(params)}::uuid")
    where = " AND ".join(conditions)
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT
                rq.id::text, rq.tour_id::text, rq.tenant_id::text,
                t.name AS tenant_name, t.slug AS tenant_slug,
                rq.tenant_tour_version_id::text, rq.failure_summary,
                rq.escalate_detail, rq.review_status, rq.created_at
            FROM silver_aa_internal.review_queue rq
            LEFT JOIN shared.tenants t ON t.tenant_id = rq.tenant_id
            WHERE {where}
            ORDER BY rq.created_at DESC
            LIMIT ${len(params)}
        """, *params)

    data = [
        {
            "id": r["id"],
            "tour_id": r["tour_id"],
            "tenant_id": r["tenant_id"],
            "tenant_name": r["tenant_name"],
            "tenant_slug": r["tenant_slug"],
            "tenant_tour_version_id": r["tenant_tour_version_id"],
            "failure_summary": r["failure_summary"],
            "escalate_detail": _parse_jsonb(r["escalate_detail"], []),
            "review_status": r["review_status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    logger.info("a4_review_log_queried", count=len(data), tenant_filter=tenant_id)
    return {"data": data, "total": len(data), "tenant_filter": tenant_id}


@router.get("/trust-ramp")
async def get_trust_ramp(request: Request, x_admin_secret: str = Header(None)):
    """Every acp_deliver.packets row with its own publish_mode (ramp state) — no per-tenant
    rollup (decision #3 above). Pure read, no suggested-next-level computation (decision #2)."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                p.packet_id::text, p.tenant_id, t.name AS tenant_name, t.slug AS tenant_slug,
                p.year, p.month, p.week, p.status, p.publish_mode,
                p.created_at, p.delivered_at
            FROM acp_deliver.packets p
            LEFT JOIN shared.tenants t ON t.tenant_id::text = p.tenant_id
            ORDER BY p.tenant_id, p.year DESC, p.month DESC, p.week DESC
        """)

    data = [
        {
            "packet_id": r["packet_id"],
            "tenant_id": r["tenant_id"],
            "tenant_name": r["tenant_name"],
            "tenant_slug": r["tenant_slug"],
            "year": r["year"],
            "month": r["month"],
            "week": r["week"],
            "status": r["status"],
            "publish_mode": r["publish_mode"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "delivered_at": r["delivered_at"].isoformat() if r["delivered_at"] else None,
        }
        for r in rows
    ]
    logger.info("a4_trust_ramp_queried", count=len(data))
    return {"data": data, "total": len(data)}
