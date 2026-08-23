"""
services.acp_angle_gate.service — T8 request lifecycle (workflow steps 1-7).

DB tables: acp_shared.angle_gate_request / angle_gate_option (migration 113).
"""
from __future__ import annotations

from uuid import UUID

import structlog

from services.acp_angle_gate.brand_audience import fetch_brand_audience
from services.acp_angle_gate.generate import generate_angles
from services.acp_angle_gate.goals import get_goal
from services.acp_planning.tenant_pool import fetch_tenant_trips

logger = structlog.get_logger()


class AngleGateError(Exception):
    """Base class for angle-gate lifecycle errors — this module's own domain errors, distinct
    from generate.py's AngleGenerationError (which propagates through unchanged when it happens
    mid-lifecycle, e.g. inside set_goal_and_generate())."""


class AtomNotFoundError(AngleGateError):
    pass


class RequestNotFoundError(AngleGateError):
    pass


class InvalidGoalError(AngleGateError):
    pass


class WrongStatusError(AngleGateError):
    """Raised when an action is attempted on a request in the wrong lifecycle state (e.g.
    choosing an angle before a goal has been set, or setting a goal twice)."""


_ATOM_QUERY = """
    SELECT atom_id, tour_id, text
    FROM acp_contract.tour_atoms
    WHERE atom_id = $1 AND owner_scope = $2 AND NOT deleted AND NOT is_empty_marker
"""


async def _fetch_atom_for_tenant(tenant_id: UUID, atom_id: str, pool) -> dict:
    """Tenant-scoped single-atom fetch, same owner_scope=tenant_id convention
    services.acp_planning.tenant_pool.fetch_tenant_atoms_by_trip() already established for T7
    (AA-448) — not a new security pattern. No existing function in this repo fetches ONE atom by
    id, tenant-scoped (tenant_pool.py's own function returns ALL of a tenant's atoms grouped by
    trip); kept local here rather than added to tenant_pool.py since it's T8-specific."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_ATOM_QUERY, atom_id, str(tenant_id))
    if row is None:
        raise AtomNotFoundError(f"atom_id={atom_id!r} not found for this tenant (or not owned by them)")
    return {"atom_id": row["atom_id"], "trip_id": row["tour_id"], "text": row["text"]}


async def create_request(tenant_id: UUID, atom_id: str, channel: str, pool) -> dict:
    """Workflow step 1. Validates the atom belongs to this tenant (owner_scope check) up front —
    refuses a cross-tenant atom_id here rather than only failing later at generate time."""
    atom = await _fetch_atom_for_tenant(tenant_id, atom_id, pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO acp_shared.angle_gate_request (tenant_id, atom_id, trip_id, channel)
            VALUES ($1, $2, $3, $4)
            RETURNING request_id, tenant_id, atom_id, trip_id, channel, goal, status,
                      created_at, updated_at
            """,
            tenant_id, atom["atom_id"], atom["trip_id"], channel,
        )
    return dict(row)


async def _fetch_request_row(tenant_id: UUID, request_id: UUID, pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT request_id, tenant_id, atom_id, trip_id, channel, goal, status,
                   created_at, updated_at
            FROM acp_shared.angle_gate_request
            WHERE request_id = $1 AND tenant_id = $2
            """,
            request_id, tenant_id,
        )
    if row is None:
        raise RequestNotFoundError(f"request_id={request_id} not found for this tenant")
    return row


async def set_goal_and_generate(tenant_id: UUID, request_id: UUID, goal_key: str, pool) -> dict:
    """Workflow steps 2-6: tenant picks a goal -> auto brand audience (step 3) -> formula (step
    4) -> generate 3 angles (step 5) -> recommend (step 6) — one call, matching the build task's
    own endpoint list (POST .../goal does all of steps 2-6 in a single request, no separate
    round trip between 'goal chosen' and 'angles ready')."""
    req = await _fetch_request_row(tenant_id, request_id, pool)
    if req["status"] != "pending_goal":
        raise WrongStatusError(
            f"request_id={request_id} is status={req['status']!r}, expected 'pending_goal' — "
            "a goal has already been set for this request."
        )
    goal = get_goal(goal_key)
    if goal is None:
        raise InvalidGoalError(f"Unknown goal key: {goal_key!r}")

    atom = await _fetch_atom_for_tenant(tenant_id, req["atom_id"], pool)
    brand_audience = await fetch_brand_audience(tenant_id, pool)

    trip_name = None
    destination = None
    if req["trip_id"]:
        trips = await fetch_tenant_trips(tenant_id, pool)
        trip = next((t for t in trips if t.id == req["trip_id"]), None)
        if trip:
            trip_name = trip.name
            destination = trip.destination

    angles, recommended_index, reason, cost_usd = await generate_angles(
        content_seed=atom["text"], goal=goal, channel=req["channel"],
        brand_audience=brand_audience, destination=destination, trip_name=trip_name,
    )

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE acp_shared.angle_gate_request
                SET goal = $2, status = 'pending_choice', updated_at = now()
                WHERE request_id = $1
                """,
                request_id, goal_key,
            )
            for i, a in enumerate(angles):
                await conn.execute(
                    """
                    INSERT INTO acp_shared.angle_gate_option
                        (request_id, idx, name, why_it_works, formula_fit, best_final_style,
                         recommended)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    request_id, i, a["name"], a["why_it_works"], a["formula_fit"],
                    a["best_final_style"], i == recommended_index,
                )
    logger.info(
        "angle_gate_goal_set", request_id=str(request_id), goal=goal_key,
        recommended_index=recommended_index, recommendation_reason=reason, cost_usd=cost_usd,
    )
    return await fetch_request(tenant_id, request_id, pool)


async def choose_angle(tenant_id: UUID, request_id: UUID, idx: int, pool) -> dict:
    """Workflow step 7 — the real 'gate': tenant picks 1 of the 3 (recommended or not, both
    valid — workflow: 'có thể chọn theo đề xuất... hoặc chọn khác')."""
    req = await _fetch_request_row(tenant_id, request_id, pool)
    if req["status"] != "pending_choice":
        raise WrongStatusError(
            f"request_id={request_id} is status={req['status']!r}, expected 'pending_choice'."
        )
    if idx not in (0, 1, 2):
        raise AngleGateError(f"idx must be 0, 1, or 2, got {idx!r}")

    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.execute(
                "UPDATE acp_shared.angle_gate_option SET chosen = true "
                "WHERE request_id = $1 AND idx = $2",
                request_id, idx,
            )
            if updated == "UPDATE 0":
                raise AngleGateError(f"No angle option idx={idx} for request_id={request_id}")
            await conn.execute(
                "UPDATE acp_shared.angle_gate_request SET status = 'approved', updated_at = now() "
                "WHERE request_id = $1",
                request_id,
            )
    # AA-448's own live-verify lesson (finalize response showed stale approved=false because the
    # in-memory object was never re-read after the DB write) — re-fetch fresh from the DB here
    # instead of hand-mutating an in-memory dict, so this can't repeat that bug class.
    return await fetch_request(tenant_id, request_id, pool)


async def fetch_request(tenant_id: UUID, request_id: UUID, pool) -> dict:
    req = await _fetch_request_row(tenant_id, request_id, pool)
    async with pool.acquire() as conn:
        option_rows = await conn.fetch(
            """
            SELECT idx, name, why_it_works, formula_fit, best_final_style, recommended, chosen
            FROM acp_shared.angle_gate_option
            WHERE request_id = $1
            ORDER BY idx
            """,
            request_id,
        )
    return {
        "request_id": str(req["request_id"]),
        "tenant_id": str(req["tenant_id"]),
        "atom_id": req["atom_id"],
        "trip_id": str(req["trip_id"]) if req["trip_id"] else None,
        "channel": req["channel"],
        "goal": req["goal"],
        "status": req["status"],
        "created_at": req["created_at"].isoformat(),
        "updated_at": req["updated_at"].isoformat(),
        "angles": [dict(o) for o in option_rows],
    }


__all__ = [
    "AngleGateError", "AtomNotFoundError", "RequestNotFoundError", "InvalidGoalError",
    "WrongStatusError", "create_request", "set_goal_and_generate", "choose_angle", "fetch_request",
]
