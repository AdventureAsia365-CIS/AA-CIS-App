"""
api/routers/admin_dashboard.py — AA-527 (bổ sung, 05/09/2026) — the 4 audit-view panels of the
T5-T11 dashboard (Phương án C) that had no admin read-path at all before this: Segment, Score,
Route/Hub, Slate. The other 3 non-Atomize panels (Write-Gate, Review, Publish) reuse the
EXISTING `admin_a4.py` `content-log`/`publish-log` endpoints (extended with an optional
`tour_id` filter, same PR) rather than duplicating a query here — see that file's own docstrings.

All 4 endpoints below are read-only, x-admin-secret only (same `verify_admin_secret` convention
as `admin_atoms.py`/`admin_a4.py` — this dashboard is admin-only, per Nghiệp's explicit choice
already recorded on the Atomize section, AA-527's first build), and REQUIRE `tour_id` — the
dashboard's header anchor. There is deliberately no "all tours" mode for these 4: Segment/Score
are Tour-scoped by schema already (acp_contract.atom_ranking.tour_id), and Route/Slate are cheap
to scope down to one tour but expensive/meaningless to page across every tenant's every tour at
once for a first cut (no existing precedent list-endpoint to mirror, unlike content-log/
publish-log which already supported an optional cross-tenant listing before this task).

Cross-tenant by design (same stance as admin_a4.py, STEP0/AA-437): a Tour's Segment/Score/Route/
Slate data can in principle exist under more than one tenant (multiple tenants can each run T7
over the same platform-shared atoms for the same tour) — every endpoint here returns EVERY
tenant's rows for the given tour_id, with tenant_name attached, not scoped to one tenant.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Query, Request

from api.routers.admin import verify_admin_secret

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])


def _safe(row) -> dict:
    """Same local-safe()-per-router convention as admin_atoms.py/v1_tours.py (no shared
    api/utils.safe() exists in this repo) — UUID/Decimal/datetime -> JSON-safe, plus JSONB
    columns that come back as a raw string (no jsonb codec registered on this app's asyncpg
    connections, same gap AA-314/admin_atoms.py already found for `media`)."""
    import json
    from decimal import Decimal
    from uuid import UUID

    if not row:
        return {}
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, UUID):
            d[k] = str(v)
        elif isinstance(v, Decimal):
            d[k] = float(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, str) and k in ("ordered_segment_ids", "cleared_bar_reason"):
            try:
                d[k] = json.loads(v)
            except (TypeError, ValueError):
                pass
    return d


# ── GET /admin/dashboard/segments — Section 02, audit view ─────────────────

@router.get("/segments")
async def list_segments(
    request: Request,
    tour_id: str = Query(...),
    x_admin_secret: str = Header(None),
):
    """acp_contract.atom_segment for this tour — a Segment has no tour_id column of its own
    (it's grouped by place/action across a tenant's whole atom pool, AA-509), so this reaches it
    through atom_segment_member -> tour_atoms.tour_id, one row per Segment that has >=1 member
    atom on this tour. total_rank/recurrence/route linkage joined in (same LATERAL Route lookup
    admin_atoms.py's GET /atoms already uses) so this one panel shows Segment + its Score + its
    Route membership together, rather than 3 separate near-empty tables."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT asg.segment_id, asg.canonical_place, asg.canonical_action, asg.tenant_id,
                   t.name AS tenant_name,
                   count(DISTINCT asm.atom_id) AS member_count,
                   ar.total_rank, ar.recurrence, ar.excluded_reason,
                   rte.route_id, rte.hub_name AS route_hub_name
            FROM acp_contract.atom_segment_member asm
            JOIN acp_contract.tour_atoms ta ON ta.atom_id = asm.atom_id
            JOIN acp_contract.atom_segment asg ON asg.segment_id = asm.segment_id
            LEFT JOIN shared.tenants t ON t.tenant_id = asg.tenant_id
            LEFT JOIN acp_contract.atom_ranking ar
                ON ar.segment_id = asm.segment_id AND ar.tour_id = ta.tour_id
            LEFT JOIN LATERAL (
                SELECT r.route_id, r.hub_name
                FROM acp_contract.route r
                -- AA-532: current version only, same reasoning as admin_atoms.py's identical
                -- LATERAL join — a superseded route (never deleted) must not read as "part of
                -- Route X" once re-detection has moved this Segment on.
                WHERE r.tour_id = ta.tour_id AND r.superseded_at IS NULL
                  AND r.ordered_segment_ids @> jsonb_build_array(asm.segment_id)
                LIMIT 1
            ) rte ON true
            WHERE ta.tour_id = $1::uuid AND NOT ta.deleted AND NOT ta.is_empty_marker
            GROUP BY asg.segment_id, asg.canonical_place, asg.canonical_action, asg.tenant_id,
                     t.name, ar.total_rank, ar.recurrence, ar.excluded_reason,
                     rte.route_id, rte.hub_name
            ORDER BY ar.total_rank ASC NULLS LAST, asg.canonical_place
            """,
            tour_id,
        )

    return {"data": [_safe(r) for r in rows], "total": len(rows), "tour_id": tour_id}


# ── GET /admin/dashboard/score — Section 03, audit view ─────────────────────

@router.get("/score")
async def list_score(
    request: Request,
    tour_id: str = Query(...),
    x_admin_secret: str = Header(None),
):
    """acp_contract.atom_ranking rows for this tour, in rank order (lower total_rank = better,
    same convention as the Route.score docstring, migration 130) — the ranked list feeding Route
    detection, distinct from the Segment panel above (which shows grouping, not the demand/
    recurrence/questions/said breakdown a rank is actually made of). A row with excluded_reason
    set (transit/unnamed_place) is real output too (AA-515: "an exclusion is arguable rather than
    a silent absence"), sorted after every ranked row rather than hidden."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ar.tenant_id, t.name AS tenant_name, ar.segment_id,
                   asg.canonical_place, asg.canonical_action,
                   ar.demand_rank, ar.recurrence_rank, ar.questions_rank, ar.said_rank,
                   ar.total_rank, ar.demand_market, ar.demand_volume,
                   ar.recurrence, ar.questions, ar.said, ar.excluded_reason, ar.computed_at
            FROM acp_contract.atom_ranking ar
            LEFT JOIN shared.tenants t ON t.tenant_id = ar.tenant_id
            LEFT JOIN acp_contract.atom_segment asg ON asg.segment_id = ar.segment_id
            WHERE ar.tour_id = $1::uuid
            ORDER BY (ar.excluded_reason IS NOT NULL), ar.total_rank ASC NULLS LAST
            """,
            tour_id,
        )

    return {"data": [_safe(r) for r in rows], "total": len(rows), "tour_id": tour_id}


# ── GET /admin/dashboard/routes — Section 04, audit view ────────────────────

@router.get("/routes")
async def list_routes(
    request: Request,
    tour_id: str = Query(...),
    x_admin_secret: str = Header(None),
):
    """acp_contract.route rows for this tour (has its own tour_id column directly, migration
    131 — no join-through needed, unlike Segment above). `hub_grouping_backlog` is always true
    here — AA-525 Phần 12 mục 8 confirmed there is no admin view yet of "which Routes got grouped
    into the same Hub and why" (acp_contract.hub itself has 0 rows in current live data — Route
    detection isn't wiring hub_id yet); flagged explicitly rather than silently showing an
    always-empty Hub column.

    AA-532: deliberately does NOT filter `superseded_at IS NULL` the way every other reader of
    this table now does (v1_route_hub.py, slate.py, admin_atoms.py) — this IS the audit view, the
    one place seeing a Route's version history (current AND superseded) is the actual point, not
    a bug. `version`/`superseded_at` are exposed so the panel can show that history rather than
    just the current snapshot; current rows sort first (`superseded_at IS NULL` ordered before
    any timestamp), then best score."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.route_id, r.tenant_id, t.name AS tenant_name, r.hub_id, r.hub_name,
                   r.ordered_segment_ids, r.first_day, r.last_day, r.score, r.created_at,
                   r.version, r.superseded_at
            FROM acp_contract.route r
            LEFT JOIN shared.tenants t ON t.tenant_id = r.tenant_id
            WHERE r.tour_id = $1::uuid
            ORDER BY (r.superseded_at IS NOT NULL), r.score ASC
            """,
            tour_id,
        )

    return {
        "data": [_safe(r) for r in rows], "total": len(rows), "tour_id": tour_id,
        "hub_grouping_backlog": True,
    }


# ── GET /admin/dashboard/slate — Section 05, audit view ──────────────────────

@router.get("/slate")
async def list_slate(
    request: Request,
    tour_id: str = Query(...),
    x_admin_secret: str = Header(None),
):
    """acp_shared.subject (the Slate proposal, AA-511) for this tour. subject has no tour_id of
    its own either (it's keyed to a Segment-or-Route, migration 133's own CHECK constraint) — so
    this reaches it through whichever of the two the Subject actually carries: `route_id` joins
    straight to acp_contract.route.tour_id, `segment_id` joins through atom_segment_member the
    same way the Segment panel above does. A Subject matches this tour if EITHER path resolves to
    it (never both — the CHECK constraint above guarantees segment_id/route_id are mutually
    exclusive on one row)."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.subject_id, s.tenant_id, t.name AS tenant_name, s.channel, s.state,
                   s.score, s.segment_id, s.route_id, s.cleared_bar_reason, s.created_at
            FROM acp_shared.subject s
            LEFT JOIN shared.tenants t ON t.tenant_id = s.tenant_id
            WHERE
                s.route_id IN (SELECT route_id FROM acp_contract.route WHERE tour_id = $1::uuid)
                OR s.segment_id IN (
                    SELECT DISTINCT asm.segment_id
                    FROM acp_contract.atom_segment_member asm
                    JOIN acp_contract.tour_atoms ta ON ta.atom_id = asm.atom_id
                    WHERE ta.tour_id = $1::uuid AND NOT ta.deleted AND NOT ta.is_empty_marker
                )
            ORDER BY s.created_at DESC
            """,
            tour_id,
        )

    by_state = {"proposed": 0, "picked": 0, "used": 0, "cut": 0}
    for r in rows:
        if r["state"] in by_state:
            by_state[r["state"]] += 1

    return {
        "data": [_safe(r) for r in rows], "total": len(rows), "tour_id": tour_id,
        "by_state": by_state,
    }
