# AA-515 STEP0 — Ranking/Atom Score stage

Read-only investigation. No code changed. Discovered as a blocking gap during AA-510 STEP0
(`docs/claude_audit/AA-510-step0-route-hub-investigation.md`, Q2/Q3/Q5): Route needs atoms
already ranked to build `ordered_segment_ids` and to compute `family` overlap, and AA-CIS has no
such stage. Blocks the rest of AA-507's chain (AA-510→511→512→513→514).

## Q1 — Ms. Thư's real ranking/atom_score module: criteria, formula, pipeline stage

**Module**: `src/aa_social/stages/score.py`, stage `score` — runs 4th in the pipeline
(`ingest → atoms → research → score → slate → write`, per repo `CLAUDE.md`), i.e. **after**
Segment matching (Segment is built inside the `atoms` stage itself, per `CLAUDE.md`: "`aa run
atoms` # a place-and-activity pair per day, in Segments") and **after** `research` (DataForSEO
search-demand fetch — `score` reads what `research` already wrote).

**The unit ranked is the Segment, not the Atom** — module docstring, line 3: *"The Segment is the
unit, not the Atom. A Segment is one real-world moment and an Atom is one itinerary's telling of
it, so ranking Atoms ranks the same moment once per phrasing."* Scores are computed once per
Segment then **written per Atom** (`_store()`), "because that is what the slate reads."

**Formula — a rank-sum, per ADR 0014** (`rank()`, `score.py:141-178`): four terms, each a
*competition rank* (1, 2, 2, 4 — ties share a rank, `_ranks()`), summed, **lowest total wins**:
1. `demand_rank` — search volume, ranked separately per market (Segment scored once per brand
   market, keeps its best-ranking market — `_demand_ranks()`). A Segment nothing was searched for
   takes the **median** rank of the measured Segments, not last place ("absence of evidence is
   not evidence of absence" — but "known unsearched is worse than unknown", so still not
   equal-to-measured either).
2. `recurrence_rank` — how many itineraries the Segment recurs across.
3. `questions_rank` — how many People Also Ask questions landed on it.
4. `said_rank` — how many characters the itineraries spend describing the moment (a later
   addition per ticket 46 — "the only signal here that comes from a person deciding a moment was
   worth describing").

Explicitly **no weights, no tuning constant** — "a rank-sum has nothing to tune, which is the
point — anything tuned would have been invented rather than measured." Two Segment classes are
excluded outright before ranking (ADR 0019 transit, ADR 0020 unnamed place) but stay visible in
the ranked output under their own heading.

**Route is derived INSIDE this same stage**, right after storing scores (`score.py:104-108`,
`run()`): *"Routes are derived here rather than in `slate` because they are made of what this
stage ranked, and because the ranked file is where an exclusion or a family has to be
arguable."* This directly answers AA-510's own open question: Route in the reference pipeline is
built strictly from RANKED Segments (post-exclusion), not raw ones.

## Q2 — Is this the same concept as `distinctiveness`/`dfs_relevance`, or different?

**Confirmed different — three separate axes, not two, and none of them is the reference's
rank-sum ranking.** Read both AA-CIS modules directly, not inferred:

| | `score_distinctiveness()` | `score_dfs_relevance()` | Ms. Thư's `score.py` rank-sum |
|---|---|---|---|
| Grain | **Atom**-level | **Tour**-level (explicitly NOT atom-level) | **Segment**-level (written per-atom) |
| Input | Competitor-content token-overlap (`acp_shared.competitor_index_cache`) | `seo_context.keyword_ideas[].search_volume`, MAX per tour | Search demand (per market) + itinerary recurrence + PAA count + description length |
| Output | HIGH/MED/LOW (3-bucket) | HIGH/MED/LOW (3-bucket) | Integer rank-sum (ordinal, not bucketed) |
| Purpose | "How distinctive vs. what competitors already say" | "Is this whole tour worth prioritizing for search-led content" | "Which Segment is worth writing about first, and in what order do its days become a Route" |
| File | `services/acp_shared/competitor_index.py` | `services/acp_shared/dfs_relevance.py` | (no AA-CIS equivalent exists) |

`dfs_relevance.py`'s own docstring states the boundary explicitly and cites the same ADR the
STEP0 prompt names: *"ADR-2026-038 §0.4 ... `dfs_relevance` is a SEPARATE axis from
`distinctiveness` ... This one is TOUR-level ... never attached to an individual atom."* Neither
axis computes anything resembling recurrence-across-itineraries or PAA-count **per Segment**, and
neither produces an ordering usable for `ordered_segment_ids` — both are single independent
buckets per (atom|tour), not a comparative rank across a set. **Confirmed by code, not
supposition: AA-515's "ranking" is a third, currently-nonexistent thing** — closer in spirit to
Ms. Thư's `score.py` (a comparative, order-producing rank-sum over Segments) than to either
existing AA-CIS axis. Reusable as raw ingredients, though — see Q3.

(Note: `ADR-2026-038` itself is not a committed file anywhere in this repo — every reference to
it, in both `dfs_relevance.py`'s own docstring and this repo's `CLAUDE.md`, cites it by section
number only. It is tracked as a real, Accepted decision but not as a markdown ADR doc — same
absence an earlier audit, `AA-439-03-t5-t6-dfs-scoring-audit.md`, already found for the same
label. Not a blocker, just noting where the "already Accepted" claim's paper trail actually
lives — nowhere in this checkout as a standalone file.)

## Q3 — Are they persisted? Usable foundation, or build from scratch?

**`score_distinctiveness()` — persisted, real column.** Written directly into
`acp_contract.tour_atoms.distinctiveness` at T5 atomize time
(`services/acp_produce/tenant_pipeline.py:371-379`, the literal `INSERT`). A durable, queryable,
per-atom value today.

**`score_dfs_relevance()` — NOT persisted as a standing column.** `fetch_dfs_relevance_by_tour()`
recomputes it on every call, live, from `seo_context.keyword_ideas` (`dfs_relevance.py:98-127`) —
no `dfs_relevance` column exists in any migration (`grep` across `api/migrations/*.sql` for the
literal string — zero `CREATE`/`ALTER` hits, only comments referencing the module). Its only
persisted trace is a **per-request snapshot**, not a general table: migration 127
(`angle_gate_request_dfs_paa_snapshot.sql`) freezes one `SearchDemandSignal` (relevance + PAA +
related keywords) onto the specific `angle_gate_request` row that asked for it at T8 — scoped to
one tenant/atom/moment-of-asking, not a reusable ranking source for Route.

**Neither is a usable foundation for AA-515's ranking table as-is** — `distinctiveness` measures
the wrong axis (competitive uniqueness, not search-worthiness-for-ordering) and has no recurrence/
PAA-count/said-length terms; `dfs_relevance` is tour-grain (would need re-deriving per Segment)
and isn't persisted anywhere queryable in bulk. Both are legitimate, real, live-computed **inputs**
a rank-sum COULD read (demand bucket from `dfs_relevance` logic re-grained to Segment; PAA count
already sits in `seo_context.people_also_ask`) but neither is "the ranking stage, already built
under a different name" — a genuinely new stage/table is needed, not a rename.

## Q4 — T6 curation vs. automated ranking: confirmed different in kind, by code

**Confirmed, re-checked directly against current code, not just AA-510's earlier exclusion.** T6
(`frontend/app/(tenant)/portal/_components/AtomsTab.tsx` + `PATCH /atoms/{atom_id}`,
`admin_atoms.py`) exposes exactly two atom-level actions a human can take: `starred` (boolean
toggle) and `deleted` (soft-delete) — both plain `PATCH` writes, no algorithm, no comparison
across atoms. `starred`/`deleted` default `false` at insert and only change via an explicit human
click (`v1_atoms.py`'s insert code, confirmed in the AA-439-03 audit and unchanged since).
Automated ranking (both the reference's rank-sum and AA-515's proposed stage) is a **computed,
re-run, comparative ordering across every atom/Segment in scope** — the two are orthogonal
inputs to whatever consumes them next (N6 allocator already multiplies `starred` and
`distinctiveness` together as independent weight factors, `allocator.py:116`, confirmed in the
AA-439-03 audit — proof the codebase already treats "human curated" and "auto-scored" as separate
multiplicative terms, not one blended thing). **T6 curation is not, and should not become, the
ranking mechanism AA-515 is asking for.**

## Q5 — Where should ranking run in T5→T6→T7: before/parallel/after Segment (AA-509)?

**Recommendation, not a decision — flagging for chốt**: Ms. Thư's own stage order is
`atoms(+Segment) → research → score(ranking) → slate(Route)`, i.e. **ranking runs strictly AFTER
Segment matching**, because the ranked unit IS the Segment (`_candidates()` reads
`segment_members JOIN atoms JOIN atom_scores` — Segment membership must already exist to know
which Atoms to fold into one Candidate). This is not an arbitrary choice in the source: ranking
per-Atom would double/triple-count one real-world moment retold across itineraries (the module's
own opening example — the Nakasendo walk arriving 13 times). **Porting the same order to AA-CIS
(T5 atomize → AA-509 Segment matching → AA-515 ranking → AA-510 Route) is the evidence-backed
choice**, not ranking in parallel with Segment or before it.

Consequence for AA-510's own Q2/Q5 open items (now answered by this ordering): Route's
`derive_routes()` input (`Moment.score`) and `families()`'s "ranked" Segment-set both need
AA-515's ranking to have already run for the same `(tenant_id, tour_id)` before Route can build —
confirms AA-515 is a genuine prerequisite, not parallelizable, matching the STEP0 prompt's own
framing.

**Two real open design questions this STEP0 does NOT resolve** (flagging, not deciding):
1. AA-CIS's own `research` stage equivalent (T2's DataForSEO fetch, `seo_context`) is TOUR-level,
   not per-Segment/per-keyword-per-moment the way Ms. Thư's `search_demand` table is (keyed
   `(keyword, market)`, fed by a research loop that explicitly chooses which Segment to look up
   per ADR mentioned in `_demand_ranks()`'s own docstring). AA-CIS has no per-Segment keyword
   research loop today — only a per-tour DataForSEO fetch. A literal port of `_demand_ranks()`
   needs a demand SOURCE keyed at Segment grain, which doesn't exist; reusing the existing
   tour-level `dfs_relevance` numbers as a per-Segment proxy would be a real design substitution,
   not a port — needs an explicit decision.
2. Whether `recurrence` (itineraries a Segment recurs across) should count ALL tenants' rewrites
   of a tour or stay scoped to the one tenant deriving the ranking — segment_id is already
   tenant-partitioned (AA-509's `_mint()` folds `tenant_id` in), so a cross-tenant recurrence
   count is not even reachable by construction unless the query deliberately widens past one
   tenant's own segments. Likely should stay single-tenant (matches every other AA-509/510
   convention already established) but not yet confirmed against a build prompt.

## Should know

- Ranking is a genuinely new stage for AA-CIS — neither `distinctiveness` nor `dfs_relevance` is
  it, under a different name or otherwise (Q2/Q3).
- Stage order evidence points to: T5 atomize → AA-509 Segment → **AA-515 ranking** → AA-510 Route.
- `ADR-2026-038` is not a file in this repo (any repo checked) — cited by section number only,
  same gap an earlier audit already found. Not blocking, just don't go looking for a markdown ADR
  that isn't there.
- This STEP0 does not design AA-515's actual schema/formula — it confirms the reference
  mechanism exists, is portable in shape, and identifies the two real gaps (Segment-grain demand
  source; tenant-scoping of recurrence) a build prompt needs to settle first.
