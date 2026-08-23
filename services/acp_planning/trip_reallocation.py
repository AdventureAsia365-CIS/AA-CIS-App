"""
services.acp_planning.trip_reallocation — AA-448 round 6: feedback-informed trip-reallocation
suggestion for the NEXT quarter.

NOT part of aa-marketing-v2's design — Module H's `rollup_atoms()` (the reference's real
feedback loop) only ever adjusted `tour_atoms.weight` and fed that into future MONTH allocation
(N6). It never re-touched `QuarterPlan`/trip selection at all. This module is Nghiep's own
explicit extension (round 6): once real feedback has adjusted atom weights
(`services/acp_shared/content_metrics.py::rollup_atom_weights()`), those adjusted weights now
also flow into `compute_quarter_plan()`'s 5th scoring term (`engagement_adjustment`,
quarter.py) — this module surfaces that as an actionable, tenant-reviewed suggestion for the
NEXT quarter, rather than silently re-planning anything.

Shape mirrors `services/acp_produce/trust_ramp.py::suggest_ramp_transition()`/
`confirm_ramp_transition()` exactly (Nghiep's own suggested naming/pattern): `suggest_...()` is
pure-ish — computes, diffs, never writes; `confirm_...()` ALWAYS writes an
`acp_shared.audit_log` entry (same table trust_ramp.py already reuses, no new logging shape),
whether the tenant accepts or rejects, and on accept applies the change through the SAME
Gate-B-Option-A finalize path T7's own `POST /v1/planning/quarter-plan` uses — an accepted
reallocation becomes a normal new quarter_plan_version, not a special kind of object.
"""
from __future__ import annotations

import json
from uuid import UUID

from services.acp_shared.dfs_relevance import fetch_dfs_relevance_by_tour

from .models import QuarterPlan
from .quarter import (approve_quarter_plan_version, compute_quarter_plan,
                      fetch_approved_quarter_plan, save_quarter_plan_version)
from .runway import compute_runway_map
from .tenant_config import fetch_tenant_planning_config
from .tenant_pool import fetch_tenant_atoms_by_trip, fetch_tenant_trips


async def suggest_trip_reallocation(tenant_id: UUID, year: int, quarter: int, pool) -> dict:
    """Never writes. Computes a fresh QuarterPlan for (year, quarter) using the tenant's
    CURRENT, feedback-adjusted atom weights (whatever rollup_atom_weights() last wrote to
    tour_atoms.weight — this function does not trigger a rollup itself, it only consumes
    whatever weights already exist), and diffs its trip_ids against the tenant's existing
    finalized plan for that quarter, if any."""
    config = await fetch_tenant_planning_config(tenant_id, pool)
    trips = await fetch_tenant_trips(tenant_id, pool)
    atoms_by_trip = await fetch_tenant_atoms_by_trip(tenant_id, pool)
    runway = compute_runway_map(tenant_id, year, trips, config.markets)
    dfs_relevance_by_trip = await fetch_dfs_relevance_by_tour([t.id for t in trips], pool)

    fresh_plan = compute_quarter_plan(
        tenant_id, year, quarter, trips, config.markets, config.capacity_posts_per_week,
        specials=[], runway=runway, atoms_by_trip=atoms_by_trip,
        dfs_relevance_by_trip=dfs_relevance_by_trip,
    )

    existing_plan = await fetch_approved_quarter_plan(tenant_id, year, quarter, pool)
    existing_ids = set(existing_plan.trip_ids) if existing_plan else set()
    fresh_ids = set(fresh_plan.trip_ids)

    return {
        "plan": fresh_plan.model_dump(mode="json"),
        "has_existing_plan": existing_plan is not None,
        "added": sorted(str(i) for i in (fresh_ids - existing_ids)),
        "removed": sorted(str(i) for i in (existing_ids - fresh_ids)),
        "unchanged": sorted(str(i) for i in (fresh_ids & existing_ids)),
    }


async def confirm_trip_reallocation(
    pool, tenant_id: UUID, year: int, quarter: int, accept: bool, actor: str,
) -> dict:
    """ALWAYS writes an acp_shared.audit_log entry first (mirrors
    trust_ramp.py::confirm_ramp_transition()'s "never silently" framing — a REJECTED suggestion
    is exactly the kind of event this log exists to surface, not something to drop). Re-runs
    suggest_trip_reallocation() itself (not passed a cached suggestion) so what gets applied on
    accept is never stale relative to what the tenant most recently saw — a deliberate
    simplicity choice over passing a large plan payload through the confirm request; this is a
    low-frequency (quarterly) action, the extra DB round-trip is not a real cost here."""
    suggestion = await suggest_trip_reallocation(tenant_id, year, quarter, pool)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO acp_shared.audit_log
                (tenant_id, actor, action, resource_type, resource_id, details)
            VALUES ($1, $2, 'trip_reallocation_suggestion', 'quarter_plan', $3, $4::jsonb)
            """,
            str(tenant_id), actor, f"{year}-Q{quarter}",
            json.dumps({
                "accepted": accept, "added": suggestion["added"], "removed": suggestion["removed"],
            }),
        )

    if not accept:
        return {"accepted": False, "suggestion": suggestion}

    plan = QuarterPlan(**suggestion["plan"])
    # AA-448 live-verify finding: acp_shared.quarter_plan_version.source has a CHECK constraint
    # allowing only 'standard'/'override' (migration 092) — "override" is the correct existing
    # value here (a tenant overriding their previous plan based on a feedback suggestion),
    # not a new value this task should invent a migration for.
    version_id = await save_quarter_plan_version(plan, pool, source="override")
    await approve_quarter_plan_version(version_id, f"tenant:{tenant_id}", pool)
    return {"accepted": True, "version_id": str(version_id), "suggestion": suggestion}


__all__ = ["suggest_trip_reallocation", "confirm_trip_reallocation"]
