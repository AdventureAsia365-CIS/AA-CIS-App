"""
api/routers/v1_planning.py — AA-448: T7 Content Planning (tenant self-service quarter plan).

Per ADR-2026-038 §0.2 (tenant self-service — AA does not gate tenant content at any T0-T11
step): this is a `/v1/*` tenant-JWT-only router, same convention as `v1_tours.py`/
`v1_marketplace.py`/`v1_competitors.py` (reuses `get_tenant` unchanged, no staff/admin path).

Reads trips/atoms from `services.acp_planning.tenant_pool` (AA-448 — same source-of-truth as
`GET /v1/marketplace`, AA-444: a tenant's own rewritten tours + their own owner_scope atoms),
NOT the platform-wide `runway.fetch_trips()`/buggy `quarter.fetch_atoms_by_trip()` the old
admin-only `/admin/quarter-plan/*` routes use — see
docs/implementation-notes/AA-448-t7-content-planning.md for why those two functions are left
untouched rather than fixed in place (admin_atoms.py's preview-slotgrid and admin_produce.py's
real N7 trigger both still depend on them exactly as they are today).

markets/channels/capacity_posts_per_week are NEVER client-supplied here (unlike the retired
admin `CreateQuarterPlanRequest`) — read fresh from `fetch_tenant_planning_config()`
(services/acp_planning/tenant_config.py), the tenant's own configured values. Self-service means
the tenant plans against THEIR OWN settings, not an arbitrary value they could pass in a
request body.

Gate B (round 6, Option A): `POST /quarter-plan` (finalize) auto-approves the instant a tenant
saves it — `save_quarter_plan_version()` immediately followed by `approve_quarter_plan_version()`
(`approved_by=f"tenant:{tenant_id}"`), never a human step. See implementation notes "STOP point"
for the full reasoning and why `admin_atoms.py`/`admin_produce.py` need zero changes for this.

Locking (round 6): a quarter can only be REFUSED at finalize time if it is FULLY locked (every
week already produced-or-past, `services/acp_planning/lock_status.py`) — an in-progress quarter
stays editable, per Nghiep's explicit round-6 correction to round 4's wording.

Feedback loop (round 6, explicitly a NEW extension beyond aa-marketing-v2's own Module H — see
`services/acp_shared/content_metrics.py`'s module docstring): manual metric entry -> confidence-
gated `tour_atoms.weight` rollup -> feeds `compute_quarter_plan()`'s 5th scoring term
(`engagement_adjustment`) automatically (no new plumbing) -> `suggest_trip_reallocation()`/
`confirm_trip_reallocation()` (`services/acp_planning/trip_reallocation.py`) surfaces an
actionable, tenant-reviewed suggestion for the NEXT quarter — never auto-applied.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.routers.v1_tours import get_tenant
from services.acp_planning.allocator import compute_slot_grid
from services.acp_planning.lock_status import fetch_quarter_lock_status, is_quarter_fully_locked
from services.acp_planning.models import QuarterPlanNotApprovedError
from services.acp_planning.quarter import (approve_quarter_plan_version, compute_quarter_plan,
                                           fetch_approved_quarter_plan, save_quarter_plan_version)
from services.acp_planning.runway import compute_runway_map
from services.acp_planning.tenant_config import TenantNotFoundError, fetch_tenant_planning_config
from services.acp_planning.tenant_pool import fetch_tenant_atoms_by_trip, fetch_tenant_trips
from services.acp_planning.trip_reallocation import confirm_trip_reallocation, suggest_trip_reallocation
from services.acp_shared.content_metrics import (PieceNotFoundError, PieceNotOwnedError,
                                                 record_metric_snapshot, rollup_atom_weights)
from services.acp_shared.dfs_relevance import fetch_dfs_relevance_by_tour

router = APIRouter(prefix="/v1/planning", tags=["tenant-planning"])


async def _resolve_config(tenant_id: UUID, pool):
    try:
        return await fetch_tenant_planning_config(tenant_id, pool)
    except TenantNotFoundError:
        # Should not happen for a tenant with a valid JWT (the token itself only exists because
        # shared.tenants had a row at login time) — 404, not 500, if it somehow does.
        raise HTTPException(status_code=404, detail="Unknown tenant")


async def _compute_plan(tenant_id: UUID, year: int, quarter: int, specials: list[str],
                        excludes: set[UUID], pool):
    config = await _resolve_config(tenant_id, pool)
    trips = await fetch_tenant_trips(tenant_id, pool)
    atoms_by_trip = await fetch_tenant_atoms_by_trip(tenant_id, pool)
    runway = compute_runway_map(tenant_id, year, trips, config.markets)
    dfs_relevance_by_trip = await fetch_dfs_relevance_by_tour([t.id for t in trips], pool)
    plan = compute_quarter_plan(
        tenant_id, year, quarter, trips, config.markets, config.capacity_posts_per_week,
        specials, runway, atoms_by_trip, excludes=excludes,
        dfs_relevance_by_trip=dfs_relevance_by_trip,
    )
    return plan, config, len(trips)


class QuarterPlanRequest(BaseModel):
    year: int
    quarter: int
    # AA-323 Gap 1 parity (specials[]/excluded_trip_ids[]) — same manual-override shape the
    # retired admin CreateQuarterPlanRequest offered, kept for T7's own UI to reuse.
    specials: list[str] = []
    excluded_trip_ids: list[UUID] = []


@router.post("/quarter-plan/preview", summary="Compute (not persist) this tenant's quarter plan")
async def preview_quarter_plan(
    body: QuarterPlanRequest, request: Request, tenant=Depends(get_tenant),
):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    plan, config, trip_pool_size = await _compute_plan(
        tenant_id, body.year, body.quarter, body.specials, set(body.excluded_trip_ids), pool,
    )
    lock_status = await fetch_quarter_lock_status(tenant_id, body.year, body.quarter, pool)
    return {
        "plan": plan.model_dump(mode="json"),
        "trip_pool_size": trip_pool_size,
        "config": {
            "markets": config.markets, "channels": config.channels,
            "capacity_posts_per_week": config.capacity_posts_per_week,
        },
        "lock_status": [s.__dict__ for s in lock_status],
        "fully_locked": is_quarter_fully_locked(lock_status),
    }


@router.post("/quarter-plan", summary="Finalize this tenant's quarter plan (Gate B Option A — auto-approved)")
async def finalize_quarter_plan(
    body: QuarterPlanRequest, request: Request, tenant=Depends(get_tenant),
):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool

    lock_status = await fetch_quarter_lock_status(tenant_id, body.year, body.quarter, pool)
    if is_quarter_fully_locked(lock_status):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Q{body.quarter} {body.year} is fully locked (every week already produced or "
                "in the past) — nothing left to plan."
            ),
        )

    plan, _config, _trip_pool_size = await _compute_plan(
        tenant_id, body.year, body.quarter, body.specials, set(body.excluded_trip_ids), pool,
    )
    # AA-448 live-verify finding: acp_shared.quarter_plan_version.source has a CHECK constraint
    # allowing only 'standard'/'override' (migration 092) — a tenant's own finalize IS the
    # standard path now (Gate B Option A retired the old admin-creates/staff-approves meaning
    # this column used to distinguish), so "standard" is correct here, not a new value.
    version_id = await save_quarter_plan_version(plan, pool, source="standard")
    approved_by = f"tenant:{tenant_id}"
    await approve_quarter_plan_version(version_id, approved_by=approved_by, pool=pool)
    # Live-verify finding: approve_quarter_plan_version() only updates the DB row — the
    # in-memory `plan` object built above was never mutated, so returning it as-is here would
    # show approved=false in THIS response even though the very next GET already returns
    # approved=true (confirmed live: DB is correct, only this response's immediate payload was
    # stale). Mirror what the in-memory approve_quarter_plan() helper already does for exactly
    # this reason.
    plan.approved = True
    plan.approved_by = approved_by

    return {
        "version_id": str(version_id),
        "plan": plan.model_dump(mode="json"),
        "lock_status": [s.__dict__ for s in lock_status],
    }


@router.get("/quarter-plan", summary="Read this tenant's current finalized quarter plan")
async def get_quarter_plan(
    request: Request, tenant=Depends(get_tenant),
    year: int = Query(...), quarter: int = Query(...),
):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    plan = await fetch_approved_quarter_plan(tenant_id, year, quarter, pool)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"No finalized quarter plan for Q{quarter} {year}")
    lock_status = await fetch_quarter_lock_status(tenant_id, year, quarter, pool)
    return {
        "plan": plan.model_dump(mode="json"),
        "lock_status": [s.__dict__ for s in lock_status],
        "fully_locked": is_quarter_fully_locked(lock_status),
    }


@router.get("/slot-grid", summary="Compute (read-only) this tenant's month slot grid")
async def get_slot_grid(
    request: Request, tenant=Depends(get_tenant),
    year: int = Query(...), month: int = Query(..., ge=1, le=12),
):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    quarter = (month - 1) // 3 + 1

    quarter_plan = await fetch_approved_quarter_plan(tenant_id, year, quarter, pool)
    if quarter_plan is None:
        raise HTTPException(
            status_code=404,
            detail=f"No finalized quarter plan for Q{quarter} {year} — finalize the quarter first.",
        )

    config = await _resolve_config(tenant_id, pool)
    trips = await fetch_tenant_trips(tenant_id, pool)
    trips_by_id = {t.id: t for t in trips}
    atoms_by_trip = await fetch_tenant_atoms_by_trip(tenant_id, pool)
    runway = compute_runway_map(tenant_id, year, trips, config.markets)

    try:
        grid = compute_slot_grid(
            tenant_id, year, month, config.channels, config.capacity_posts_per_week,
            quarter_plan, runway, trips_by_id, atoms_by_trip, config.markets[0],
        )
    except QuarterPlanNotApprovedError as exc:
        # Defensive — should be unreachable since fetch_approved_quarter_plan() only ever
        # returns a plan with .approved forced True, but keep the real error type visible
        # rather than a generic 500 if this invariant is ever violated.
        raise HTTPException(status_code=409, detail=str(exc))

    return {"slot_grid": grid.model_dump(mode="json")}


# ---------------------------------------------------------------- feedback loop (round 6)

class MetricSnapshotRequest(BaseModel):
    piece_id: str
    reach: int | None = None
    engagement: int | None = None
    clicks: int | None = None


@router.post("/metrics", summary="Manually report engagement for a published piece")
async def post_metric_snapshot(
    body: MetricSnapshotRequest, request: Request, tenant=Depends(get_tenant),
):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    try:
        snapshot_id = await record_metric_snapshot(
            tenant_id, body.piece_id, body.reach, body.engagement, body.clicks,
            entered_by=tenant["sub"], pool=pool,
        )
    except PieceNotFoundError:
        raise HTTPException(status_code=404, detail=f"No piece {body.piece_id!r}")
    except PieceNotOwnedError:
        raise HTTPException(status_code=404, detail=f"No piece {body.piece_id!r}")  # never leak existence
    return {"snapshot_id": str(snapshot_id)}


@router.post("/metrics/rollup", summary="Recompute atom weights from all currently-entered metrics")
async def post_metrics_rollup(request: Request, tenant=Depends(get_tenant)):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    moved = await rollup_atom_weights(tenant_id, pool)
    return {"atoms_adjusted": len(moved), "weights": moved}


@router.get("/trip-reallocation/suggest", summary="Feedback-informed trip-reallocation suggestion for a quarter")
async def get_trip_reallocation_suggestion(
    request: Request, tenant=Depends(get_tenant),
    year: int = Query(...), quarter: int = Query(...),
):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    return await suggest_trip_reallocation(tenant_id, year, quarter, pool)


class TripReallocationConfirmRequest(BaseModel):
    year: int
    quarter: int
    accept: bool


@router.post("/trip-reallocation/confirm", summary="Accept or reject a trip-reallocation suggestion")
async def post_trip_reallocation_confirm(
    body: TripReallocationConfirmRequest, request: Request, tenant=Depends(get_tenant),
):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    return await confirm_trip_reallocation(
        pool, tenant_id, body.year, body.quarter, body.accept, actor=f"tenant:{tenant_id}",
    )


__all__ = ["router"]
