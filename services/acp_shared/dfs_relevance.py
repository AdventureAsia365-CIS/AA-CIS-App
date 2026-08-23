"""
services.acp_shared.dfs_relevance — AA-448, tour-level DataForSEO search-demand signal.

ADR-2026-038 §0.4 (per AA-445-01's citation): `dfs_relevance` is a SEPARATE axis from
`distinctiveness` (services/acp_shared/competitor_index.py — atom-level, competitor
token-overlap). This one is TOUR-level, from real search demand
(`silver_aa_internal.seo_context.keyword_ideas[].search_volume`), used to filter/prioritize
TOURS at T1 (browse pool — not wired by this task, flagged as an open item in the STEP0
investigation) and T7 (quarter plan, this task) — never attached to an individual atom
(§0.4 point 2, and confirmed live: `distinctiveness` stays purely atom-level in
`compute_quarter_plan()`'s existing `dist` term, this module never touches it).

Confirmed via grep before writing this file: `dfs_relevance` had ZERO hits anywhere in this
repo before this task (AA-445-01/AA-448-00 STEP0 both independently found this) — this is a
new module, not a port of existing code.

Thresholds are explicitly uncalibrated (§0.4 point 6, "chưa hiệu chỉnh bằng data thật" —
AA-439-05 separately found the newest real seo_context row had entirely null search_volume) —
kept as a dataclass of named constants, not hardcoded inline, so a follow-up ticket can tune
them without touching any call site (matches this task's own "config được, không hardcode"
instruction).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

Relevance = Literal["HIGH", "MED", "LOW"]

# Same 3-bucket shape as services.acp_shared.competitor_index's Distinctiveness ("HIGH"/"MED"/
# "LOW") — kept as a separate Literal, not the same type alias, because the two are a
# deliberately SEPARATE axis (ADR §0.4 point 1) and importing one module's type into the other
# would blur that boundary for no benefit (they are not interchangeable values).


@dataclass(frozen=True)
class DfsRelevanceThresholds:
    """§0.4's own tentative numbers: LOW < 50/mo, MED 50-500/mo, HIGH > 500/mo. `low_max` is the
    boundary between LOW and MED (exclusive on the low side, i.e. volume < low_max -> LOW);
    `high_min` is the boundary between MED and HIGH (inclusive, i.e. volume >= high_min ->
    HIGH)."""
    low_max: int = 50
    high_min: int = 500


_DEFAULT_THRESHOLDS = DfsRelevanceThresholds()


def score_dfs_relevance(
    search_volumes: list[Optional[int]],
    thresholds: DfsRelevanceThresholds = _DEFAULT_THRESHOLDS,
) -> Relevance:
    """Pure. `search_volumes` = every non-None `search_volume` value already extracted from one
    tour's latest `seo_context.keyword_ideas` row (see `fetch_dfs_relevance_by_tour` below for
    the DB-wiring side that builds this list per tour).

    Uses the MAX of the tour's keyword ideas — the tour's single best real-demand keyword
    opportunity — not an average, which a handful of genuinely-zero-volume long-tail ideas
    (routine in a 25-idea/tour list, AA-197's own cap) would silently drag toward LOW even when
    one strong keyword exists.

    Empty input -> MED. This covers BOTH real cases the task's null-handling requirement names:
    (a) no seo_context row exists yet for this tour (T2 DFS was never run against it), and
    (b) a row exists but every one of its keyword_ideas has search_volume=None (a real, live
    case AA-439-05 already found — DataForSEO can return volume=null per keyword). MED is an
    honest "no signal either way" default, matching `score_distinctiveness()`'s own
    "MED-when-empty... deliberate honest-middle default, not a bug" convention
    (services/acp_shared/competitor_index.py) — not LOW, which would silently punish a tour AA
    simply hasn't run DataForSEO against yet."""
    if not search_volumes:
        return "MED"
    best = max(search_volumes)
    if best < thresholds.low_max:
        return "LOW"
    if best >= thresholds.high_min:
        return "HIGH"
    return "MED"


_SEO_CONTEXT_LATEST_QUERY = """
    SELECT DISTINCT ON (tour_id) tour_id, keyword_ideas
    FROM silver_aa_internal.seo_context
    WHERE tour_id = ANY($1::uuid[])
    ORDER BY tour_id, fetched_at DESC
"""


async def fetch_dfs_relevance_by_tour(
    tour_ids: list[UUID], pool, thresholds: DfsRelevanceThresholds = _DEFAULT_THRESHOLDS,
) -> dict[UUID, Relevance]:
    """DB-wiring wrapper — ONE bulk query for every tour_id in `tour_ids` (not per-trip N+1;
    same bulk convention `fetch_atoms_by_trip()` already uses for atoms). Reads each tour's
    LATEST seo_context row (`DISTINCT ON (tour_id) ... ORDER BY fetched_at DESC` — a tour can
    have more than one row across repair-round re-fetches; "latest wins" matches
    `fetch_current_version_no()`'s own convention elsewhere in this codebase, quarter.py:427).

    Tours with no seo_context row at all are simply ABSENT from the returned dict (same
    "absent means empty, not zero" convention `atoms_by_trip.get(trip.id, [])` already
    establishes) — callers must `.get(trip.id, score_dfs_relevance([]))` i.e. default missing
    keys to `"MED"` themselves; this function does not silently insert every input tour_id with
    a MED placeholder, since that would hide a genuinely-empty result set from a caller that
    wants to distinguish "no tours passed in" from "every tour scored MED"."""
    if not tour_ids:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SEO_CONTEXT_LATEST_QUERY, tour_ids)
    out: dict[UUID, Relevance] = {}
    for r in rows:
        ideas = r["keyword_ideas"]
        if isinstance(ideas, str):
            ideas = json.loads(ideas) if ideas else []
        volumes = [
            i.get("search_volume") for i in (ideas or [])
            if isinstance(i, dict) and i.get("search_volume") is not None
        ]
        out[r["tour_id"]] = score_dfs_relevance(volumes, thresholds)
    return out


__all__ = [
    "Relevance", "DfsRelevanceThresholds", "score_dfs_relevance",
    "fetch_dfs_relevance_by_tour",
]
