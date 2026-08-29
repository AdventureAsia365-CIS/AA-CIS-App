"""
services.acp_angle_gate.service — T8 request lifecycle (workflow steps 1-7).

DB tables: acp_shared.angle_gate_request / angle_gate_option (migration 113).
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

import structlog

from services.acp_angle_gate.brand_audience import fetch_brand_audience
from services.acp_angle_gate.generate import generate_angles
from services.acp_angle_gate.goals import get_goal
from services.acp_planning.allocator import compute_slot_grid, create_weekly_produce_run, persist_slot_grid
from services.acp_planning.models import QuarterPlanNotApprovedError
from services.acp_planning.quarter import fetch_approved_quarter_plan
from services.acp_planning.runway import compute_runway_map
from services.acp_planning.tenant_config import TenantNotFoundError, fetch_tenant_planning_config
from services.acp_planning.tenant_pool import fetch_tenant_atoms_by_trip, fetch_tenant_trips
from services.acp_shared.dfs_relevance import fetch_search_demand_signal

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

# AA-450: migration 114's own header comment documents why this realistically returns NULL for
# most real tenant self-service requests today — T7's tenant-facing endpoint
# (api/routers/v1_planning.py::get_slot_grid()) never calls persist_slot_grid(), so
# acp_v2_slots is populated only by admin-triggered N7 paths. Wired anyway (correct
# infrastructure for whenever a persisted slot DOES exist, e.g. an admin-run tenant, or a
# future change that persists the tenant preview) — services/acp_content_writing/ has its own
# fallback for the NULL case, not this module's job to fabricate one.
_SLOT_CTA_QUERY = """
    SELECT payload ->> 'cta_target' AS cta_target
    FROM acp_shared.acp_v2_slots
    WHERE tenant_id = $1 AND channel = $2 AND payload -> 'atom_ids' ? $3
    ORDER BY created_at DESC
    LIMIT 1
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


async def _fetch_slot_cta(tenant_id: UUID, atom_id: str, channel: str, pool) -> Optional[str]:
    """AA-450: best-effort CTA lookup from a persisted T7 slot (services.acp_planning.models
    .Slot.cta_target) matching this (tenant, channel, atom). Returns None (not an error) when no
    matching slot row exists — see this module's own comment above `_SLOT_CTA_QUERY` and
    migration 114's header for why that's the common case today, not an edge case."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_SLOT_CTA_QUERY, str(tenant_id), channel, atom_id)
    cta = row["cta_target"] if row else None
    return cta or None  # empty string from a slot with no cta_target is treated as "none"


async def _compute_and_persist_slot_cta(
    tenant_id: UUID, atom_id: str, channel: str, year: int, month: int, pool,
) -> Optional[str]:
    """AA-451 — closes the gap migration 114's header documented: T7's own tenant-facing
    endpoint (api/routers/v1_planning.py::get_slot_grid()) never persists its computed
    SlotGrid, so `_fetch_slot_cta()` above realistically finds nothing for a real self-service
    tenant. Called ONLY when that lookup already came back empty AND the caller supplied
    `year`/`month` (Option B, Nghiep-confirmed — see docs/implementation-notes/AA-451.md).

    Recomputes the tenant's month slot-grid using the EXACT SAME tenant-scoped fetchers
    `get_slot_grid()` uses (`fetch_tenant_planning_config`/`fetch_approved_quarter_plan`/
    `fetch_tenant_trips`/`fetch_tenant_atoms_by_trip`/`compute_runway_map`/`compute_slot_grid`)
    — deliberately NOT `allocate_month()`/`allocate_and_persist_week()` (services.acp_planning.
    allocator), which call the platform-wide `runway.fetch_trips()`/`quarter.fetch_atoms_by_trip
    ()` AA-445-02 found scope by the tour's OWNING tenant, not `owner_scope` — reusing those here
    would silently persist a different (wrong-tenant) slot set than what this same tenant's own
    T7 preview shows them.

    Returns None (never raises) on any "can't compute yet" state — unknown tenant, no finalized
    quarter plan, or the atom simply isn't in any slot this month (cooldown / trip not in this
    quarter's share) — exactly the same "best-effort, fall through to T9's own CTA-ask fallback"
    contract `_fetch_slot_cta()` already has."""
    try:
        config = await fetch_tenant_planning_config(tenant_id, pool)
    except TenantNotFoundError:
        return None

    quarter = (month - 1) // 3 + 1
    quarter_plan = await fetch_approved_quarter_plan(tenant_id, year, quarter, pool)
    if quarter_plan is None:
        # No finalized T7 quarter plan yet — same 404 condition get_slot_grid() itself would
        # give a tenant calling it directly. Not an error here: T8 must still work even for a
        # tenant who never touched T7.
        return None

    trips = await fetch_tenant_trips(tenant_id, pool)
    trips_by_id = {t.id: t for t in trips}
    atoms_by_trip = await fetch_tenant_atoms_by_trip(tenant_id, pool)
    runway = compute_runway_map(tenant_id, year, trips, config.markets)

    try:
        grid = compute_slot_grid(
            tenant_id, year, month, config.channels, config.capacity_posts_per_week,
            quarter_plan, runway, trips_by_id, atoms_by_trip, config.markets[0],
        )
    except QuarterPlanNotApprovedError:
        # Defensive/unreachable — fetch_approved_quarter_plan() always forces .approved=True.
        return None

    target = next((s for s in grid.slots if s.channel == channel and atom_id in s.atom_ids), None)
    if target is None:
        # Atom didn't land in a slot this month (atom floor / cooldown / trip not selected for
        # this quarter's destination share) — nothing to persist, cta stays None.
        return None

    run_id = await create_weekly_produce_run(pool, str(tenant_id), year, month, target.week)
    await persist_slot_grid(pool, run_id, str(tenant_id), target.week, grid)

    # Re-read from the DB rather than trusting `target.cta_target` in-memory — same "don't
    # hand-carry pre-write state" lesson AA-448's own finalize-response bug taught, and doubles
    # as a correctness check that the persist actually landed.
    return await _fetch_slot_cta(tenant_id, atom_id, channel, pool)


async def create_request(
    tenant_id: UUID, atom_id: str, channel: str, pool,
    year: Optional[int] = None, month: Optional[int] = None,
) -> dict:
    """Workflow step 1. Validates the atom belongs to this tenant (owner_scope check) up front —
    refuses a cross-tenant atom_id here rather than only failing later at generate time.

    AA-451: `year`/`month` are optional and backward-compatible — omitted, behavior is
    unchanged from before this change (`cta` may come back None, T9's existing ask-the-tenant
    fallback still covers it). Supplied, and no slot is already persisted for this
    (tenant, channel, atom), this computes-and-persists one on the spot (see
    `_compute_and_persist_slot_cta()`)."""
    atom = await _fetch_atom_for_tenant(tenant_id, atom_id, pool)
    cta = await _fetch_slot_cta(tenant_id, atom_id, channel, pool)
    if cta is None and year is not None and month is not None:
        cta = await _compute_and_persist_slot_cta(tenant_id, atom_id, channel, year, month, pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO acp_shared.angle_gate_request (tenant_id, atom_id, trip_id, channel, cta)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING request_id, tenant_id, atom_id, trip_id, channel, goal, cta, status,
                      created_at, updated_at
            """,
            tenant_id, atom["atom_id"], atom["trip_id"], channel, cta,
        )
    return dict(row)


async def _fetch_request_row(tenant_id: UUID, request_id: UUID, pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT request_id, tenant_id, atom_id, trip_id, channel, goal, cta, status,
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

    # AA-469 Việc 4 — DFS/PAA search-demand signal, the confirmed real gap from both this
    # task's STEP0 and the prior AA-469 STEP0 (docs/claude_audit/
    # AA-469-viec4-step0-t8-t11-chain-investigation.md §1-2): angle generation never read
    # seo_context at any layer. Only fetched when the request has a trip_id (matches
    # trip_name/destination's own guard just above — seo_context is keyed by tour_id, no
    # signal to fetch for a tripless atom). `fetch_search_demand_signal()` returns None when
    # this tour has no seo_context row at all — that's the common case for tours DFS hasn't
    # run against, not an error; build_user_prompt() below omits the block entirely for None.
    search_demand = None
    if req["trip_id"]:
        search_demand = await fetch_search_demand_signal(req["trip_id"], pool)

    angles, recommended_index, reason, cost_usd = await generate_angles(
        content_seed=atom["text"], goal=goal, channel=req["channel"],
        brand_audience=brand_audience, destination=destination, trip_name=trip_name,
        search_demand=search_demand,
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
            # AA-494 prerequisite fix — the other 2 options were never unset, so a future
            # design that allows re-choosing a different angle after 'approved' would have T9
            # silently read the wrong option (first chosen=true row by idx, not the latest
            # choice). Harmless today only because the status guard above blocks calling this
            # twice — explicit unset here removes that landmine ahead of any status redesign.
            await conn.execute(
                "UPDATE acp_shared.angle_gate_option SET chosen = false "
                "WHERE request_id = $1 AND idx != $2",
                request_id, idx,
            )
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
        "cta": req["cta"],
        "status": req["status"],
        "created_at": req["created_at"].isoformat(),
        "updated_at": req["updated_at"].isoformat(),
        "angles": [dict(o) for o in option_rows],
    }


__all__ = [
    "AngleGateError", "AtomNotFoundError", "RequestNotFoundError", "InvalidGoalError",
    "WrongStatusError", "create_request", "set_goal_and_generate", "choose_angle", "fetch_request",
]
