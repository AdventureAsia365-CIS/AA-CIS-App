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

AA-455 bước 1 (24/08/2026) added a 3rd use case: `publish_log` list + force-unpublish. Per
STEP0 (docs/claude_audit/AA-455-01-step0-a4-force-unpublish.md §4/§7), this stays on the SAME
`/admin/a4-oversight` FE page (already allowlisted in middleware.ts since AA-437) and the SAME
`/admin/a4` router prefix here — no new route, so no middleware change needed. Still no
flag/suspend — that stays deferred to the Command Center backlog (AA-255->259); force-unpublish
is the one action this issue scoped in.

AA-469 Việc 5 (30/08/2026) added a 4th use case: `GET /content-log` — T9/T10's quality-gate
outcomes (`acp_shared.content_piece.gate_ledger`/`held_reason`, `status IN ('held','failed')`),
the stage with the best structured error data of any LLM-using T-step but zero prior A4 path
(STEP0: docs/claude_audit/AA-469-viec5-step0-a4-feedback-loop-investigation.md). T5 (atomize)
failures did NOT need a new endpoint — they write into the SAME `review-log` table/join key as T3
(see `services/acp_produce/tenant_pipeline.py::escalate_t5_atomize_failure()`), so they surface
through the existing `/review-log` endpoint above automatically.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request

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


@router.get("/publish-log")
async def get_publish_log(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    x_admin_secret: str = Header(None),
):
    """AA-455 bước 1 — T11 delivery-state rows (acp_shared.publish_log). Deploys against an
    empty table until T11's own write path (bước 2, not built here) starts producing rows.
    Same flat-list-first shape as review-log/trust-ramp above — no server-side aggregation."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    conditions = ["1=1"]
    params: list = []
    if tenant_id:
        params.append(tenant_id)
        conditions.append(f"pl.tenant_id = ${len(params)}::uuid")
    where = " AND ".join(conditions)
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT
                pl.publish_id::text, pl.piece_id::text, pl.tenant_id::text,
                t.name AS tenant_name, t.slug AS tenant_slug,
                pl.channel, pl.status, pl.external_id, pl.external_url,
                pl.published_at, pl.unpublished_at, pl.unpublished_by,
                pl.last_error, pl.created_at
            FROM acp_shared.publish_log pl
            LEFT JOIN shared.tenants t ON t.tenant_id = pl.tenant_id
            WHERE {where}
            ORDER BY pl.created_at DESC
            LIMIT ${len(params)}
        """, *params)

    data = [
        {
            "publish_id": r["publish_id"],
            "piece_id": r["piece_id"],
            "tenant_id": r["tenant_id"],
            "tenant_name": r["tenant_name"],
            "tenant_slug": r["tenant_slug"],
            "channel": r["channel"],
            "status": r["status"],
            "external_id": r["external_id"],
            "external_url": r["external_url"],
            "published_at": r["published_at"].isoformat() if r["published_at"] else None,
            "unpublished_at": r["unpublished_at"].isoformat() if r["unpublished_at"] else None,
            "unpublished_by": r["unpublished_by"],
            "last_error": r["last_error"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    logger.info("a4_publish_log_queried", count=len(data), tenant_filter=tenant_id)
    return {"data": data, "total": len(data), "tenant_filter": tenant_id}


@router.get("/content-log")
async def get_content_log(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    x_admin_secret: str = Header(None),
):
    """AA-469 Việc 5 — T9/T10's own gap, closed: `content_piece.gate_ledger`/`held_reason` is the
    best structured error data of any LLM-using stage (per-gate pass/fail + violations, plus
    `repair_log`'s retry-feedback trail) but had ZERO A4 path before this — the data existed,
    only the read route was missing (STEP0's own "easiest gap to patch" ranking).

    AA-501 widened this from "held/failed only" to EVERY content_piece row, with full write
    context (atom/tour/goal/angle/DFS-PAA/channel) added — per Nghiệp's explicit decision this is
    the WIDEST of the two AA-501 views: "AA cần thấy MỌI THỨ tenant thấy, CỘNG THÊM chi tiết kỹ
    thuật — không phải tập con khác biệt" (AA must see everything Tenant sees, PLUS technical
    detail — not a different subset). The old held/failed-only filter would have hidden exactly
    the 'approved'/'processing' rows a lesson-log/comparison use case needs to see alongside the
    failures. `repair_log` (retry-feedback trail) is now selected too — it existed on the table
    since migration 115 but this endpoint never fetched it (STEP0 §1.5's own flagged gap).

    No real numeric "score" exists for T10 (per-criterion pass/fail, not T3's quality_score) —
    `gate_pass_count`/`gate_total_count` are computed here from `gate_ledger`'s own pass/fail
    entries as a summary, NOT a replacement for the full per-gate detail already in `gate_ledger`
    (Nghiệp: "cần phải xem chi tiết được, biết nguyên nhân rõ ràng gate nào bị held" — a total
    alone would not satisfy that).

    `publish_status` (`published`/`pending_publish`/`n/a`) — a LEFT JOIN to
    `acp_shared.publish_log` (`status = 'published'`, same convention `v1_publish.py`'s own
    `/pending` query uses): `published` when a publish_log row exists, `pending_publish` when the
    piece is `approved` but has none yet, `n/a` for anything not yet ready to publish at all
    (`held`/`failed`/`processing`).

    Same cross-tenant-by-default shape as review-log/publish-log above: optional `tenant_id`
    filter (already existed, unchanged), no hard tenant scoping — A4 is cross-tenant oversight by
    design (STEP0/AA-437).

    `channel` reads `COALESCE(cp.channel, agr.channel)` — same reasoning AA-469 Việc 4's
    flow-order fix already applied to `v1_publish.py`'s two queries on this same table.
    `angle_gate_option`/`tour_atoms` joins follow the same option_id-first (AA-497) and
    owner_scope=tenant_id conventions the tenant-facing `fetch_review()`
    (services/acp_content_writing/service.py, AA-501) uses — `tour_atoms`'s `owner_scope` filter
    here uses `cp.tenant_id` directly (a SQL column reference, not a bound per-request tenant_id
    param — this endpoint is cross-tenant, unlike the tenant-scoped Python helper).

    NOT built here (explicitly out of scope, AA-505 instead): LLM cost/token tracking — no such
    column exists on any of these tables yet."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    conditions = ["1 = 1"]
    params: list = []
    if tenant_id:
        params.append(tenant_id)
        conditions.append(f"cp.tenant_id = ${len(params)}::uuid")
    where = " AND ".join(conditions)
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT
                cp.piece_id::text, cp.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug,
                cp.angle_gate_request_id::text, agr.atom_id, agr.goal, agr.cta,
                agr.dfs_paa_snapshot, agr.trip_id,
                COALESCE(cp.channel, agr.channel) AS channel,
                cp.status, cp.held_reason, cp.gate_ledger, cp.repair_log, cp.attempt_number,
                LEFT(cp.content_text, 280) AS content_preview, cp.created_at,
                COALESCE(ago.name, ago_chosen.name) AS angle_name,
                COALESCE(ago.why_it_works, ago_chosen.why_it_works) AS angle_why_it_works,
                COALESCE(ago.formula_fit, ago_chosen.formula_fit) AS angle_formula_fit,
                COALESCE(ago.best_final_style, ago_chosen.best_final_style) AS angle_best_final_style,
                ta.text AS atom_text, ta.activity_type AS atom_activity_type,
                ta.emotional_hook AS atom_emotional_hook, ta.season_note AS atom_season_note,
                rt.src_name AS tour_name, rt.country AS tour_destination,
                pl.publish_id AS publish_id
            FROM acp_shared.content_piece cp
            JOIN acp_shared.angle_gate_request agr ON agr.request_id = cp.angle_gate_request_id
            LEFT JOIN shared.tenants t ON t.tenant_id = cp.tenant_id
            LEFT JOIN acp_shared.angle_gate_option ago ON ago.option_id = cp.angle_gate_option_id
            LEFT JOIN acp_shared.angle_gate_option ago_chosen
                ON ago_chosen.request_id = agr.request_id AND ago_chosen.chosen = true
                AND cp.angle_gate_option_id IS NULL
            LEFT JOIN acp_contract.tour_atoms ta
                ON ta.atom_id = agr.atom_id AND ta.owner_scope = cp.tenant_id::text
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = agr.trip_id
            LEFT JOIN acp_shared.publish_log pl
                ON pl.piece_id = cp.piece_id AND pl.status = 'published'
            WHERE {where}
            ORDER BY cp.created_at DESC
            LIMIT ${len(params)}
        """, *params)

    def _publish_status(status: str, published: bool) -> str:
        if published:
            return "published"
        if status == "approved":
            return "pending_publish"
        return "n/a"

    def _gate_counts(gate_ledger: list) -> dict:
        passed = sum(1 for g in gate_ledger if isinstance(g, dict) and g.get("passed"))
        return {"passed": passed, "total": len(gate_ledger)}

    data = []
    for r in rows:
        gate_ledger = _parse_jsonb(r["gate_ledger"], [])
        gate_counts = _gate_counts(gate_ledger)
        data.append({
            "piece_id": r["piece_id"],
            "tenant_id": r["tenant_id"],
            "tenant_name": r["tenant_name"],
            "tenant_slug": r["tenant_slug"],
            "angle_gate_request_id": r["angle_gate_request_id"],
            "atom_id": r["atom_id"],
            "goal": r["goal"],
            "channel": r["channel"],
            "status": r["status"],
            "held_reason": r["held_reason"],
            "gate_ledger": gate_ledger,
            "gate_pass_count": gate_counts["passed"],
            "gate_total_count": gate_counts["total"],
            "repair_log": _parse_jsonb(r["repair_log"], []),
            "attempt_number": r["attempt_number"],
            "content_preview": r["content_preview"],
            "cta": r["cta"],
            "angle": {
                "name": r["angle_name"], "why_it_works": r["angle_why_it_works"],
                "formula_fit": r["angle_formula_fit"], "best_final_style": r["angle_best_final_style"],
            } if r["angle_name"] else None,
            "atom": {
                "text": r["atom_text"], "activity_type": r["atom_activity_type"],
                "emotional_hook": r["atom_emotional_hook"], "season_note": r["atom_season_note"],
            } if r["atom_text"] else None,
            "tour": {
                "name": r["tour_name"], "destination": r["tour_destination"],
            } if r["tour_name"] else None,
            "dfs_paa_snapshot": _parse_jsonb(r["dfs_paa_snapshot"], None),
            "publish_status": _publish_status(r["status"], r["publish_id"] is not None),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })
    logger.info("a4_content_log_queried", count=len(data), tenant_filter=tenant_id)
    return {"data": data, "total": len(data), "tenant_filter": tenant_id}


@router.post("/publish-log/{publish_id}/unpublish")
async def force_unpublish(
    publish_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
    x_admin_user_id: Optional[str] = Header(None),
):
    """AA-455 bước 1 — A4's one mutating action. Only flips a `status='published'` row to
    'unpublished'; a row already unpublished/failed 404s rather than double-acting (verified
    live, see AA-455-01 implementation notes). `unpublished_by` records "admin:<id>" using the
    same `x-admin-user-id` header AA-232 already established (BFF forwards the verified JWT's
    `sub` claim) — tolerant of a missing/malformed header, same fallback shape
    admin_pipeline.py's reviewed_by handling already uses, so a legacy ADMIN_SECRET-only session
    doesn't 500, it just records "admin:unknown"."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    admin_actor = "unknown"
    if x_admin_user_id:
        try:
            admin_actor = str(UUID(x_admin_user_id))
        except (ValueError, AttributeError):
            admin_actor = "unknown"

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE acp_shared.publish_log
            SET status = 'unpublished', unpublished_at = now(), unpublished_by = $2
            WHERE publish_id = $1 AND status = 'published'
            RETURNING publish_id::text, tenant_id::text, channel, status, unpublished_at
        """, publish_id, f"admin:{admin_actor}")

    if not row:
        raise HTTPException(status_code=404, detail="publish_log row not found or already unpublished")

    logger.info("a4_force_unpublish", publish_id=str(publish_id), admin_actor=admin_actor)
    return {
        "publish_id": row["publish_id"],
        "tenant_id": row["tenant_id"],
        "channel": row["channel"],
        "status": row["status"],
        "unpublished_at": row["unpublished_at"].isoformat() if row["unpublished_at"] else None,
        "unpublished_by": f"admin:{admin_actor}",
    }
