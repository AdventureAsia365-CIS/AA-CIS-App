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
                                           fetch_approved_quarter_plan, fetch_quarter_plan_version,
                                           fetch_quarter_plan_version_history, save_quarter_plan_version)
from services.acp_planning.runway import compute_runway_map
from services.acp_planning.tenant_config import TenantNotFoundError, fetch_tenant_planning_config
from services.acp_planning.tenant_pool import (fetch_tenant_atoms_by_trip, fetch_tenant_trips,
                                                fetch_used_atom_ids)
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


@router.get(
    "/quarter-plan/history",
    summary="List every saved version of this tenant's quarter plan (AA-469 Việc 2)",
)
async def get_quarter_plan_history(
    request: Request, tenant=Depends(get_tenant),
    year: int = Query(...), quarter: int = Query(...),
):
    """Wires `fetch_quarter_plan_version_history()` (services/acp_planning/quarter.py) — the
    tenant-facing version-picker list. Returns an empty list (not 404) for a quarter that was
    never finalized — that's a real, valid answer for a history view ("nothing here yet"),
    unlike `GET /quarter-plan`'s 404 for "there's no CURRENT plan to show me right now"."""
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    versions = await fetch_quarter_plan_version_history(tenant_id, year, quarter, pool)
    return {
        "versions": [
            {
                "version_id": str(v["version_id"]), "version_no": v["version_no"],
                "approval_status": v["approval_status"], "approved_by": v["approved_by"],
                "approved_at": v["approved_at"].isoformat() if v["approved_at"] else None,
                "created_at": v["created_at"].isoformat() if v["created_at"] else None,
                "source": v["source"],
            }
            for v in versions
        ],
    }


@router.get(
    "/quarter-plan/versions/{version_id}",
    summary="Read one specific historical quarter-plan version, by id (AA-469 Việc 2)",
)
async def get_quarter_plan_version_by_id(
    version_id: UUID, request: Request, tenant=Depends(get_tenant),
):
    """Wires `fetch_quarter_plan_version()` (services/acp_planning/quarter.py, built for AA-323's
    admin-side Preview screen — STEP0 confirmed it was never imported into this tenant router
    before this task) — lets a tenant open ANY past version from `GET .../history` above,
    approved or not, not only the current one. `version_id` is a global PK (not tenant-scoped in
    the query itself, matching the underlying function's own contract) — the ownership check
    below is what keeps this from leaking another tenant's plan by guessing/enumerating ids; a
    cross-tenant version_id 404s identically to a nonexistent one, same "never leak existence"
    convention `post_metric_snapshot()` below already uses for PieceNotOwnedError."""
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    result = await fetch_quarter_plan_version(version_id, pool)
    if result is None or result["tenant_id"] != tenant_id:
        raise HTTPException(status_code=404, detail=f"No quarter plan version {version_id}")
    return {
        "version_no": result["version_no"], "approval_status": result["approval_status"],
        "plan": result["plan"].model_dump(mode="json"),
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


@router.get(
    "/slot-suggestions",
    summary="T7 slot-view + T8 atom-picker data — slot grid's suggested atoms, enriched, plus "
            "this month's free-atom pool (AA-494 Decision 6 — suggestion only, never a gate)",
)
async def get_slot_suggestions(
    request: Request, tenant=Depends(get_tenant),
    year: int = Query(...), month: int = Query(..., ge=1, le=12),
):
    """AA-494 Step 4 — T8→slot-grid wiring. Reuses `get_slot_grid()`'s exact computation
    (same config/trips/atoms/runway/quarter-plan fetch, same `compute_slot_grid()` call) rather
    than duplicating it, then adds the two things the approved UI/UX design (design doc Decision
    6) needs that the bare SlotGrid doesn't carry:
      - `atoms_by_id`: full atom detail (text/activity_type/distinctiveness/trip_name/
        destination) for every atom_id this tenant owns — both a slot's `atom_ids` (suggested)
        and the free-atom list resolve against this ONE map, so the frontend never needs a
        second lookup shape for "suggested" vs. "free" atom cards.
      - `used_atoms` / `free_atom_ids`: the atom-availability rule (`fetch_used_atom_ids()`,
        Step 3) — an atom with an approved content_piece written (real created_at) within this
        calendar month is "used" and drops off `free_atom_ids`; everything else the tenant owns
        is free, suggested-in-a-slot or not (picking a free atom outside its suggested slot is
        explicitly allowed per Decision 6's product model — slots are a priority hint, not a
        gate; `create_request()` itself still accepts ANY atom_id, unchanged by this endpoint).

    Purely additive/read-only — does not persist anything (unlike `set_channel()`'s optional
    `year`/`month` persist-on-first-use path, AA-451, moved there from `create_request()` by
    AA-469 Việc 4's flow-order fix), and does not change what `create_request()` accepts. A slot
    whose suggested atoms are ALL used just shows as fully green in the UI; it is
    never filtered out of the grid here, so the frontend can still render its "already written"
    success state (design doc UI/UX: "A slot-card that's already been written flips to a
    success/green state, showing which atom was used and the write date").
    """
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
        raise HTTPException(status_code=409, detail=str(exc))

    used_atoms = await fetch_used_atom_ids(tenant_id, year, month, pool)

    atoms_by_id: dict[str, dict] = {}
    for trip_id, atoms in atoms_by_trip.items():
        trip = trips_by_id.get(trip_id)
        for atom in atoms:
            atoms_by_id[atom.atom_id] = {
                "atom_id": atom.atom_id,
                "trip_id": str(trip_id),
                "trip_name": trip.name if trip else None,
                "destination": trip.destination if trip else None,
                "text": atom.text,
                "activity_type": atom.activity_type,
                "distinctiveness": atom.distinctiveness,
            }

    free_atom_ids = [atom_id for atom_id in atoms_by_id if atom_id not in used_atoms]

    return {
        "slot_grid": grid.model_dump(mode="json"),
        "atoms_by_id": atoms_by_id,
        "used_atoms": {atom_id: u._asdict() for atom_id, u in used_atoms.items()},
        "free_atom_ids": free_atom_ids,
        "capacity_posts_per_week": config.capacity_posts_per_week,
    }


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
