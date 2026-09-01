"""services/acp_contract/route_detection.py — AA-510, Route/Hub detection + route_pick snapshot.

(`create_subject()`/`acp_contract.subject` renamed to `create_route_pick()`/
`acp_contract.route_pick` at AA-511 STEP0, migration 132 — freed the name `subject` for the
unrelated Slate-proposal concept `acp_shared.subject`.)

Ported from Ms. Thư's aa-social-media `src/aa_social/routes.py` (`derive_routes()`/`families()`/
`stops()`) and `stages/score.py`'s `_store_routes()` (rebuild-whole persistence). Full evidence
and every deviation from the origin/build prompt, disclosed not silent: docs/claude_audit/
AA-510-step0-route-hub-investigation.md, docs/implementation-notes/AA-510.md.

**A Route is one tour's ordered run of ranked, non-excluded Segments** — Magome, then the pass,
then Tsumago. Built from whatever `atom_ranking` (AA-515) last ranked, so ADR 0019/0020's
transit/unnamed-place exclusion is inherited, not re-applied here. A run breaks where a day has
nothing ranked on it (usually the transfer); a run of <2 days or <2 places is not a journey —
that stays a Segment.

**A Hub is the journey a family of Routes tells** — six Nakasendo itineraries are six sales of
one Hub, not six unrelated Routes. Family membership is measured in shared ranked Segments
(Jaccard over the SMALLER tour's set, >= SHARED_ENOUGH) because two tours sharing a region
without sharing a week are not one journey.

Grain is the Segment (AA-515's own grain), not the Atom (the origin's grain) — implementation
notes Decision 4.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

# A journey is at least 2 days and 2 places -- one day is a moment, two days in one place is a
# stay, both already a Segment's job (ported verbatim, routes.py:36-37).
LEAST_DAYS = 2
LEAST_PLACES = 2

# At most 5 -- a run of ranked days is often most of the itinerary; a Blog piece cannot walk 13
# days and a reader would not follow it. Longer runs are cut into consecutive spans, in day
# order, never reduced to the strongest few days (ported verbatim, routes.py:39-45).
MOST_DAYS = 5

# How much of the smaller tour's ranked Segment set two tours must share before they are one
# journey -- measured on Ms. Thư's own Japan export at 0.3 (routes.py:47-53). AA-CIS has no
# equivalent catalog to re-measure against yet; kept as the starting point, a named constant so
# it is never inlined (build prompt: "config, không hardcode"). Reused for BOTH family-forming
# (route-to-route grouping by tour) and Hub-reuse matching (implementation notes Decision 6) --
# one threshold, not two unvalidated magic numbers.
SHARED_ENOUGH = 0.3


@dataclass(frozen=True)
class Moment:
    """One ranked, non-excluded Segment, as a Route needs to see it — for ONE tour."""

    segment_id: str
    tour_id: str
    day: int
    place: str
    score: int  # atom_ranking.total_rank -- lower is better (rank-sum, AA-515)


@dataclass(frozen=True)
class Route:
    """Consecutive days of one tour, and the ranked Segments along them."""

    route_id: str
    tenant_id: str
    tour_id: str
    first_day: int
    last_day: int
    segment_ids: tuple[str, ...]
    places: tuple[str, ...]
    score: int
    hub_name: str = ""
    hub_id: str | None = None

    @property
    def days(self) -> int:
        return self.last_day - self.first_day + 1


def derive_routes(tenant_id: str, moments: Iterable[Moment]) -> list[Route]:
    """Every journey in one tenant's ranked inventory. Same moments in, same Routes out.

    Score is the mean of the member moments' total_rank, rounded — a strong run is not
    outranked by a longer weaker one, a weak tail is not hidden by a strong opening. Sorted
    ascending (lowest/best total_rank first), matching the rank-sum convention (AA-515:
    "lowest total wins"). `hub_id`/`hub_name` are resolved separately, after family detection
    — every Route here starts with `hub_name=""`.
    """
    by_tour: dict[str, list[Moment]] = {}
    for moment in moments:
        by_tour.setdefault(moment.tour_id, []).append(moment)

    routes: list[Route] = []
    for tour_id, held in sorted(by_tour.items()):
        for run in _spans(_runs(sorted(held, key=lambda m: (m.day, m.segment_id)))):
            places = tuple(dict.fromkeys(moment.place for moment in run))
            days = {moment.day for moment in run}
            if len(days) < LEAST_DAYS or len(places) < LEAST_PLACES:
                continue
            first, last = min(days), max(days)
            routes.append(Route(
                route_id=f"{tenant_id}:{tour_id}:{first}-{last}",
                tenant_id=tenant_id,
                tour_id=tour_id,
                first_day=first,
                last_day=last,
                segment_ids=tuple(m.segment_id for m in run),
                places=places,
                score=round(sum(m.score for m in run) / len(run)),
            ))
    return sorted(routes, key=lambda route: (route.score, route.route_id))


def _runs(held: list[Moment]) -> list[list[Moment]]:
    """Moments split into consecutive-day runs. A gap is a day ranking left empty — almost
    always the transfer (ported verbatim, routes.py:119-130)."""
    runs: list[list[Moment]] = []
    for moment in held:
        if runs and moment.day - runs[-1][-1].day <= 1:
            runs[-1].append(moment)
        else:
            runs.append([moment])
    return runs


def _spans(runs: list[list[Moment]]) -> list[list[Moment]]:
    """Runs cut to a length a piece can walk. A trailing short span joins the one before it
    rather than being dropped (ported verbatim, routes.py:133-150)."""
    spans: list[list[Moment]] = []
    for run in runs:
        days = sorted({moment.day for moment in run})
        cuts = [days[at:at + MOST_DAYS] for at in range(0, len(days), MOST_DAYS)]
        if len(cuts) > 1 and len(cuts[-1]) < LEAST_DAYS:
            cuts[-2] = cuts[-2] + cuts[-1]
            cuts.pop()
        for cut in cuts:
            within = set(cut)
            spans.append([moment for moment in run if moment.day in within])
    return spans


def families(tours: Mapping[str, set[str]], share: float = SHARED_ENOUGH) -> dict[str, str]:
    """Which tours sell one journey, as tour_id -> family key (the alphabetically-smallest
    member's tour_id). A tour sharing nothing with any other is not in the map — a family of
    one is not a family (ported verbatim algorithm, routes.py:153-190, `trip_code` -> `tour_id`).
    """
    parent = {tour: tour for tour in tours}

    def find(tour: str) -> str:
        while parent[tour] != tour:
            parent[tour] = parent[parent[tour]]
            tour = parent[tour]
        return tour

    ordered = sorted(tours)
    for index, one in enumerate(ordered):
        for other in ordered[index + 1:]:
            smaller = min(len(tours[one]), len(tours[other]))
            if not smaller:
                continue
            if len(tours[one] & tours[other]) / smaller >= share:
                left, right = find(one), find(other)
                if left != right:
                    parent[max(left, right)] = min(left, right)

    grouped: dict[str, list[str]] = {}
    for tour in ordered:
        grouped.setdefault(find(tour), []).append(tour)
    return {
        tour: min(members)
        for members in grouped.values()
        if len(members) > 1
        for tour in members
    }


@dataclass(frozen=True)
class Stop:
    """One place on one day, and everything that happens there — presentation only, used to
    make a Subject snapshot human-readable without a live join (ported verbatim, routes.py:
    193-227)."""

    day: int
    place: str
    actions: tuple[str, ...] = ()

    @property
    def said(self) -> str:
        doing = [one for one in self.actions if one]
        if not doing:
            return ""
        if len(doing) == 1:
            return doing[0]
        return ", ".join(doing[:-1]) + " and " + doing[-1]

    def __str__(self) -> str:
        said = self.said
        return f"day {self.day} {self.place}" + (f" — {said}" if said else "")


def stops(steps: Iterable[tuple[int, str, str]]) -> list[Stop]:
    """A journey as it is shown. Order is the order given. A place named twice on one day is
    one Stop with 2 actions; a place revisited on a later day is a second Stop (ported verbatim,
    routes.py:230-248)."""
    held: dict[tuple[int, str], list[str]] = {}
    order: list[tuple[int, str]] = []
    for day, place, action in steps:
        key = (day, place)
        if key not in held:
            held[key] = []
            order.append(key)
        if action and action not in held[key]:
            held[key].append(action)
    return [Stop(day=d, place=p, actions=tuple(held[(d, p)])) for d, p in order]


def journey_name(places: Sequence[str], limit: int = 4) -> str:
    """A readable placeholder Hub/Route name from a day-ordered place sequence —
    "Kyoto → Magome → Tsumago". NOT marketer-authored copy (no naming/rename UI exists yet,
    implementation notes Decision 9) — a disclosed placeholder for CONTEXT.md's "named as a
    traveller would say it", capped at `limit` places so a long itinerary doesn't produce an
    unreadable name.
    """
    trimmed = list(dict.fromkeys(places))[:limit]
    return " → ".join(trimmed) if trimmed else "Untitled journey"


# ── DB-facing wrappers (impure) ─────────────────────────────────────────────────────────────

async def run_route_detection(tenant_id: str, pool) -> dict:
    """Rebuild acp_contract.route WHOLE for one tenant (DELETE+INSERT) — matches the
    STEP0-confirmed origin behavior (`_store_routes()`, "derived, never accumulated"; see
    implementation notes Decision 10 for why acp_contract.hub is explicitly NOT rebuilt the
    same way — it persists and is matched/reused, never deleted).

    Reads only non-excluded (`excluded_reason IS NULL`) atom_ranking rows — the transit/
    unnamed-place gate (ADR 0019/0020) already ran one layer down (AA-515) and is not
    re-applied here.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT ar.segment_id, ar.tour_id::text AS tour_id, ar.total_rank,
                   asg.canonical_place, asg.canonical_action,
                   MIN(ta.itinerary_day) AS day
            FROM acp_contract.atom_ranking ar
            JOIN acp_contract.atom_segment asg ON asg.segment_id = ar.segment_id
            JOIN acp_contract.atom_segment_member asm ON asm.segment_id = ar.segment_id
            JOIN acp_contract.tour_atoms ta
                ON ta.atom_id = asm.atom_id AND ta.tour_id = ar.tour_id
            WHERE ar.tenant_id = $1::uuid AND ar.excluded_reason IS NULL
              AND ta.itinerary_day IS NOT NULL AND NOT ta.deleted AND NOT ta.is_empty_marker
            GROUP BY ar.segment_id, ar.tour_id, ar.total_rank, asg.canonical_place,
                     asg.canonical_action
        """, tenant_id)

        old_hubs = await conn.fetch("""
            SELECT h.hub_id, h.hub_name, array_agg(DISTINCT r.tour_id::text) AS tour_ids
            FROM acp_contract.hub h
            JOIN acp_contract.route r ON r.hub_id = h.hub_id
            WHERE h.tenant_id = $1::uuid
            GROUP BY h.hub_id, h.hub_name
        """, tenant_id)

    moments = [
        Moment(segment_id=r["segment_id"], tour_id=r["tour_id"], day=r["day"],
               place=r["canonical_place"], score=r["total_rank"])
        for r in rows
    ]
    tour_segments: dict[str, set[str]] = defaultdict(set)
    tour_steps: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for r in rows:
        tour_segments[r["tour_id"]].add(r["segment_id"])
        tour_steps[r["tour_id"]].append((r["day"], r["canonical_place"], r["canonical_action"]))

    routes = derive_routes(tenant_id, moments)
    family_of = families(dict(tour_segments), SHARED_ENOUGH)

    routes_by_tour: dict[str, list[Route]] = defaultdict(list)
    for r in routes:
        routes_by_tour[r.tour_id].append(r)

    grouped: dict[str, set[str]] = defaultdict(set)
    for tour_id, key in family_of.items():
        grouped[key].add(tour_id)
    # Only pursue Hub resolution for families that actually produced >=1 Route this run — a
    # family whose every member failed the LEAST_DAYS/LEAST_PLACES gate has nothing to attach
    # a Hub to; skipping it avoids minting an immediately-orphaned Hub row for no reason.
    grouped = {k: v for k, v in grouped.items() if any(t in routes_by_tour for t in v)}

    old_hub_tours = {str(r["hub_id"]): set(r["tour_ids"]) for r in old_hubs}
    old_hub_names = {str(r["hub_id"]): r["hub_name"] for r in old_hubs}

    resolved_hub: dict[str, tuple[str, str]] = {}  # family_key -> (hub_id, hub_name)
    hubs_created = 0
    hubs_reused = 0
    async with pool.acquire() as conn:
        for family_key, member_tours in grouped.items():
            # Primary signal: which real tours a hub covers — durable across a Segment-level
            # reshuffle, unlike segment_id sets. hub_name equality is checked as a tie-break
            # only when tour-set overlap alone doesn't clear the bar (implementation notes
            # Decision 7).
            best_hub_id, best_ratio = None, 0.0
            for hub_id, old_tours in old_hub_tours.items():
                smaller = min(len(member_tours), len(old_tours))
                if not smaller:
                    continue
                ratio = len(member_tours & old_tours) / smaller
                if ratio > best_ratio:
                    best_hub_id, best_ratio = hub_id, ratio

            candidates = routes_by_tour.get(family_key, [])
            if candidates:
                canonical_places = list(min(candidates, key=lambda r: r.score).places)
            else:
                canonical_places = [
                    p for _d, p, _a in sorted(tour_steps.get(family_key, []))
                ]
            name = journey_name(canonical_places)

            if best_hub_id is not None and best_ratio >= SHARED_ENOUGH:
                # hub_name is deliberately NOT overwritten on reuse (Decision 8) — a future
                # marketer rename must survive a rebuild that still regroups the same tours.
                resolved_hub[family_key] = (best_hub_id, old_hub_names[best_hub_id])
                await conn.execute(
                    "UPDATE acp_contract.hub SET updated_at = now() WHERE hub_id = $1::uuid",
                    best_hub_id,
                )
                hubs_reused += 1
            else:
                new_hub_id = await conn.fetchval("""
                    INSERT INTO acp_contract.hub (tenant_id, hub_name)
                    VALUES ($1::uuid, $2) RETURNING hub_id
                """, tenant_id, name)
                resolved_hub[family_key] = (str(new_hub_id), name)
                hubs_created += 1

    finished: list[Route] = []
    for route in routes:
        family_key = family_of.get(route.tour_id)
        if family_key is not None and family_key in resolved_hub:
            hub_id, hub_name = resolved_hub[family_key]
            finished.append(replace(route, hub_id=hub_id, hub_name=hub_name))
        else:
            # Standalone tour — "a family of one is not a family" (origin's own rule): no Hub
            # row created or reused, hub_name is a per-route placeholder from its own places.
            finished.append(replace(
                route, hub_id=None, hub_name=journey_name(list(route.places)),
            ))

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM acp_contract.route WHERE tenant_id = $1::uuid", tenant_id,
            )
            if finished:
                await conn.executemany("""
                    INSERT INTO acp_contract.route
                        (route_id, tenant_id, tour_id, hub_id, hub_name, ordered_segment_ids,
                         first_day, last_day, score)
                    VALUES ($1, $2::uuid, $3::uuid, $4::uuid, $5, $6::jsonb, $7, $8, $9)
                """, [
                    (r.route_id, r.tenant_id, r.tour_id, r.hub_id, r.hub_name,
                     json.dumps(list(r.segment_ids)), r.first_day, r.last_day, r.score)
                    for r in finished
                ])

    return {
        "routes_written": len(finished),
        "hubs_created": hubs_created,
        "hubs_reused": hubs_reused,
        "families_found": len(grouped),
        "tours_ranked": len(tour_segments),
    }


async def create_route_pick(
    tenant_id: str, route_id: str, pool, selected_by: str | None = None,
) -> dict | None:
    """Snapshot one Route into a route_pick at the moment a marketer picks it (ADR 0024) — no
    live FK, ever, into route.route_id (the same lesson the origin's own Subject layer learned
    the hard way, docs/adr/0024-a-subject-outlives-the-segment-it-came-from.md, applied one
    layer up here).

    Named `create_subject()`/`acp_contract.subject` at AA-510; renamed here (AA-511 STEP0,
    migration 132) to free the name `subject` for the unrelated Slate-proposal concept
    `acp_shared.subject` this issue builds — the two are a different grain/purpose entirely, not
    a compatibility rename.

    Returns None if the Route no longer exists for this tenant (already rebuilt away) — the
    caller's job to surface as "pick again", not this function's. Re-joins the underlying
    Segments at snapshot time (best-effort — a partial/empty join degrades the snapshot's
    `stops` detail but never fails route_pick creation) so the snapshot is a human-readable,
    self-sufficient record that no longer depends on anything staying in place afterward.
    """
    async with pool.acquire() as conn:
        route = await conn.fetchrow("""
            SELECT route_id, tour_id, hub_id, hub_name, ordered_segment_ids,
                   first_day, last_day, score
            FROM acp_contract.route WHERE route_id = $1 AND tenant_id = $2::uuid
        """, route_id, tenant_id)
        if not route:
            return None

        segment_ids = route["ordered_segment_ids"]
        if isinstance(segment_ids, str):
            segment_ids = json.loads(segment_ids)

        step_rows = await conn.fetch("""
            SELECT asg.segment_id, asg.canonical_place, asg.canonical_action,
                   MIN(ta.itinerary_day) AS day
            FROM acp_contract.atom_segment asg
            JOIN acp_contract.atom_segment_member asm ON asm.segment_id = asg.segment_id
            JOIN acp_contract.tour_atoms ta
                ON ta.atom_id = asm.atom_id AND ta.tour_id = $1::uuid
            WHERE asg.segment_id = ANY($2::text[])
            GROUP BY asg.segment_id, asg.canonical_place, asg.canonical_action
        """, route["tour_id"], segment_ids)

        snapshot = _build_snapshot(route, segment_ids, step_rows)
        route_pick_id = await conn.fetchval("""
            INSERT INTO acp_contract.route_pick (tenant_id, hub_name, route_snapshot, selected_by)
            VALUES ($1::uuid, $2, $3::jsonb, $4)
            RETURNING route_pick_id
        """, tenant_id, route["hub_name"], json.dumps(snapshot), selected_by)

    return {
        "route_pick_id": str(route_pick_id),
        "hub_name": route["hub_name"],
        "route_snapshot": snapshot,
    }


def _build_snapshot(route, segment_ids: list[str], step_rows) -> dict:
    by_day = sorted(
        (r["day"], r["canonical_place"], r["canonical_action"] or "")
        for r in step_rows if r["day"] is not None
    )
    resolved_stops = stops(by_day)
    return {
        "route_id": route["route_id"],
        "tour_id": str(route["tour_id"]),
        "hub_id": str(route["hub_id"]) if route["hub_id"] else None,
        "hub_name": route["hub_name"],
        "ordered_segment_ids": segment_ids,
        "first_day": route["first_day"],
        "last_day": route["last_day"],
        "score": route["score"],
        "places": list(dict.fromkeys(s.place for s in resolved_stops)),
        "stops": [
            {"day": s.day, "place": s.place, "actions": list(s.actions)}
            for s in resolved_stops
        ],
    }


__all__ = [
    "Moment", "Route", "Stop",
    "LEAST_DAYS", "LEAST_PLACES", "MOST_DAYS", "SHARED_ENOUGH",
    "derive_routes", "families", "stops", "journey_name",
    "run_route_detection", "create_route_pick",
]
