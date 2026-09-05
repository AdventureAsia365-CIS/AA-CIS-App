"""
api/routers/v1_route_hub.py — AA-510: Route/Hub read endpoints + route_pick.

`/v1/*` tenant-JWT-only router, same convention as `v1_tours.py`/`v1_planning.py` (reuses
`get_tenant` unchanged, no staff/admin path — ADR-2026-038 §0.2, tenant self-service).

Route/Hub themselves have no write endpoint here — they are entirely derived
(`services/acp_contract/route_detection.py::run_route_detection()`, fired in the background
right after T5 ranking, `v1_tours.py::_run_ranking_pipeline()`). This router only exposes what
was last derived, plus the one real write in this layer: a tenant PICKING a Route, which
snapshots it into a route_pick (ADR 0024 — no live FK, ever, back into `route.route_id`).

Was `/v1/subjects` + `acp_contract.subject` at AA-510; renamed to `/v1/route-picks` +
`acp_contract.route_pick` at AA-511 STEP0 (migration 132) — `acp_shared.subject` is a different,
unrelated concept (the AA-511 Slate proposal) and the two names collided. The old
`/v1/subjects` path had no real frontend consumer yet, so this is a deliberate breaking rename,
not a versioned/compatibility change (see docs/implementation-notes/AA-510.md).

GET  /v1/routes             — this tenant's current Routes, ordered by score (best first)
GET  /v1/hubs                — this tenant's Hubs (persist across rebuilds, never deleted)
POST /v1/route-picks         — snapshot one Route into a route_pick (`{"route_id": "..."}` body)
GET  /v1/route-picks         — this tenant's route_picks, newest first
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.routers.v1_tours import get_tenant

router = APIRouter(prefix="/v1", tags=["Route/Hub"])


def get_pool(request: Request):
    return request.app.state.pool


def _route_row_to_dict(row) -> dict:
    segment_ids = row["ordered_segment_ids"]
    if isinstance(segment_ids, str):
        segment_ids = json.loads(segment_ids)
    return {
        "route_id": row["route_id"],
        "tour_id": str(row["tour_id"]),
        "hub_id": str(row["hub_id"]) if row["hub_id"] else None,
        "hub_name": row["hub_name"],
        "ordered_segment_ids": segment_ids,
        "first_day": row["first_day"],
        "last_day": row["last_day"],
        "score": row["score"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


@router.get("/routes")
async def list_routes(request: Request, tenant=Depends(get_tenant)):
    """AA-532: `superseded_at IS NULL` — a tenant only ever picks the CURRENT version of a Route
    identity (tenant_id, tour_id, first_day, last_day); an older version stays in the table
    (never deleted, only superseded) so any Subject already pointing at it keeps resolving, but
    it must not be offered here as if it were still pick-able."""
    tenant_id = tenant["sub"]
    pool = get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT route_id, tour_id, hub_id, hub_name, ordered_segment_ids,
                   first_day, last_day, score, created_at
            FROM acp_contract.route
            WHERE tenant_id = $1::uuid AND superseded_at IS NULL
            ORDER BY score ASC, route_id ASC
        """, tenant_id)
    return {"routes": [_route_row_to_dict(r) for r in rows]}


@router.get("/hubs")
async def list_hubs(request: Request, tenant=Depends(get_tenant)):
    tenant_id = tenant["sub"]
    pool = get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT h.hub_id, h.hub_name, h.created_at, h.updated_at,
                   COUNT(r.route_id) AS route_count,
                   array_agg(DISTINCT r.tour_id::text) FILTER (WHERE r.route_id IS NOT NULL)
                       AS tour_ids
            FROM acp_contract.hub h
            -- AA-532: only a Route's CURRENT version counts toward route_count/tour_ids — a
            -- superseded row staying in the table (never deleted) must not double-count or keep
            -- a Hub looking like it still covers a tour whose Route moved on.
            LEFT JOIN acp_contract.route r ON r.hub_id = h.hub_id AND r.superseded_at IS NULL
            WHERE h.tenant_id = $1::uuid
            GROUP BY h.hub_id, h.hub_name, h.created_at, h.updated_at
            ORDER BY h.updated_at DESC
        """, tenant_id)
    return {"hubs": [
        {
            "hub_id": str(r["hub_id"]),
            "hub_name": r["hub_name"],
            "created_at": r["created_at"].isoformat(),
            "updated_at": r["updated_at"].isoformat(),
            "route_count": r["route_count"],
            "tour_ids": r["tour_ids"] or [],
        }
        for r in rows
    ]}


class CreateRoutePickRequest(BaseModel):
    route_id: str


@router.post("/route-picks")
async def pick_route(
    body: CreateRoutePickRequest, request: Request, tenant=Depends(get_tenant),
):
    tenant_id = tenant["sub"]
    pool = get_pool(request)
    from services.acp_contract.route_detection import create_route_pick

    result = await create_route_pick(
        tenant_id, body.route_id, pool, selected_by=f"tenant:{tenant_id}",
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Route no longer available — it may have been rebuilt. Refresh and pick again.",
        )
    return result


@router.get("/route-picks")
async def list_route_picks(request: Request, tenant=Depends(get_tenant)):
    tenant_id = tenant["sub"]
    pool = get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT route_pick_id, hub_name, route_snapshot, selected_at, selected_by
            FROM acp_contract.route_pick
            WHERE tenant_id = $1::uuid
            ORDER BY selected_at DESC
        """, tenant_id)
    route_picks = []
    for r in rows:
        snapshot = r["route_snapshot"]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        route_picks.append({
            "route_pick_id": str(r["route_pick_id"]),
            "hub_name": r["hub_name"],
            "route_snapshot": snapshot,
            "selected_at": r["selected_at"].isoformat(),
            "selected_by": r["selected_by"],
        })
    return {"route_picks": route_picks}


__all__ = ["router"]
