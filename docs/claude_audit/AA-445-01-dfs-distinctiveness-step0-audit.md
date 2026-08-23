# AA-445-01 — STEP0 investigate: DFS + score_distinctiveness() (B4/T0/T1-T2 scope-finding)

Investigate only, no code changed. Branch `feature/aa-445-01-step0-dfs-investigate`, worktree
`../aa-445-worktree` (per the task's concurrency note — AA-444's uncommitted-work loss avoided).
Builds directly on `AA-439-03` (distinctiveness/N5/N6 trace), `AA-439-05` (DFS call-site/cost
audit) and `ADR-2026-038 §0.4` (Notion, dated 22/08/2026 — **one day before this task started**),
which already answers most of the architecture questions this STEP0 was meant to surface. This
report's job is therefore mostly **verify-against-code**, not propose-from-scratch: confirm what
§0.4 decided still matches the real repo, and flag exactly what remains unbuilt/undecided.

**Headline: nothing in §0.4's design has been built yet (`dfs_relevance` — zero hits anywhere in
the repo, grepped), and one open question from the original AA-445-01 task prompt is already
resolved wrong in its own framing — `distinctiveness` is NOT "never used" by N5/N7. It IS read
with real decision weight by N5 (Quarter Plan) and N6 (Slot Allocator) — N7 (`acp_produce`) reads
it zero times, confirmed by grep. It's currently inert only because the scorer that would ever
set it to anything but the migration default was never built (`AA-317`), not because nothing
reads it.** Separately, this task also found a fully-built, zero-UI tenant-competitor-URL system
(`acp_silver_s2.competitor_inputs` / `/v1/competitors`, AA-88) that §0.4's own T0-intake decision
does not appear to have been checked against — a real option to weigh before building a second,
overlapping mechanism.

---

## Q1 — Does anything real read `distinctiveness`? (N5/N6/N7)

**Yes — N5 and N6, with real decision weight. N7: zero.** Full `distinctiveness` grep, every
read site classified:

| Site | Real decision impact? | Detail |
|---|---|---|
| `services/acp_planning/quarter.py:169` (**N5** Quarter Plan trip scoring) | **Yes** | `dist = sum({"HIGH":1.0,"MED":0.5,"LOW":0.1}[a.distinctiveness] for a in atoms) / len(atoms)`, then `score = runway_fit*0.4 + richness*0.3 + dist*0.3 + forced_bonus` (`quarter.py:171`) — a real 30%-weighted term in which trips get selected as quarter "big rocks." |
| `services/acp_planning/allocator.py:116` (**N6** Slot Allocator atom-selection weight) | **Yes** | `weight = a.weight * (1.5 if starred else 1.0) * {"HIGH":1.5,"MED":1.0,"LOW":0.6}[a.distinctiveness]` — a real multiplier deciding which atom wins a content slot. |
| `services/acp_produce/*` (**N7**, production pipeline) | **No — zero references** | Grepped the entire `services/acp_produce/` tree for `distinctiveness`: 0 hits. N7 does not read this field at all, contrary to the original task prompt's framing ("N7 Produce code — tìm chỗ đọc field distinctiveness"). |
| `frontend/.../AtomsTab.tsx` (T6, tenant), `frontend/app/admin/curation*` | Display/filter only | Real, wired UI (badge, summary breakdown, filter dropdown) — but a UI read, not a pipeline decision. |
| `api/routers/admin_atoms.py` | Query param passthrough | Filters/returns the column; doesn't compute or gate on it. |

**Why it's currently inert despite N5/N6 really reading it**: `score_distinctiveness()` — the one
function that would ever set the column to anything other than its migration-079 default — has
never been written (`AA-317`, confirmed the only mention of that ticket number anywhere in the
repo, `api/routers/v1_atoms.py:248-251`'s own comment: *"distinctiveness/... are deliberately
absent from this INSERT — score_distinctiveness() does not exist yet (AA-317, out of scope
here)"*). AA-439-03 live-queried this yesterday (22/08): **100% of 2,566 non-deleted atoms sit at
`distinctiveness='LOW'`** — not `MED` (a subtlety AA-317's own comment thread had to self-correct
once already, "SỬA S121": `LOW` is `Atom`'s real init default per the reference `aamc/models.py`;
`MED` is only what `score_distinctiveness()` itself returns at *call* time when `idx.phrases` is
empty — N2/AA-299's atom-insert code never calls that function at all, so atoms never reach the
`MED` branch, they just sit at the DB column default). Net effect, unchanged since AA-439-03,
re-confirmed by this task's own read of the same three files: **N5's `dist` term is flat 0.1 for
every trip with any atoms (contributing a fixed 0.03 to every trip's score), and N6's
distinctiveness multiplier is flat 0.6 for every atom — `starred` is the only thing that
currently differentiates atoms in either formula.**

**Consequence for this task's priority question**: building B4/`score_distinctiveness()` is *not*
"build a function nobody calls" (the original task prompt's framing implicitly worried about
that) — N5 and N6 already call it, correctly, every time they run. It's "build a function whose
two real callers have been silently getting the same flat placeholder value since the day those
formulas shipped." That's a stronger case for priority than the task prompt assumed, not a
weaker one.

---

## Q2 — DFS call sites today, and the exact place to extend to T2

**Two genuinely different things in this codebase are both called "DFS" — worth separating
before answering, because the task prompt's own citations (ADR-2026-021 pointing at
`graph.py:446-462`) name the validation check, while ADR-2026-038 §0.4's "DFS mở rộng T2" is
about the search-volume *data fetch*, not that check. Confirmed via code + both ADRs that they
are wired independently:**

### 2a. `process_seo()` — the actual DataForSEO fetch (what §0.4 means by "DFS")
Confirmed (re-verifying AA-439-05, still true): only one real call site,
**`api/routers/admin_pipeline.py:458-488`** (A1 admin rewrite) — builds a seed via
`build_seed()`, calls `process_seo(tour_id=..., seed=..., ...)`, then passes the result as
`seo=seo_data` into `_rewrite_tour()` (`admin_pipeline.py:493`).

`_rewrite_tour()` (`api/routers/v1_pipeline.py:82`) is the **same function**, shared by A1 and
T1/T2 — not a tier-branched implementation. It takes `seo: dict = None` and defaults to `{}`.
Three real call sites, traced this task:

| Caller | Passes `seo=`? | Tier |
|---|---|---|
| `admin_pipeline.py:490-498` | **Yes**, `seo_data` from a fresh `process_seo()` call | A1 |
| `api/routers/v1_tours.py:317-321` (`trigger_rewrite()`, aliased `_do_rewrite`) | **No** — no `seo=` kwarg at all | T2 (tenant rewrite) |
| `services/acp_produce/tenant_pipeline.py:152-154` (T3 QA-gate repair round) | **No** | T2/T3 repair re-rewrite |

So T1/T2 doesn't skip DFS via a flag or a tier check — it **structurally can't reach it**, because
neither of its two `_rewrite_tour()` call sites builds a `seo_data` dict or passes one in. This
confirms AA-439-05's finding at the exact call-site level (not just "T1/T2 never calls
`process_seo`" — now: "the two lines where it *could* pass that data into the shared graph never
do").

**Exact extension point** (already decided in principle by ADR-2026-038 §0.4 point 3, 22/08,
*not yet built*): mirror `admin_pipeline.py:458-488`'s pattern inside `v1_tours.py`'s
`trigger_rewrite()`, before its `_do_rewrite(...)` call at line ~317 — check for an existing
`seo_context` row by `tour_id` first (free, per AA-439-05 §4 — most rewritten tours were
originally A1-generated and already have one), call `process_seo()` only on a miss (~$0.18/tour,
AA-439-05 §7), then pass `seo=seo_data`. The same fix would need to be duplicated at
`tenant_pipeline.py:152-154` if repair-round rewrites should also carry SEO data (not addressed
by §0.4, worth deciding explicitly rather than assuming).

### 2b. `DFS_INTENT_UNDERUSED` — the validation check (what the task's own file citation names)
`services/content_generation/graph.py`'s `validate_node` (the `_dfs_intent_tokens`/
`_keyword_intent_matched`/`_DFS_INTENT_OVERLAP_THRESHOLD` block, real code at lines 414-445 and
the check itself at **654-669** in the current file — not 446-462 as ADR-2026-021 cites; that ADR
is dated 06/07/2026, before enough unrelated edits landed above it to drift the line numbers,
confirmed by reading the current file directly rather than trusting the ADR's line reference).
This check reads `state.get("seo", {})` — the **same** `seo` dict as 2a, so it's automatically
"extended to T2" the moment 2a is fixed, with no separate code change needed for the check itself
(it's already inside the one shared `validate_node`, not a tier-gated function). **But
ADR-2026-038 §5 explicitly scopes this specific check to A2 only, "not T3"** — so extending 2a
(the data fetch, for `dfs_relevance`) is a settled direction, while whether `DFS_INTENT_UNDERUSED`
itself should start actually *failing* T3 content once T2 has real `seo` data is a **separate,
already-declined** question per §5, not an open one. Don't conflate the two when scoping AA-445-02
— feeding T2 real `seo` data will make this check newly *able* to fire for tenant rewrites as a
side effect (today it can't fire — `seo_kws` is always empty), which is a real behavior change
worth flagging explicitly in that build task even though it's not the primary goal.

Side note, not chased further (out of scope): `graph.py`'s own AA-251 code (`_DFS_INTENT_TOKEN_RE`,
threshold 0.5, `seed_builder.py`'s comment referencing "DFS_INTENT_UNDERUSED false-positive") and
`tests/unit/test_aa251_dfs_intent_seed_fuzzy.py` show ADR-2026-021's "hướng 4" fix is already
built and tested — that ADR's own header ("implementation chờ STEP 0") reads as stale against the
current code; flagged for whoever next touches that ADR, not investigated further here.

---

## Q3 — T0 (`BrandTab.tsx`) domain-list field: does it exist?

**No — confirmed by full read of `frontend/app/(tenant)/portal/_components/BrandTab.tsx` (269
lines).** Its only fields are `system_prompt`, `style_guide`, `forbidden_words` (comma-separated
string in the UI, JSONB in the DB) — nothing domain/competitor-adjacent. Backing table:
**`shared.tenant_brand_rules`** (migration `005_tenant_config.sql` — the task prompt's generic
name "brand_identity" is not the real table name, confirmed via `v1_tours.py`'s own query at
line ~289: `FROM shared.tenant_brand_rules`):

```sql
CREATE TABLE shared.tenant_brand_rules (
    id SERIAL PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES shared.tenants(tenant_id),
    system_prompt TEXT, style_guide TEXT,
    forbidden_words JSONB DEFAULT '[]', custom_validators JSONB DEFAULT '[]',
    version INT DEFAULT 1, is_active BOOLEAN DEFAULT TRUE, updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

ADR-2026-038 §0.4 already decided (22/08) domain intake belongs at T0/Brand Setup — a new JSONB
column (e.g. `competitor_domains JSONB DEFAULT '[]'`) matches this table's own existing
convention (`forbidden_words` is the same shape: JSONB array on this exact row, versioned the
same way). No new table needed for this piece, confirming the task prompt's own assumption.

**But a real, already-built alternative was found this task, not covered by §0.4's decision**:
`acp_silver_s2.competitor_inputs` (migration `027_competitor_inputs.sql`, ticket AA-88) —
```sql
CREATE TABLE acp_silver_s2.competitor_inputs (
    id UUID PK, tenant_id UUID REFERENCES shared.tenants(tenant_id),
    country VARCHAR(100) NOT NULL, url TEXT NOT NULL, label VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE, added_by UUID, created_at/updated_at TIMESTAMPTZ,
    UNIQUE (tenant_id, url)
);
```
— with a **complete CRUD API already shipped**, `api/routers/v1_competitors.py` (`GET/POST/PATCH/
DELETE /v1/competitors`, max 10 active URLs/country, ownership-verified). Grepped the entire
`frontend/` tree for any call to `/v1/competitors` (not just the word "competitor"): **zero
matches** — this API has no UI anywhere, tenant or admin. `frontend/app/admin/pipeline/s2/page.tsx`
(the only file that even mentions "competitor") is a run-context/Gate-B viewer, never calls this
endpoint.

This is a genuine option worth weighing before AA-445-02 is scoped, not something to silently
pick past: `tenant_brand_rules.competitor_domains` (bare domains, tenant-global, matches AA-317's
`domains: list[str]` shape exactly, zero existing infra) vs. **reusing** `competitor_inputs`
(full URLs not bare domains, scoped **per-country** not tenant-global, already has a working
ownership-checked CRUD API — just needs a UI built and its consumer changed from S2's Apify path
to B4's plain-fetch path). The per-country scoping is a real shape mismatch against AA-317's
"tenant declares domains" design (a tenant's competitors plausibly differ by country market) —
worth deciding deliberately, not by default.

---

## Q4 — Does S2's DataForSEO/Apify competitor path give B4 anything to reuse?

**No — confirmed by full read of `services/acp/s2/tools/apify.py` (108 lines): S2's competitor
mechanism doesn't actually capture competitor page text anywhere, so there's no phrase corpus to
reuse even in principle, separate from the tech (Apify) being a different dependency than B4's
designed `requests.get`.**

- S2 uses **Apify** (`apify~website-content-crawler`, a paid third-party crawler,
  `APIFY_API_TOKEN` required), never DataForSEO, for competitor content — confirmed by grepping
  `apify.py` for any DataForSEO import: none. DataForSEO in S2 (`services/acp_produce/
  dataforseo.py`, separately, N7's stage) only checks *whether* a known competitor domain appears
  in SERP results (`competitor_present: bool`, `dataforseo.py:219-220`) — a boolean flag, not
  page content, and belongs to N7's SERP-gap-brief stage, not S2.
- `apify.py`'s own node (`make_apify_node`) is **fire-and-forget**: it looks up the tenant's
  `competitor_inputs` rows, `POST`s a crawl job to Apify's `/runs` endpoint, and immediately
  stores only `{run_id, country, apify_run_id, competitor_urls, fetched_at}` to S3 — **it never
  polls the crawl for completion or reads back any crawled page text.** `competitor_count` (used
  by `confidence.py` for a scoring dimension) and a bare `competitors_s3_key` reference (used by
  `synthesize.py`'s Bedrock prompt for LLM-driven gap commentary) are the only two things
  downstream ever gets from this path — never the actual scraped HTML/text a token-overlap
  `CompetitorIndex.phrases` corpus needs.
- Confirms AA-439-03 Part B's separate finding from the other direction: even the **reference**
  `aa-marketing-v2` design's B4 (`competitor_index()`) only implements agency-declared-domain
  fetch, never the "SERP-discovered rivals" DataForSEO-adjacent half its own prose mentions — and
  this app's current S2 build is a third, different thing again (URL-level intake + an
  unconsumed async Apify job), not an implementation of either half.

**Answer: (b) — B4 needs its own code path.** There is nothing to adapt from S2's DataForSEO
client (wrong tool, boolean-only output) or its Apify integration (never reads its own crawl
results back). The only reusable *asset*, not code path, is the `competitor_inputs` **table** and
its CRUD API discussed in Q3 — as a storage/intake location, not a fetch mechanism. B4's actual
fetch (`requests.get` against tenant-declared domains' homepages, per AA-317's already-chosen
design) has no existing implementation anywhere in this repo to build on or collide with.

---

## Synthesis — what ADR-2026-038 §0.4 already decided vs. what's still open

§0.4 (22/08/2026, one day before this task) already settled the core architecture question the
original AA-445-01 prompt was written to surface, so this section reports **gap-to-build**
against that decision, not a fresh proposal:

**Already decided (§0.4), confirmed still unbuilt (0 hits for `dfs_relevance` anywhere in the
repo, this task's own grep):**
1. Two separate signals, not combined into one atom score: `distinctiveness` (atom-level,
   competitor token-overlap, unchanged algorithm from `aamc/corpus.py`) and `dfs_relevance`
   (tour-level, from `seo_context.search_volume`) — kept apart specifically because §0.4's own
   reasoning shows combining them would leave both axes flat at once (0% tenants have a
   competitor index → `distinctiveness` always `MED`/`LOW`; DFS is tour-flat by construction →
   every atom in a tour would tie).
2. `dfs_relevance` used to filter/prioritize **tours** at T1 (pool selection) and T7 (Quarter
   Plan) — never attached to individual atoms.
3. Competitor domain intake goes at **T0** (Brand Setup) — see Q3 above for the two real storage
   options this task found, only one of which (`tenant_brand_rules` + new column) §0.4 appears to
   have actually considered.
4. T2 gets DFS by reusing `process_seo()` — see Q2a above for the exact two call sites that need
   the change.
5. Starred stays a third, independent signal — no code change implied, already true today.
6. Tentative `dfs_relevance` thresholds proposed (LOW <50/mo, MED 50–500/mo, HIGH >500/mo),
   explicitly flagged in §0.4 itself as uncalibrated against real volume distribution — same
   class of risk AA-439-05 §5 already found live (the newest real `seo_context` row has entirely
   null `search_volume`), so a null-handling default (§0.4 point 3: MED) is necessary, not
   optional, from day one.

**Not decided by §0.4, real open points for AA-445-02's scope (options, not a recommendation):**

- **B4 domain-list storage** (Q3): new `tenant_brand_rules.competitor_domains` JSONB column
  (matches §0.4's stated T0 location exactly, tenant-global, zero reuse) vs. repurposing
  `acp_silver_s2.competitor_inputs` (already has a working CRUD API and ownership checks, but is
  per-country-scoped and URL-shaped, and its only current consumer is the unrelated,
  non-content-capturing Apify path from Q4) — a UI would need to be built either way, since
  neither currently has one.
- **Where the `CompetitorIndex.phrases` corpus itself lives**: no table anywhere in this schema
  today holds scraped competitor phrase text (confirmed — `competitor_inputs` stores only input
  URLs, not fetched content; Apify's own crawl output is never even pulled back per Q4). B4 needs
  a new place to persist this (new table, or a JSONB blob on an existing per-tenant row) plus a
  refresh/TTL policy, since it's live homepage scraping that will go stale.
- **`dfs_relevance` in N5's formula**: §0.4 point 2 says it "thay hoặc bổ sung `runway_fit`"
  (replace or add to) without choosing — `quarter.py:171`'s current formula
  (`runway_fit*0.4 + richness*0.3 + dist*0.3 + forced_bonus`) already sums its three weights to
  1.0, so adding a 4th weighted term means re-deriving all four weights, not just plugging in a
  number. `runway_fit` itself measures buyer-journey funnel timing (BOFU/MOFU window), a
  genuinely different concept from search demand — worth flagging that "replace" and "add" are
  not a minor wording difference here.
- **T7 doesn't have a tenant-facing surface yet** (re-confirmed consistent with AA-440's earlier
  finding, not re-audited fully this task) — so `dfs_relevance` feeding T7 only helps the
  admin-side Gate-B `quarter.py` computation today, not a tenant screen, until T7 tenant
  self-service ships separately.
- **T1 (`PoolTab.tsx`) has a `sort` state today but no relevance/DFS option** in it (confirmed by
  reading the component's filter state) — surfacing `dfs_relevance` at T1 is a real, un-scoped
  frontend change, not just a backend field being populated.
- **`DFS_INTENT_UNDERUSED` side effect** (Q2b): once T2 gets real `seo` data, this existing check
  becomes newly *able* to fire on tenant rewrites for the first time (today it structurally can't
  — `seo_kws` is always empty for T2). ADR-2026-038 §5 already declined extending this check's
  *gating* to T3 — AA-445-02 should decide explicitly whether to suppress/ignore this check's
  output for tenant-tier content (to honor §5) or let it fire as an incidental consequence of the
  DFS data-fetch fix, rather than let it happen silently.

## Verification note

Every claim above is either a direct `path:line` code read (this session, current repo state,
23/08/2026) or a live prior finding re-cited from `AA-439-03`/`AA-439-05` (both dated 22/08/2026,
re-checked against the same files this task read fresh rather than trusted blindly — e.g. the
`v1_atoms.py:248-251` comment, `distinctiveness` default value, and DFS call-site list were all
independently re-grepped, not copy-pasted from the prior reports). Linear AA-317 (full issue +
its 1 comment) and both Notion ADRs (2026-038 §0.4 full text, 2026-021 full text) were fetched
live this session, quoted verbatim above where load-bearing.

## Open items — explicitly out of scope for this STEP0

- Whether to actually build B4/CompetitorIndex before or after `dfs_relevance` — AA-317's own
  comment already flags this as a real sequencing question ("effort thấp hơn dự kiến" once
  scoped, but still "làm sau, không chặn N2"); not re-decided here.
- The exact HIGH/MED/LOW `search_volume` thresholds' real calibration — §0.4 itself already
  flags this needs real post-launch data, not resolvable from this repo alone.
- Whether `acp_silver_s2.competitor_inputs`'s existing per-country scoping is the *right* grain
  for a tenant's declared domain list, product-wise — flagged as a decision point above, not
  settled.
- T7 tenant self-service build status — deferred to AA-440's own audit, not re-verified line-by-
  line this task.
