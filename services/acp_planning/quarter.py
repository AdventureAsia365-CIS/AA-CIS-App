"""
services.acp_planning.quarter — N5 Quarter Plan (1x/quarter).

Ported from aamc/planning.py's plan_quarter()/D3 (aa-marketing-v2 research
build). Scores tours -> chooses quarter focus + big rocks. Pure Python,
$0 LLM.

Fixes applied during the port (see docs/implementation-notes/AA-301.md):
  B4 — special-tour matching used substring containment (`s in name.lower()`),
       which both false-negatived ("sapa trekking" not in "sapa valley trek")
       and false-positived on partial word matches. Replaced with token
       overlap + prefix fuzzy match (_fuzzy_match).
  B5 — THIN_TRIP_ATOM_MIN existed in config but no code anywhere capped a
       thin trip's content share. _cap_thin_trip_shares() now caps and
       redistributes the freed share proportionally to non-thin trips.

Gate B (Ms. Thu must approve the quarter plan, REQUIRED, NEVER auto) is
QuarterPlan.approved — allocate_month() (N6) refuses to run against an
unapproved plan (QuarterPlanNotApprovedError). No acp_shared.acp_hitl_requests
row is created for this — that table is FK'd to acp_shared.acp_runs(run_id),
an ACP-B2B "pipeline run" concept N4-N6 don't have (they're periodic
per-tenant computations, not runs); reusing it would mean inventing a fake
run_id. Self-chosen decision, see AA-301 implementation notes.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional
from uuid import UUID

from services.acp_shared.atom_constants import THIN_TRIP_ATOM_MIN

from .constants import THIN_TRIP_MAX_SHARE
from .models import AtomRecord, BigRock, QuarterPlan, RunwayMap, Trip, compute_trips_hash

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TOKEN_MIN_PREFIX = 4
_FUZZY_MATCH_THRESHOLD = 0.5


def _tokens(s: str) -> set[str]:
    return set(_TOKEN_RE.findall(s.lower()))


def _tokens_fuzzy_equal(a: str, b: str, min_prefix: int = _TOKEN_MIN_PREFIX) -> bool:
    if a == b:
        return True
    if len(a) >= min_prefix and len(b) >= min_prefix:
        return a[:min_prefix] == b[:min_prefix]
    return False


def _fuzzy_match(special: str, trip_name: str, trip_destination: Optional[str],
                  threshold: float = _FUZZY_MATCH_THRESHOLD) -> bool:
    """B4 fix — token overlap + prefix fuzzy match instead of substring
    containment. 'sapa trekking' now matches 'Sapa Valley Trek' (token
    'trek'/'trekking' share a 4-char prefix) at >=50% of the special's own
    tokens matched, instead of silently dropping the special (previous bug:
    'sapa trekking' in 'sapa valley trek'.lower() -> False)."""
    special_tokens = _tokens(special)
    if not special_tokens:
        return False
    candidate_tokens = _tokens(trip_name) | _tokens(trip_destination or "")
    matched = sum(
        1 for st in special_tokens
        if any(_tokens_fuzzy_equal(st, ct) for ct in candidate_tokens)
    )
    return (matched / len(special_tokens)) >= threshold


def _cap_thin_trip_shares(
    shares: dict[str, float], atom_counts: dict[str, int],
) -> tuple[dict[str, float], list[str]]:
    """B5 fix — a destination whose live atom count is below
    THIN_TRIP_ATOM_MIN has its content share capped at THIN_TRIP_MAX_SHARE.
    Freed share is redistributed proportionally across non-thin
    destinations so shares still sum to ~1.0 (redistribution behavior is
    not specified by the issue — self-chosen, see AA-301 implementation
    notes)."""
    notes: list[str] = []
    thin: dict[str, float] = {}
    normal: dict[str, float] = {}
    for dest, share in shares.items():
        if atom_counts.get(dest, 0) < THIN_TRIP_ATOM_MIN:
            thin[dest] = share
        else:
            normal[dest] = share

    capped: dict[str, float] = {}
    freed = 0.0
    for dest, share in thin.items():
        new_share = min(share, THIN_TRIP_MAX_SHARE)
        if new_share < share:
            notes.append(
                f"'{dest}' is thin ({atom_counts.get(dest, 0)} atoms < {THIN_TRIP_ATOM_MIN}) "
                f"— share capped {share:.2f} -> {new_share:.2f}")
            freed += share - new_share
        capped[dest] = new_share

    normal_total = sum(normal.values()) or 1.0
    for dest, share in normal.items():
        capped[dest] = share + freed * (share / normal_total)

    return capped, notes


def compute_quarter_plan(
    tenant_id: UUID, year: int, quarter: int, trips: list[Trip], markets: list[str],
    capacity_posts_per_week: int, specials: list[str], runway: RunwayMap,
    atoms_by_trip: dict[UUID, list[AtomRecord]],
) -> QuarterPlan:
    """Pure computation — no DB, no LLM, 100% unit-testable."""
    q_months = [(quarter - 1) * 3 + i for i in (1, 2, 3)]

    ranked: list[tuple[float, Trip, bool]] = []
    for t in trips:
        if t.lifecycle_stage == "retired":
            continue
        atoms = atoms_by_trip.get(t.id, [])
        dest = t.destination or t.name
        runway_fit = sum(
            1 for m in q_months for mk in markets if runway.stage(dest, mk, m) in ("BOFU", "MOFU")
        ) / (len(q_months) * len(markets) or 1)
        richness = min(len(atoms) / 10, 1.0)
        dist = sum({"HIGH": 1.0, "MED": 0.5, "LOW": 0.1}[a.distinctiveness] for a in atoms) / (len(atoms) or 1)
        forced = any(_fuzzy_match(s, t.name, t.destination) for s in specials)
        score = runway_fit * 0.4 + richness * 0.3 + dist * 0.3 + (1.0 if forced else 0.0)
        ranked.append((score, t, forced))
    ranked.sort(key=lambda x: -x[0])

    max_trips = max(2, min(len(ranked), capacity_posts_per_week + 1))
    chosen = ranked[:max_trips]
    capacity_note = None
    if len(ranked) > max_trips:
        capacity_note = (
            f"{len(ranked)} eligible trips at {capacity_posts_per_week} posts/wk — "
            f"focusing on {max_trips} trips (applied).")

    plan = QuarterPlan(
        tenant_id=tenant_id, year=year, quarter=quarter,
        trip_ids=[t.id for _, t, _ in chosen],
        forced_specials=[t.id for _, t, forced in chosen if forced],
        capacity_note=capacity_note,
        trips_hash=compute_trips_hash(trips),
    )

    total_score = sum(s for s, _, _ in chosen) or 1
    raw_shares: dict[str, float] = {}
    dest_atom_counts: dict[str, int] = {}
    for s, t, _ in chosen:
        dest = t.destination or t.name
        raw_shares[dest] = raw_shares.get(dest, 0.0) + s / total_score
        dest_atom_counts[dest] = dest_atom_counts.get(dest, 0) + len(atoms_by_trip.get(t.id, []))

    capped_shares, thin_notes = _cap_thin_trip_shares(raw_shares, dest_atom_counts)
    plan.destination_shares = {k: round(v, 2) for k, v in capped_shares.items()}
    plan.thin_trip_notes = thin_notes

    for _, t, _ in chosen[:3]:
        highs = [a for a in atoms_by_trip.get(t.id, []) if a.distinctiveness == "HIGH" and not a.usage_log]
        if len(highs) >= 2:
            plan.big_rocks.append(BigRock(
                rock_id=f"rock_{uuid.uuid4().hex[:10]}", trip_id=t.id,
                title=f"{t.name}: definitive guide",
                atom_ids=[a.atom_id for a in highs[:6]],
                atomization_contract={"social": 4, "email": 1, "lead_magnet": 1}))

    return plan


_ATOM_ROW_QUERY = """
    SELECT ta.atom_id, ta.tour_id, ta.text, ta.distinctiveness, ta.starred,
           ta.deleted, ta.weight, ta.cooldown_until, ta.usage_log
    FROM acp_contract.tour_atoms ta
    JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = ta.tour_id
    WHERE rt.tenant_id = $1 AND NOT ta.deleted AND NOT ta.is_empty_marker
"""


def _row_to_atom(row) -> AtomRecord:
    return AtomRecord(
        atom_id=row["atom_id"], trip_id=row["tour_id"], text=row["text"],
        distinctiveness=row["distinctiveness"] or "LOW", starred=row["starred"],
        deleted=row["deleted"], weight=float(row["weight"]),
        cooldown_until=row["cooldown_until"] or {}, usage_log=row["usage_log"] or [],
    )


async def fetch_atoms_by_trip(tenant_id: UUID, pool) -> dict[UUID, list[AtomRecord]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(_ATOM_ROW_QUERY, tenant_id)
    by_trip: dict[UUID, list[AtomRecord]] = {}
    for r in rows:
        atom = _row_to_atom(r)
        by_trip.setdefault(atom.trip_id, []).append(atom)
    return by_trip


async def plan_quarter(
    tenant_id: UUID, year: int, quarter: int, markets: list[str],
    capacity_posts_per_week: int, specials: list[str], runway: RunwayMap, pool,
) -> QuarterPlan:
    """Async DB-wiring wrapper. `markets`/`capacity_posts_per_week`/`specials`
    are caller-supplied — no tenant campaign-config table exists in this
    schema yet (same gap noted in runway.py's runway_map())."""
    from .runway import fetch_trips
    trips = await fetch_trips(tenant_id, pool)
    atoms_by_trip = await fetch_atoms_by_trip(tenant_id, pool)
    return compute_quarter_plan(
        tenant_id, year, quarter, trips, markets, capacity_posts_per_week,
        specials, runway, atoms_by_trip,
    )


def approve_quarter_plan(plan: QuarterPlan, approved_by: str) -> QuarterPlan:
    """Gate B — the only way a QuarterPlan may become allocatable. Never
    called automatically anywhere in this module."""
    plan.approved = True
    plan.approved_by = approved_by
    return plan


__all__ = [
    "compute_quarter_plan", "fetch_atoms_by_trip", "plan_quarter",
    "approve_quarter_plan",
]
