"""services/acp_contract/atom_ranking.py — AA-515, the rank-sum stage.

Ported (adapted where AA-CIS genuinely has no equivalent — disclosed below) from Ms. Thư's
aa-social-media `src/aa_social/stages/score.py`. Full evidence: `docs/claude_audit/AA-515-
step0-ranking-investigation.md`, `AA-515-step0b-demand-research-loop.md`,
`AA-515-step0c-multimarket-schema.md`.

**The unit ranked is the Segment**, per ADR 0014 (rank-sum, no weights, no tuning constant) —
4 axes, each a competition rank (1, 2, 2, 4 — ties share a rank), summed, lowest total wins:
demand (per market, best market kept), recurrence (distinct tours a Segment spans, within one
tenant — STEP0b/the build prompt both confirm this stays single-tenant, never cross-tenant,
matching every other AA-508/509 convention), questions (People Also Ask landing on the
Segment), said (how much the itineraries describe the moment).

**`_demand()` reads the `search_demand` cache by NAME (word-overlap), never embedding-match**
— a deliberate choice this build keeps, not re-litigates (STEP0b Q1: the reference repo
measured the embedding matcher under-reaching from 14% to 45% of Segments carrying any demand
at all when switched to name-matching).

**Two adaptations, disclosed, not silent:**
1. **`questions` also uses word-overlap claim-by-name**, not embedding-match. Ms. Thư's own
   `_questions()` lands PAA questions on a Segment via `atom_matches` (built by
   `match_queries_to_atoms()`, an embedding-based landing step this codebase has no equivalent
   infrastructure for — no `atom_matches` table, no `Embedder`). Rather than build a parallel
   embedding-matching subsystem for one axis, this port extends the SAME claim-by-name test
   `_demand()` already uses (and the build prompt already mandated for demand) to the PAA
   questions carried alongside each bought keyword in `search_demand.people_also_ask` — a
   Segment claims a keyword's PAA the same way it claims that keyword's volume. Consistent with
   the demand decision, not a second, different mechanism.
2. **`said` is `SUM(LENGTH(tour_atoms.text))`** — the only per-atom text length signal that
   exists. Real, disclosed limitation: AA-509's own Decision 1 changed `tour_atoms.text` from an
   LLM-written 1-2 sentence narrative to a terse `f"{place} — {action}"` mechanical join, so this
   axis currently carries little real variance (differs mostly by place/action NAME length, not
   by how much an itinerary elaborates on a moment) — same class of "axis technically wired,
   near-inert until its real signal exists" finding this repo's own AA-439-03 audit made about
   `distinctiveness` before AA-445-02 shipped a real function for it. Not fixed here — out of
   this build's scope, flagged for whoever next touches T5's `text` derivation.
3. **`_about_something_else()`/`elsewhere`-refusal (score.py's off-topic-PAA suspect-claim
   check) is NOT ported** — a secondary refinement layered on top of `_demand()`, not the
   rank-sum itself, and depends on a `trips`/country-word table shape this codebase doesn't
   share. Deferred, disclosed, not silently dropped — `_demand()`/`compute_questions()` below
   read every measured row, unfiltered by that refinement.

Transit/unnamed-place exclusion (ADR 0019/0020, `ranking_reference.py`) runs before ranking —
excluded Segments still get a row (per tour they touch) in `atom_ranking`, `excluded_reason`
set, every rank column NULL — "an exclusion is arguable rather than a silent absence" (score.py's
own docstring), not hidden entirely.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from services.acp_contract.ranking_reference import (
    PLACE_KINDS,
    claimable_words,
    is_transit,
    keyword_words,
    names_somewhere,
)


@dataclass(frozen=True)
class Candidate:
    """One Segment and the four things it is ranked on."""

    segment_id: str
    place: str
    action: str
    tour_ids: tuple[str, ...]
    recurrence: int
    questions: int
    said: int
    demand: dict[str, int]


@dataclass(frozen=True)
class RankedSegment:
    segment_id: str
    tour_ids: tuple[str, ...]
    demand_rank: int
    recurrence_rank: int
    questions_rank: int
    said_rank: int
    total_rank: int
    demand_market: str | None
    demand_volume: int | None
    recurrence: int
    questions: int
    said: int


@dataclass(frozen=True)
class ExcludedSegment:
    segment_id: str
    tour_ids: tuple[str, ...]
    reason: str  # 'transit' | 'unnamed_place'


def _competition_ranks(
    candidates: Sequence[Candidate], of: Callable[[Candidate], int],
) -> dict[str, int]:
    """Best first: 1, 2, 2, 4. Equal values take equal ranks — a straight sum would otherwise
    encode the order rows happened to arrive in."""
    ordered = sorted(candidates, key=lambda c: -of(c))
    ranks: dict[str, int] = {}
    previous = None
    place = 0
    for position, candidate in enumerate(ordered, start=1):
        value = of(candidate)
        if value != previous:
            place = position
            previous = value
        ranks[candidate.segment_id] = place
    return ranks


def _demand_ranks(candidates: Sequence[Candidate], market: str) -> dict[str, int]:
    """Rank on demand for one market, with a Segment nothing was measured for taking the
    MEDIAN of the measured — "known unsearched is worse than unknown, but absence of evidence
    is not evidence of absence" (score.py's own reasoning, ported verbatim in spirit)."""
    measured = [c for c in candidates if market in c.demand]
    if not measured:
        return {c.segment_id: 1 for c in candidates}
    ranks = _competition_ranks(measured, lambda c: c.demand[market])
    middle = sorted(ranks.values())[len(ranks) // 2]
    return {c.segment_id: ranks.get(c.segment_id, middle) for c in candidates}


def rank_segments(candidates: list[Candidate], markets: list[str]) -> list[RankedSegment]:
    """Rank-sum every candidate, keeping each one's best market. No weights, no tuning constant
    — a straight sum of 4 competition ranks, lowest wins (ADR 0014).

    Hoists Ms. Thư's own `_demand_ranks(candidates, market)` call out of the per-candidate loop
    her reference `rank()` runs it inside — that call's result depends only on `candidates` and
    `market`, never on which candidate is currently being scored, so it was being recomputed
    identically once per (candidate × market) pair for no reason. Same output, not a change to
    the algorithm — a straightforward hoist, not a re-design.
    """
    if not candidates:
        return []

    recurrence_rank = _competition_ranks(candidates, lambda c: c.recurrence)
    questions_rank = _competition_ranks(candidates, lambda c: c.questions)
    said_rank = _competition_ranks(candidates, lambda c: c.said)
    demand_rank_by_market = {market: _demand_ranks(candidates, market) for market in markets}

    ranked = []
    for candidate in candidates:
        placings = []
        for market in markets:
            demand_rank = demand_rank_by_market[market][candidate.segment_id]
            total = (
                demand_rank + recurrence_rank[candidate.segment_id]
                + questions_rank[candidate.segment_id] + said_rank[candidate.segment_id]
            )
            placings.append((total, market, demand_rank))
        # A tie between markets goes to the first the tenant listed (resolve_buyer_markets'
        # own MARKET_RANK order) — arbitrary but stable, and recorded, so it can be argued with.
        total, market, demand_rank = min(placings, key=lambda p: (p[0], markets.index(p[1])))
        ranked.append(RankedSegment(
            segment_id=candidate.segment_id, tour_ids=candidate.tour_ids,
            demand_rank=demand_rank, recurrence_rank=recurrence_rank[candidate.segment_id],
            questions_rank=questions_rank[candidate.segment_id],
            said_rank=said_rank[candidate.segment_id], total_rank=total,
            demand_market=market, demand_volume=candidate.demand.get(market),
            recurrence=candidate.recurrence, questions=candidate.questions, said=candidate.said,
        ))
    return sorted(ranked, key=lambda r: (r.total_rank, r.segment_id))


def compute_demand(
    place: str, action: str, demand_rows: list[tuple[str, str, int]],
) -> dict[str, int]:
    """Port of score.py's `_demand()` — the strongest keyword a Segment owns, per market, by
    NAME (word-overlap), never embedding-match. `demand_rows` = every (keyword, market, volume)
    row in `search_demand` with a non-null volume, loaded once per ranking run (not re-queried
    per Segment, unlike the reference repo's own per-call SQLite query — Postgres round-trips
    are not free the way a local SQLite file's are; same output, cheaper)."""
    claimable = claimable_words(place, action)
    best: dict[str, tuple[int, int]] = {}
    for keyword, market, volume in demand_rows:
        shared = keyword_words(keyword) & claimable
        if not shared - PLACE_KINDS:
            continue
        fit = len(shared)
        held = best.get(market)
        if held is None or (fit, volume) > held:
            best[market] = (fit, volume)
    return {market: volume for market, (_fit, volume) in best.items()}


def compute_questions(
    place: str, action: str, paa_rows: list[tuple[str, str, list[str]]],
) -> int:
    """How many distinct People Also Ask questions this Segment claims, by the SAME
    claim-by-name test `compute_demand()` uses (docstring item 1 — no embedding-match
    infrastructure exists in this codebase to port `_questions()`'s real mechanism)."""
    claimable = claimable_words(place, action)
    seen: set[str] = set()
    for keyword, _market, questions in paa_rows:
        shared = keyword_words(keyword) & claimable
        if not shared - PLACE_KINDS:
            continue
        seen.update(questions)
    return len(seen)


def classify_exclusion(place: str, action: str) -> str | None:
    """'transit' | 'unnamed_place' | None — the 2 exclusion classes ranking is never applied to
    (ADR 0019/0020), checked in this order because a transit action ("arrive at the trailhead")
    is excluded for what it DOES regardless of whether its place also fails to name somewhere."""
    if is_transit(action):
        return "transit"
    if not names_somewhere(place):
        return "unnamed_place"
    return None


# ── DB-facing wrapper (impure) ──────────────────────────────────────────────────────────────

async def run_atom_ranking(tenant_id: str, markets: list[str], pool) -> dict:
    """Rebuild atom_ranking WHOLE for one tenant (DELETE+INSERT) — matches the AA-510 STEP0
    finding that Ms. Thư's own `routes`/`atom_scores` are "derived, never accumulated"; no
    downstream table has an FK into this one yet expecting stability across re-runs.

    Recomputes over the tenant's WHOLE Segment set, like `run_segment_matching()` and
    `run_segment_research()` — recurrence needs full-tenant visibility regardless of which one
    tour just finished atomizing. `markets` is the tenant's resolved market-code list
    (`resolve_buyer_markets()`, via the caller's already-loaded `target_market` — this module
    has no DB access to `shared.tenant_seo_config` of its own, kept a pure input like the
    reference repo's own `rank(candidates, markets)` signature).
    """
    async with pool.acquire() as conn:
        segment_rows = await conn.fetch("""
            SELECT asg.segment_id, asg.canonical_place, asg.canonical_action,
                   array_agg(DISTINCT ta.tour_id) AS tour_ids,
                   COALESCE(SUM(LENGTH(COALESCE(ta.text, ''))), 0) AS said
            FROM acp_contract.atom_segment asg
            JOIN acp_contract.atom_segment_member asm ON asm.segment_id = asg.segment_id
            JOIN acp_contract.tour_atoms ta ON ta.atom_id = asm.atom_id
            WHERE asg.tenant_id = $1::uuid AND NOT ta.deleted AND NOT ta.is_empty_marker
            GROUP BY asg.segment_id, asg.canonical_place, asg.canonical_action
        """, tenant_id)

        demand_rows = await conn.fetch("""
            SELECT keyword, market, search_volume, people_also_ask
            FROM acp_contract.search_demand WHERE search_volume IS NOT NULL
        """)

    demand_tuples: list[tuple[str, str, int]] = []
    paa_tuples: list[tuple[str, str, list[str]]] = []
    for r in demand_rows:
        demand_tuples.append((r["keyword"], r["market"], r["search_volume"]))
        paa = r["people_also_ask"]
        if isinstance(paa, str):
            paa = json.loads(paa) if paa else []
        paa_tuples.append((r["keyword"], r["market"], paa or []))

    included: list[Candidate] = []
    excluded: list[ExcludedSegment] = []
    for row in segment_rows:
        place, action = row["canonical_place"], row["canonical_action"]
        tour_ids = tuple(str(t) for t in row["tour_ids"])
        reason = classify_exclusion(place, action)
        if reason:
            excluded.append(ExcludedSegment(row["segment_id"], tour_ids, reason))
            continue
        included.append(Candidate(
            segment_id=row["segment_id"], place=place, action=action, tour_ids=tour_ids,
            recurrence=len(tour_ids),
            questions=compute_questions(place, action, paa_tuples),
            said=row["said"],
            demand=compute_demand(place, action, demand_tuples),
        ))

    ranked = rank_segments(included, markets or ["US"])
    by_id = {r.segment_id: r for r in ranked}

    ranked_row_count = sum(len(r.tour_ids) for r in ranked)
    excluded_row_count = sum(len(e.tour_ids) for e in excluded)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM acp_contract.atom_ranking WHERE tenant_id = $1::uuid", tenant_id,
            )
            if ranked:
                await conn.executemany("""
                    INSERT INTO acp_contract.atom_ranking
                        (tenant_id, tour_id, segment_id, demand_rank, recurrence_rank,
                         questions_rank, said_rank, total_rank, demand_market, demand_volume,
                         recurrence, questions, said, excluded_reason)
                    VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                            NULL)
                """, [
                    (tenant_id, tour_id, r.segment_id, r.demand_rank, r.recurrence_rank,
                     r.questions_rank, r.said_rank, r.total_rank, r.demand_market,
                     r.demand_volume, r.recurrence, r.questions, r.said)
                    for r in ranked for tour_id in r.tour_ids
                ])
            if excluded:
                await conn.executemany("""
                    INSERT INTO acp_contract.atom_ranking
                        (tenant_id, tour_id, segment_id, recurrence, questions, said,
                         excluded_reason)
                    VALUES ($1::uuid, $2::uuid, $3, 0, 0, 0, $4)
                """, [
                    (tenant_id, tour_id, e.segment_id, e.reason)
                    for e in excluded for tour_id in e.tour_ids
                ])

    return {
        "segments_ranked": len(ranked), "segments_excluded": len(excluded),
        "rows_written": ranked_row_count + excluded_row_count,
    }


__all__ = [
    "Candidate", "RankedSegment", "ExcludedSegment",
    "rank_segments", "compute_demand", "compute_questions", "classify_exclusion",
    "run_atom_ranking",
]
