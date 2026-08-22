# AA-439-05 — How DFS is actually used today (A1/T2), for the score_distinctiveness() design

Fact-finding only — no formula proposed, no design decided. Branch
`feature/aa-439-tenant-tier-audit`. Every number below is either a direct code read (`path:line`)
or a real query against `aa-cis-dev-db` (S3-mediated ECS exec, 22/08 18:34 UTC), except the
DataForSEO price figures, which are from DataForSEO's own live pricing pages (fetched this
session, not from memory — cited per page).

**Headline for the design decision: DFS is currently called once per TOUR, never per keyword
and never per atom, and its output is already persisted per-tour in `silver_aa_internal
.seo_context` — reusable for free. But (a) tenant rewrites (T1/T2) never call DFS at all today
— only the admin/aa_internal pipeline does — and (b) the current per-tour call pattern doesn't
use DataForSEO's batch-task pricing at all, which matters enormously if per-atom calls are ever
considered.**

---

## 1. Real DFS client — every method, and what level it operates at

`services/seo_intelligence/dataforseo_client.py` (full read, 228 lines). All methods take one
`seed: str` (a single search phrase) — **none accept a list of keywords or operate per-atom**:

| Method | DataForSEO endpoint | Output level |
|---|---|---|
| `fetch_keywords(seed, ...)` | `keywords_data/google_ads/search_volume/live` | 1 keyword's volume (the seed itself) |
| `_serp_advanced(seed, ...)` | `serp/google/organic/live/advanced` | 1 SERP result set — serves BOTH PAA and related searches from one call |
| `fetch_people_also_ask` / `fetch_related` | (wrap `_serp_advanced`) | same one SERP call, reused |
| `fetch_keyword_ideas(seed, ...)` | `keywords_data/google_ads/keywords_for_keywords/live` | up to 25 keyword-idea objects, each with `search_volume`/`competition`/`competition_index`/`cpc` |
| `fetch_all(seed, ...)` | orchestrates all of the above | **3 real HTTP calls per invocation** (search_volume + SERP + keyword_ideas) |

**No `keyword_difficulty` field anywhere** — confirmed by reading every parser
(`_parse_keywords`, `_parse_paa`, `_parse_keyword_ideas`, `_parse_related`). Only
`search_volume`, `competition`, `competition_index`, `cpc` exist. (`competition`/
`competition_index` are Google Ads *bid density* metrics, not an SEO-difficulty score — a
different thing from "keyword difficulty," worth not conflating.) This matches AA-439-04's
finding that the reference implementation also lacks this field — **confirmed true of the real
client too, not just the old reference code.**

A second, separate DFS module exists for the N7 production pipeline:
`services/acp_produce/dataforseo.py` (257 lines) — `fetch_serp_profile`/`parse_top_pages`,
same shape as the reference `aamc/dataforseo.py`'s `serp_read`/`parse_top_pages`. Also no
`difficulty` field (grepped). This one is called from `services/acp_produce/research.py` and
`slot_runner.py` — the **weekly content-production brief stage (N7/T8-T10)**, not
atomize/rewrite. Confirmed by import sites, not re-read line-by-line (out of scope for this
task's question).

## 2. Where the seed is built — confirmed: per TOUR, not per keyword, not per atom

`services/seo_intelligence/seed_builder.py::build_seed(country_raw, activities, tour_name)`
(full read, 97 lines) — pure function, one call produces ONE seed string per tour:
```python
def build_seed(country_raw: str, activities, tour_name: str = "") -> str:
    ...
    if a and c:
        return f"{a} in {c}"          # e.g. "trekking in Vietnam"
    ...
```
Priority: activity+country > tour_name+country > country-only. **One seed, one tour, called
once** — confirmed by its only real caller (`admin_pipeline.py:464`, inside `_execute_run_tour`,
one call per tour being rewritten). There is no per-keyword or per-atom loop anywhere calling
`build_seed()` or the DFS client repeatedly for the same tour.

## 3. Who actually calls DFS — confirmed: admin pipeline only, tenant rewrite never does

Grepped every caller of `process_seo()` (the persistence-and-cache wrapper) across the whole
repo: **the only call site is `api/routers/admin_pipeline.py:474`**, inside `_execute_run_tour`
— the admin/aa_internal S1-Rewrite pipeline (A1). **`api/routers/v1_tours.py::trigger_rewrite()`
(T1/T2, the tenant-facing rewrite audited in AA-439-01) never imports or calls `process_seo`,
`DataForSEOClient`, or `build_seed` anywhere in its full body** (re-checked this task,
cross-referencing AA-439-01's full read of that function). **A tenant's own rewrite of a
published tour makes zero DataForSEO calls today.**

This matters directly for the design question: the DFS data that *does* exist for a tour came
from when **aa_internal** (admin) originally rewrote and published it — not from anything the
tenant triggered. It's still real, tour-scoped, reusable data (see §4) — just note that its
existence is a side effect of the A1 pipeline, not something T1/T2 produces or refreshes.

## 4. Is DFS data persisted? Yes — one row per tour, in `seo_context`, reusable without a new call

`services/seo_intelligence/handler.py::process_seo()` (full read, 230 lines):
- Redis cache layer (`RedisCache`, keyed by `(seed, location_code)`, 24h TTL) — **shared across
  tours** that happen to have the same seed+market, so a second tour with an identical seed
  doesn't trigger a second set of DFS HTTP calls.
- **But every tour still gets its own DB row regardless of cache hit or miss** — the code
  explicitly falls through to a per-tour insert either way (`handler.py:135-137`'s own comment:
  *"persist runs for BOTH cache_hit and freshly-fetched data — every tour gets its own
  seo_context row regardless of whether the Redis cache saved us the DataForSEO call"*).
- Table: `silver_aa_internal.seo_context` — columns `tour_id, keyword_search (the seed),
  top_keywords, keyword_ideas (the full volume/competition/cpc array), people_also_ask,
  related_keywords, cache_key, fetched_at, expires_at`.

**Confirmed live**: `seo_context` has **50 rows, 50 distinct `tour_id`s** — exactly one row per
tour, no duplicates. **This data is queryable by `tour_id` today, with zero new DFS calls
needed** — any atom-scoring design that joins `acp_contract.tour_atoms.tour_id →
seo_context.tour_id` gets real DFS output for free, for the 50 tours that have ever gone
through A1. (2551 platform-scope atoms exist across many more tours than 50 — see §7 for the
coverage gap this implies.)

## 5. Real data quality caveat — the most recent real row has entirely null DFS values

Live sample, the single newest `seo_context` row (21/08, `tour_id=00164580-...`):
```json
{
  "keyword_search": "Full day city tour Mongolia",
  "top_keywords": ["Full day city tour Mongolia"],
  "keyword_ideas": [{"keyword": "Full day city tour Mongolia", "search_volume": null,
                      "competition": null, "competition_index": null, "cpc": null}]
}
```
**Every numeric field is null.** This isn't a parsing bug — it's DataForSEO genuinely returning
no data for this specific seed (a fabricated-sounding, overly-generic multi-word phrase,
consistent with the exact seed-genericity problem AA-251/ADR-2026-021 already documented
elsewhere in this codebase). **Worth flagging plainly for the design decision**: even where a
`seo_context` row exists, it is not guaranteed to carry a real, usable number — any formula
built on "reuse the tour's existing DFS data" needs a defined fallback for null volume, not an
assumption that persisted data is always populated.

## 6. Real usage volume — last 30 days

```
seo_context total (all-time): 50 rows, 50 distinct tours
Last 30 days: 44 rows
  by day: 2026-07-29 → 30, 2026-08-13 → 8, 2026-08-17 → 4, 2026-08-12 → 1, 2026-08-21 → 1
Oldest row: 2026-07-12. Newest: 2026-08-21 (yesterday of this audit).
```
No dedicated DFS-call-log table exists anywhere in the schema (checked
`information_schema.tables` for any `%dataforseo%`/`%dfs%`-named table — zero results) — row
count in `seo_context` is the only available proxy for "how many times `process_seo()` ran," and
even that slightly overcounts real DFS HTTP traffic (a cache hit still inserts a row but skips
the 3 HTTP calls). **This is a genuinely low-volume workload today** — well under 50 real fetch
attempts a month.

## 7. Real DataForSEO pricing (fetched live from dataforseo.com this session, not from memory)

| Endpoint used by this app | Live-mode price |
|---|---|
| `keywords_data/google_ads/search_volume/live` | **$0.09 per task** — a task can hold **up to 1,000 keywords** at the same flat price |
| `keywords_data/google_ads/keywords_for_keywords/live` | same Google Ads Live-mode tier, **$0.09 per task**, same up-to-1,000-keyword batch |
| `serp/google/organic/live/advanced` | **$0.002 per SERP** (first), **$0.0015** for each additional SERP in the same batch |

**Real, concrete inefficiency found**: `fetch_keywords()` and `fetch_keyword_ideas()` both send
`"keywords": [seed]` — **a single-element list**, paying the full $0.09 flat task price for 1
keyword when the SAME $0.09 covers up to 1,000. Every tour-level fetch today costs, worst case
(no cache hit): $0.09 (search_volume) + $0.09 (keyword_ideas) + $0.002 (SERP) ≈ **$0.182 per
tour**. At 44 fetch attempts/30 days (§6, upper bound — some were cache hits costing $0), that's
**at most roughly $8/month** at current volume — genuinely trivial money today, but the
per-request pattern is the thing to watch if volume grows, because of §8 below.

## 8. Cost/volume estimate if DFS were called per-atom instead of per-tour

Live counts (already known from AA-438/439 audits, re-cited here for the estimate): **~2,551
platform-scope atoms + 15 tenant-scope atoms** exist today; AA-439-03 estimated ~150-300 new
atoms/tenant/month at real usage rates.

**If atom-level DFS calls repeated the CURRENT single-keyword-per-task pattern** (§7's
inefficiency, unchanged): scoring the existing 2,566 atoms once would cost roughly
`2,566 × ($0.09 + $0.09 + $0.002) ≈ $467` in a single pass, plus **2,566 separate HTTP round
trips** — a real rate-limit/latency concern for a synchronous or even background-batch process,
not just a cost one.

**If instead batched to DataForSEO's actual task-pricing shape** (up to 1,000 keywords per
$0.09 task — exactly what the *reference* `aamc/research.py`'s `keyword_research()` already does,
batching up to 200 seeds per `search_volume()` call, unlike this app's real client): the same
2,566 atoms' keywords could be search-volume-scored in **3 search_volume tasks + 3
keyword_ideas tasks ≈ $0.54 total**, plus SERP calls only where genuinely needed (SERP is
inherently per-keyword, no batch discount beyond the 25% break on additional SERPs in one
request — so this term doesn't compress the same way; at 2,566 unique atom-derived keywords,
SERP alone would still be roughly `0.002 + 2565×0.0015 ≈ $3.85`).

**The gap between these two numbers (~$467 vs. ~$4-5) is not a rounding difference — it is the
entire question of whether "per-atom DFS" is trivial or expensive**, and it hinges entirely on
whether keywords are batched into DataForSEO's task-based pricing or sent one-at-a-time the way
this app's current client does it for tours. This is handed over as a fact, not a recommendation
— which shape (batched vs. per-call) any future atom-scoring design uses is not decided here.

---

## Summary — facts for the design decision, no formula proposed

| Question | Answer |
|---|---|
| DFS call level today | **Per tour** (one seed, one `fetch_all()`), never per keyword-in-isolation, never per atom |
| Who calls it | **Admin/A1 pipeline only** (`admin_pipeline.py:474`) — tenant rewrite (T1/T2) never does |
| Is it persisted? | **Yes** — `silver_aa_internal.seo_context`, 1 row/tour, joinable by `tour_id`, no new call needed to reuse it |
| Data quality | Persisted rows can be entirely null (real example shown, §5) — not guaranteed usable |
| Real volume, last 30d | 44 `seo_context` inserts (upper bound on real DFS fetch attempts — some were cache hits) |
| Real DFS pricing (live, fetched this session) | search_volume $0.09/task (≤1,000 kw), keywords_for_keywords $0.09/task (≤1,000 kw), SERP $0.002 first / $0.0015 additional |
| Current cost, ~monthly | Roughly ≤$8/month at today's volume |
| `keyword_difficulty` field? | **No** — confirmed absent from the real client, same as the reference implementation |
| Cost if per-atom, unbatched (current pattern) | ~$467 one-time for the existing 2,566 atoms, ~2,566 HTTP round trips |
| Cost if per-atom, properly batched | ~$4-5 one-time for the same 2,566 atoms |

## Open items — explicitly out of scope

- Whether/how to actually build a combined score — not this task's job (per AA-439-04 and this
  task's own instruction).
- `services/acp_produce/dataforseo.py`/`research.py`/`slot_runner.py` internals beyond
  confirming their call sites and endpoint shapes — the N7 brief-compilation stage is a
  different pipeline stage (weekly content production, not atomize), out of scope here.
- Whether DataForSEO's actual production account has a different pricing tier/contract than
  the public live-mode prices fetched this session — not checked, flagged as the public rate
  card only.
