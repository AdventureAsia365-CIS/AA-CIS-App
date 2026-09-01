"""
services/acp_shared/slate.py — AA-511: the Slate (Weekly Slots' replacement).

Ported/adapted from Ms. Thư's aa-social-media `src/aa_social/stages/slate.py`
(`choose()`/`recommend()`) — full evidence and every deviation disclosed in
docs/claude_audit/AA-511-step0-slate-investigation.md. Read that file first for the "why", not
just this module's docstrings.

**Does not compute a score.** Per STEP0 Q1 (confirmed by reading the origin's own `slate.py`:
it reads `atom_scores` verbatim, never recomputes), `subject.score` is copied as-is from
`acp_contract.atom_ranking.total_rank` (Segment subjects — 7 non-Blog channels) or
`acp_contract.route.score` (Route/Blog subjects, AA-510's own mean-of-total_rank formula — the
origin has no Route-Subject concept at all to answer this from, see STEP0 Q2). Building a
second, parallel scoring formula here (an `acp_shared.segment_score` table) would duplicate
already-live AA-515 data — confirmed NOT to build it (STEP0 point 3a).

**Bar thresholds are the origin's real numbers** (`reference/channels.toml`, STEP0 Q3), not
invented, not a binary "has data" check:

    Blog        needs_demand=1000  needs_questions=3   (grain: Route)
    LinkedIn/Facebook/Instagram/TikTok   needs_said=150 (grain: Segment)
    Email/Landing Page/Ads               on_demand, no bar (needs_*=0, grain: Segment)

Bar reads `atom_ranking.demand_volume`/`questions`/`said` directly — NOT
`silver_aa_internal.seo_context` (that would re-derive a number AA-515 already computed and
persisted, and could disagree with it; STEP0 point 3a's correction to the build prompt's own
Bar section).

**Not ported from `choose()`**: the "one place per Channel" de-dup and `most_per_hub` hub-cap.
Both require a Hub/Route join for every one of the 7 non-Blog (Segment-grain) channels that this
build was not asked to construct (the build prompt's own scope: "đọc atom_segment/route theo
tenant, join atom_ranking lấy Score, áp Bar theo Channel, ghi cleared_bar_reason" — Bar and Score
only). `most_per_hub` is "effectively off" (99) for every Channel in the origin anyway, so this
mostly costs the de-dup rule — disclosed gap, not a silent omission: a Channel's list can show
the same place twice via two different Segments/actions. Worth a follow-up once Hub-per-Segment
resolution has a real consumer to justify building it.

**Identity, not `hashlib.sha256(...)` like the origin's `subject_id()`.** `acp_shared.subject`
uses a random `uuid` PK (per the build prompt's own literal schema) — idempotent re-propose is
instead done via two partial unique indexes on `(tenant_id, channel, segment_id)` /
`(tenant_id, channel, route_id)` (migration 133) and an `ON CONFLICT ... DO UPDATE` that refreshes
`score`/`cleared_bar_reason` on a still-`proposed` row without ever touching one a tenant has
since `picked`/`used`/`cut` — same "a judgement already made is not made again" rule the origin's
own `_store()` implements, ported in spirit not in mechanism.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

# One row per Channel: the Bar (STEP0 Q3, literal reference/channels.toml numbers), which grain
# it reads (Blog is the one Channel scored at Route grain — AA-CIS's own extension, STEP0 Q2),
# and whether it is on-demand (no weekly rhythm, origin's derive_posting_rhythm() skips these
# entirely — STEP0 Q3's own finding: the origin has no rules-based Subject list for these at all,
# this build runs the same Bar/choose logic against them anyway, at their default-zero bar).
CHANNEL_BARS: dict[str, dict] = {
    "blog":          {"needs_demand": 1000, "needs_questions": 3, "needs_said": 0,
                       "grain": "route", "on_demand": False},
    "linkedin":      {"needs_demand": 0, "needs_questions": 0, "needs_said": 150,
                       "grain": "segment", "on_demand": False},
    "facebook":      {"needs_demand": 0, "needs_questions": 0, "needs_said": 150,
                       "grain": "segment", "on_demand": False},
    "instagram":     {"needs_demand": 0, "needs_questions": 0, "needs_said": 150,
                       "grain": "segment", "on_demand": False},
    "tiktok":        {"needs_demand": 0, "needs_questions": 0, "needs_said": 150,
                       "grain": "segment", "on_demand": False},
    "email":         {"needs_demand": 0, "needs_questions": 0, "needs_said": 0,
                       "grain": "segment", "on_demand": True},
    "landing_page":  {"needs_demand": 0, "needs_questions": 0, "needs_said": 0,
                       "grain": "segment", "on_demand": True},
    "ads":           {"needs_demand": 0, "needs_questions": 0, "needs_said": 0,
                       "grain": "segment", "on_demand": True},
}

WEEKLY_RHYTHM_CHANNELS = tuple(c for c, s in CHANNEL_BARS.items() if not s["on_demand"])
ON_DEMAND_CHANNELS = tuple(c for c, s in CHANNEL_BARS.items() if s["on_demand"])


@dataclass(frozen=True)
class Candidate:
    """One Segment or Route worth proposing to a Channel, before the Bar is applied."""

    segment_id: str | None
    route_id: str | None
    score: float
    demand: int | None
    questions: int
    said: int
    place: str | None = None
    action: str | None = None
    hub_name: str | None = None


def _clears_bar(channel: str, candidate: Candidate) -> tuple[bool, dict]:
    """Whether a Candidate clears one Channel's Bar, and the reason either way.

    Literal `>=` comparisons against `reference/channels.toml`'s own numbers (STEP0 Q3) —
    `choose()`'s `if (subject.demand or 0) < channel.needs_demand: continue`, inverted to a
    positive predicate plus a recorded reason (`cleared_bar_reason` is NOT NULL regardless of
    outcome — an unmet bar is as reportable as a cleared one, matching the origin's own
    "an exclusion is arguable rather than a silent absence" philosophy for transit/unnamed-place).
    """
    spec = CHANNEL_BARS[channel]
    demand = candidate.demand or 0
    demand_ok = demand >= spec["needs_demand"]
    questions_ok = candidate.questions >= spec["needs_questions"]
    said_ok = candidate.said >= spec["needs_said"]
    cleared = demand_ok and questions_ok and said_ok
    reason = {
        "channel": channel,
        "on_demand": spec["on_demand"],
        "needs_demand": spec["needs_demand"], "demand": candidate.demand, "demand_ok": demand_ok,
        "needs_questions": spec["needs_questions"], "questions": candidate.questions,
        "questions_ok": questions_ok,
        "needs_said": spec["needs_said"], "said": candidate.said, "said_ok": said_ok,
    }
    return cleared, reason


async def _fetch_segment_candidates(tenant_id: UUID, pool) -> list[Candidate]:
    """One Candidate per ranked, non-excluded Segment.

    `atom_ranking`'s grain is (tenant, tour, segment) with identical rank/measured values
    replicated per tour a Segment touches (AA-515 Decision 3, confirmed in STEP0) — `MIN()` over
    the GROUP BY collapses that multiplicity back to one row per Segment without approximating
    anything (the values are guaranteed equal, not merely similar).
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT ar.segment_id,
                   MIN(ar.total_rank)     AS total_rank,
                   MIN(ar.demand_volume)  AS demand_volume,
                   MIN(ar.questions)      AS questions,
                   MIN(ar.said)           AS said,
                   MAX(asg.canonical_place)  AS canonical_place,
                   MAX(asg.canonical_action) AS canonical_action
            FROM acp_contract.atom_ranking ar
            JOIN acp_contract.atom_segment asg ON asg.segment_id = ar.segment_id
            WHERE ar.tenant_id = $1::uuid AND ar.excluded_reason IS NULL
            GROUP BY ar.segment_id
        """, tenant_id)
    return [
        Candidate(
            segment_id=r["segment_id"], route_id=None, score=r["total_rank"],
            demand=r["demand_volume"], questions=r["questions"] or 0, said=r["said"] or 0,
            place=r["canonical_place"], action=r["canonical_action"],
        )
        for r in rows
    ]


async def _fetch_route_candidates(tenant_id: UUID, pool) -> list[Candidate]:
    """One Candidate per Route (Blog-only grain, AA-CIS's own extension — STEP0 Q2).

    Demand/questions are aggregated across the Route's member Segments, a choice this build
    discloses rather than ports (the origin never bars a Route at all): demand = the STRONGEST
    single keyword any member Segment carries (mirrors `_demand()`'s own "the strongest rather
    than the sum" philosophy, one level up — a Route's search case rests on its best moment, not
    an average of weaker ones); questions = the SUM across member Segments (the FAQ pool a Blog
    piece draws from is genuinely the union of every moment's questions along the walk, matching
    how `slate.py::_asked()` already pools questions across every atom_id a Subject carries).
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT r.route_id, r.score, r.hub_name,
                   MAX(ar.demand_volume) AS demand_volume,
                   COALESCE(SUM(ar.questions), 0) AS questions
            FROM acp_contract.route r
            LEFT JOIN LATERAL (
                SELECT ar2.demand_volume, ar2.questions
                FROM acp_contract.atom_ranking ar2
                WHERE ar2.tenant_id = r.tenant_id AND ar2.tour_id = r.tour_id
                  AND ar2.segment_id = ANY (
                      SELECT jsonb_array_elements_text(r.ordered_segment_ids)
                  )
                  AND ar2.excluded_reason IS NULL
            ) ar ON true
            WHERE r.tenant_id = $1::uuid
            GROUP BY r.route_id, r.score, r.hub_name
        """, tenant_id)
    return [
        Candidate(
            segment_id=None, route_id=r["route_id"], score=r["score"],
            demand=r["demand_volume"], questions=int(r["questions"] or 0), said=0,
            hub_name=r["hub_name"],
        )
        for r in rows
    ]


async def propose_slate(tenant_id: UUID, pool) -> dict:
    """Recompute what clears each Channel's Bar right now, and persist it (AA-511's `run()`).

    Runs on every `GET /v1/slate` (matches the origin: "Storing is deterministic and always
    runs... the evidence a Subject carries has to be able to grow"). A row already `picked`/
    `used`/`cut` is NEVER touched by this function — only rows still sitting at `proposed` are
    refreshed or removed. A candidate that no longer clears the Bar (or no longer exists) has its
    stale `proposed` row deleted; this is the one place this build's Bar-only scope still ports
    the origin's `delete_missing()` behavior, since leaving a phantom `proposed` row around would
    make `GET /v1/slate`'s own eligible-count wrong.
    """
    segments = await _fetch_segment_candidates(tenant_id, pool)
    routes = await _fetch_route_candidates(tenant_id, pool)

    async with pool.acquire() as conn:
        async with conn.transaction():
            live_segment_ids: dict[str, set[str]] = {}
            live_route_ids: dict[str, set[str]] = {}
            for channel in CHANNEL_BARS:
                spec = CHANNEL_BARS[channel]
                candidates = routes if spec["grain"] == "route" else segments
                live_segment_ids[channel] = set()
                live_route_ids[channel] = set()
                for candidate in candidates:
                    cleared, reason = _clears_bar(channel, candidate)
                    if not cleared:
                        continue
                    if candidate.segment_id:
                        live_segment_ids[channel].add(candidate.segment_id)
                        # The ON CONFLICT target must match idx_subject_unique_segment's own
                        # predicate exactly (`WHERE segment_id IS NOT NULL`, migration 133) --
                        # `state` is checked in the DO UPDATE's own WHERE instead, so a conflict
                        # against an already-picked/used/cut row is a silent no-op (left alone)
                        # rather than an inference-target mismatch error.
                        await conn.execute("""
                            INSERT INTO acp_shared.subject
                                (tenant_id, segment_id, route_id, channel, cleared_bar_reason, score)
                            VALUES ($1::uuid, $2, NULL, $3, $4::jsonb, $5)
                            ON CONFLICT (tenant_id, channel, segment_id) WHERE segment_id IS NOT NULL
                            DO UPDATE SET cleared_bar_reason = excluded.cleared_bar_reason,
                                          score = excluded.score
                            WHERE acp_shared.subject.state = 'proposed'
                        """, tenant_id, candidate.segment_id, channel,
                            json.dumps(reason), candidate.score)
                    else:
                        live_route_ids[channel].add(candidate.route_id)
                        await conn.execute("""
                            INSERT INTO acp_shared.subject
                                (tenant_id, segment_id, route_id, channel, cleared_bar_reason, score)
                            VALUES ($1::uuid, NULL, $2, $3, $4::jsonb, $5)
                            ON CONFLICT (tenant_id, channel, route_id) WHERE route_id IS NOT NULL
                            DO UPDATE SET cleared_bar_reason = excluded.cleared_bar_reason,
                                          score = excluded.score
                            WHERE acp_shared.subject.state = 'proposed'
                        """, tenant_id, candidate.route_id, channel,
                            json.dumps(reason), candidate.score)

            for channel in CHANNEL_BARS:
                await conn.execute("""
                    DELETE FROM acp_shared.subject
                    WHERE tenant_id = $1::uuid AND channel = $2 AND state = 'proposed'
                      AND segment_id IS NOT NULL
                      AND NOT (segment_id = ANY($3::text[]))
                """, tenant_id, channel, list(live_segment_ids[channel]))
                await conn.execute("""
                    DELETE FROM acp_shared.subject
                    WHERE tenant_id = $1::uuid AND channel = $2 AND state = 'proposed'
                      AND route_id IS NOT NULL
                      AND NOT (route_id = ANY($3::text[]))
                """, tenant_id, channel, list(live_route_ids[channel]))

    return {"segments_seen": len(segments), "routes_seen": len(routes)}


async def fetch_slate(tenant_id: UUID, pool) -> dict:
    """Everything currently on the Slate, grouped by Channel, strongest (lowest score) first.

    Presentation fields (`place`/`action`/`hub_name`) are joined live rather than duplicated on
    the `subject` row, since `acp_contract.route` is rebuilt whole (DELETE+INSERT) every T5/T7
    ranking run — a `subject` whose Route was just rebuilt away shows with `place`/`hub_name`
    NULL rather than crashing (LEFT JOIN); this is expected for a `proposed` row (the next
    `propose_slate()` call cleans it up) and disclosed as stale-but-harmless for a `picked` one
    (matches `acp_contract.route_pick`'s own ADR-0024 "outlives the thing it came from" pattern
    one layer up — this build does not yet snapshot a picked Subject the same way, see the
    build prompt's own scope: pick only needs to flip `state` and create the `angle_gate_request`).
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.subject_id, s.channel, s.state, s.score, s.cleared_bar_reason,
                   s.segment_id, s.route_id, s.created_at,
                   asg.canonical_place, asg.canonical_action,
                   r.hub_name, r.ordered_segment_ids, r.tour_id
            FROM acp_shared.subject s
            LEFT JOIN acp_contract.atom_segment asg ON asg.segment_id = s.segment_id
            LEFT JOIN acp_contract.route r ON r.route_id = s.route_id
            WHERE s.tenant_id = $1::uuid AND s.state != 'cut'
            ORDER BY s.channel, s.score ASC NULLS LAST, s.subject_id
        """, tenant_id)

    by_channel: dict[str, list[dict]] = {c: [] for c in CHANNEL_BARS}
    for r in rows:
        reason = r["cleared_bar_reason"]
        if isinstance(reason, str):
            reason = json.loads(reason)
        by_channel.setdefault(r["channel"], []).append({
            "subject_id": str(r["subject_id"]),
            "channel": r["channel"],
            "state": r["state"],
            "score": float(r["score"]) if r["score"] is not None else None,
            "cleared_bar_reason": reason,
            "segment_id": r["segment_id"],
            "route_id": r["route_id"],
            "place": r["canonical_place"],
            "action": r["canonical_action"],
            "hub_name": r["hub_name"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })

    return {
        channel: {
            "channel": channel,
            "on_demand": CHANNEL_BARS[channel]["on_demand"],
            "eligible_count": sum(1 for s in subjects if s["state"] == "proposed"),
            "subjects": subjects,
        }
        for channel, subjects in by_channel.items()
    }


class SubjectNotFoundError(Exception):
    """No `acp_shared.subject` row for this id, for this tenant."""


class SubjectNotEligibleError(Exception):
    """The Subject exists but is not in `state = 'proposed'` (already picked/used/cut)."""


async def pick_subject(tenant_id: UUID, subject_id: UUID, pool, selected_by: str) -> dict:
    """Flip a Subject `proposed -> picked` and create the matching `angle_gate_request`
    (T8's own entry point, `services/acp_angle_gate/service.py::create_request()` grain is
    per-atom — a real, disclosed simplification for a Route/Blog Subject: `atom_id` resolves to
    ONE representative atom (the Route's first ordered Segment's first member atom for its own
    `tour_id`), not the whole walk. T9's writer therefore currently sees only that one atom's
    text, not the full journey `acp_contract.route.ordered_segment_ids` describes — the same
    class of disclosed gap AA-515's own `said_rank` note carries ("technically wired, near-inert
    until a real consumer exists"), flagged for whoever next extends T9 to read a Route's full
    walk. `channel` is set on `angle_gate_request` immediately (this build knows it already, from
    the Subject) rather than through the AA-469 Việc 4 two-step atom-then-channel flow, which
    stays exactly as it is for the atom-picker's own (non-Slate) entry point.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT subject_id, channel, state, segment_id, route_id
            FROM acp_shared.subject WHERE subject_id = $1::uuid AND tenant_id = $2::uuid
        """, subject_id, tenant_id)
        if row is None:
            raise SubjectNotFoundError(f"subject_id={subject_id} not found for this tenant")
        if row["state"] != "proposed":
            raise SubjectNotEligibleError(
                f"subject_id={subject_id} is '{row['state']}', not 'proposed'"
            )

        atom_id, trip_id = await _resolve_representative_atom(
            conn, tenant_id, row["segment_id"], row["route_id"],
        )
        if atom_id is None:
            raise SubjectNotEligibleError(
                f"subject_id={subject_id} has no live atom left to write from "
                "(its Segment/Route was rebuilt away) — refresh the Slate and pick again."
            )

        async with conn.transaction():
            await conn.execute(
                "UPDATE acp_shared.subject SET state = 'picked' WHERE subject_id = $1::uuid",
                subject_id,
            )
            request_row = await conn.fetchrow("""
                INSERT INTO acp_shared.angle_gate_request
                    (tenant_id, atom_id, trip_id, channel, subject_id)
                VALUES ($1::uuid, $2, $3::uuid, $4, $5::uuid)
                RETURNING request_id, tenant_id, atom_id, trip_id, channel, status, created_at
            """, tenant_id, atom_id, trip_id, row["channel"], subject_id)

    return {
        "subject_id": str(subject_id),
        "channel": row["channel"],
        "request_id": str(request_row["request_id"]),
        "atom_id": request_row["atom_id"],
        "trip_id": str(request_row["trip_id"]) if request_row["trip_id"] else None,
        "status": request_row["status"],
    }


async def _resolve_representative_atom(
    conn, tenant_id: UUID, segment_id: str | None, route_id: str | None,
) -> tuple[str | None, str | None]:
    """One (atom_id, trip_id) to hand T8 — see `pick_subject()`'s own docstring for the
    disclosed Route/multi-atom simplification this makes."""
    if segment_id:
        row = await conn.fetchrow("""
            SELECT m.atom_id, ta.tour_id
            FROM acp_contract.atom_segment_member m
            JOIN acp_contract.tour_atoms ta ON ta.atom_id = m.atom_id
            WHERE m.segment_id = $1 AND NOT m.is_alias
              AND ta.owner_scope = $2::text AND NOT ta.deleted AND NOT ta.is_empty_marker
            ORDER BY m.atom_id LIMIT 1
        """, segment_id, str(tenant_id))
        return (row["atom_id"], str(row["tour_id"])) if row else (None, None)

    route = await conn.fetchrow(
        "SELECT tour_id, ordered_segment_ids FROM acp_contract.route WHERE route_id = $1", route_id,
    )
    if route is None:
        return None, None
    segment_ids = route["ordered_segment_ids"]
    if isinstance(segment_ids, str):
        segment_ids = json.loads(segment_ids)
    if not segment_ids:
        return None, None
    row = await conn.fetchrow("""
        SELECT m.atom_id
        FROM acp_contract.atom_segment_member m
        JOIN acp_contract.tour_atoms ta ON ta.atom_id = m.atom_id
        WHERE m.segment_id = $1 AND ta.tour_id = $2::uuid
          AND ta.owner_scope = $3::text
          AND NOT m.is_alias AND NOT ta.deleted AND NOT ta.is_empty_marker
        ORDER BY m.atom_id LIMIT 1
    """, segment_ids[0], route["tour_id"], str(tenant_id))
    return (row["atom_id"], str(route["tour_id"])) if row else (None, None)


__all__ = [
    "CHANNEL_BARS", "WEEKLY_RHYTHM_CHANNELS", "ON_DEMAND_CHANNELS",
    "Candidate", "propose_slate", "fetch_slate", "pick_subject",
    "SubjectNotFoundError", "SubjectNotEligibleError",
]
