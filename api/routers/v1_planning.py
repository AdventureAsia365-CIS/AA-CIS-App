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

Endpoints in this file so far: `POST /v1/planning/quarter-plan/preview` only — a pure read/
compute, no persistence, no "approval" concept involved either way, so it needed no Gate B
replacement decision to build. The read (`GET .../quarter-plan`), finalize (`POST
.../quarter-plan`), and `GET .../slot-grid` endpoints are added once that decision is made (see
implementation notes "STOP point").
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.routers.v1_tours import get_tenant
from services.acp_planning.quarter import compute_quarter_plan
from services.acp_planning.runway import compute_runway_map
from services.acp_planning.tenant_config import TenantNotFoundError, fetch_tenant_planning_config
from services.acp_planning.tenant_pool import fetch_tenant_atoms_by_trip, fetch_tenant_trips
from services.acp_shared.dfs_relevance import fetch_dfs_relevance_by_tour

router = APIRouter(prefix="/v1/planning", tags=["tenant-planning"])


class QuarterPlanPreviewRequest(BaseModel):
    year: int
    quarter: int
    # AA-323 Gap 1 parity (specials[]/excluded_trip_ids[]) — same manual-override shape the
    # retired admin CreateQuarterPlanRequest offered, kept for T7's own preview UI to reuse.
    specials: list[str] = []
    excluded_trip_ids: list[UUID] = []


@router.post("/quarter-plan/preview", summary="Compute (not persist) this tenant's quarter plan")
async def preview_quarter_plan(
    body: QuarterPlanPreviewRequest, request: Request, tenant=Depends(get_tenant),
):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool

    try:
        config = await fetch_tenant_planning_config(tenant_id, pool)
    except TenantNotFoundError:
        # Should not happen for a tenant with a valid JWT (the token itself only exists because
        # shared.tenants had a row at login time) — 404, not 500, if it somehow does.
        raise HTTPException(status_code=404, detail="Unknown tenant")

    trips = await fetch_tenant_trips(tenant_id, pool)
    atoms_by_trip = await fetch_tenant_atoms_by_trip(tenant_id, pool)
    runway = compute_runway_map(tenant_id, body.year, trips, config.markets)
    dfs_relevance_by_trip = await fetch_dfs_relevance_by_tour([t.id for t in trips], pool)

    plan = compute_quarter_plan(
        tenant_id, body.year, body.quarter, trips, config.markets,
        config.capacity_posts_per_week, body.specials, runway, atoms_by_trip,
        excludes=set(body.excluded_trip_ids), dfs_relevance_by_trip=dfs_relevance_by_trip,
    )

    return {
        "plan": plan.model_dump(mode="json"),
        "trip_pool_size": len(trips),
        "config": {
            "markets": config.markets, "channels": config.channels,
            "capacity_posts_per_week": config.capacity_posts_per_week,
        },
    }


__all__ = ["router"]
