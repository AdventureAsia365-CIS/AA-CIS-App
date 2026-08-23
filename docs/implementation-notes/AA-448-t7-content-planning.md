# AA-448 — T7 Content Planning (build)

Implementation notes, written incrementally while building (not batched at the end). Follows
`docs/claude_audit/AA-448-00-step0-t7-rewrite-investigation.md` (STEP0, merged into this branch
before build started — not re-derived here).

## Decisions

1. **Keep `services/acp_planning/quarter.py`/`allocator.py`/`runway.py` as the SAME files** — not
   forked into new T7-only copies. Reason found during build, not anticipated in STEP0: the pure
   `compute_*` functions have MULTIPLE live production callers beyond the `/admin/quarter-plan/*`
   routes the task asks to retire — `api/routers/admin_atoms.py`'s `GET
   /admin/atoms/preview-slotgrid` (admin-only N0→N6 visual demo, explicitly "not touched" per
   AA-431) and `api/routers/admin_produce.py`'s `POST /admin/produce/run` (the real N7 trigger,
   explicitly out of scope per this task's own "KHÔNG đụng persist layer N7") both call
   `runway_map()`/`plan_quarter()`/`allocate_month()`/`allocate_month_from_db()` directly, and
   `admin_produce.py`'s `/run` **catches `QuarterPlanNotApprovedError` as real control flow** —
   it is not incidental, it is the actual mechanism that stops content production for a
   never-planned tenant/quarter. Forking the compute functions into a new module would leave two
   divergent copies of the same scoring/allocation logic; editing the shared functions in place
   (adding a backward-compatible optional param for `dfs_relevance`, see Decision 2) keeps every
   existing caller working unchanged while T7 reuses the exact same formula, per the task's own
   "copy logic, not files" instruction.
2. **`compute_quarter_plan()`'s new `dfs_relevance_by_trip` param defaults to `None`** (treated as
   "no data for any trip" → flat MED for every trip, contributing a flat +0.1 constant to every
   score — see Decision 3 for the weight). A flat, equal contribution does not change any
   existing caller's RELATIVE trip ranking (only T7's own new fetch path builds and passes real
   per-trip data) — this is what makes touching the shared function safe for
   `admin_atoms.py`/`admin.py`'s old callers without also updating them to fetch DFS data they
   were never asked to fetch.
3. **4-weight formula: ADDITIVE, not a replacement of `runway_fit`.** ADR §0.4 says "thay HOẶC
   bổ sung `runway_fit`" without choosing. Chose additive because the two signals answer
   genuinely different questions — `runway_fit` measures buyer-journey TIMING (is this
   destination's BOFU/MOFU booking window open this quarter), `dfs_relevance` measures real
   search DEMAND (is anyone actually searching for this) — replacing one with the other would
   delete a still-useful, independent signal rather than deduplicate a redundant one. Old
   weights (0.4/0.3/0.3) scaled down ×0.8 to free exactly 0.2 for the new term
   (`QUARTER_SCORE_WEIGHTS`, constants.py: 0.32/0.24/0.24/0.20), preserving their relative
   importance to each other. Confirmed via the existing `TestScoreReasonTieBreak` unit tests
   (updated + 1 new case added) that ranking behavior for the 3 original factors is unchanged
   in kind, just numerically rescaled.
4. **`dfs_relevance` scored by MAX, not average, of a tour's `keyword_ideas[].search_volume`.**
   A 25-idea/tour cap (AA-197) is mostly long-tail by construction; averaging would let a pile
   of near-zero ideas drag a genuinely strong keyword down to MED/LOW. MAX surfaces "this tour's
   single best real demand opportunity," which is what a planner deciding whether to prioritize
   this tour actually wants to know.
5. **`fetch_tenant_atoms_by_trip()` scopes atoms by `owner_scope = tenant_id` only** — NOT `IN
   ('platform', tenant_id)`. AA-440's writeup of the old `fetch_atoms_by_trip()` bug floated the
   `IN (...)` form as a *possible* fix shape, but it was never actually built anywhere — AA-444's
   `GET /v1/marketplace` (the precedent this task explicitly told T7 to follow) scopes its own
   atom aggregate `owner_scope = $2` only, exact-tenant, no platform atoms included. T7 matches
   that real, already-shipped precedent instead of the unbuilt speculative alternative.
6. **`services/acp_planning/quarter.py`/`allocator.py`/`runway.py` stay the SAME files, edited
   in place — not forked into new T7-only modules.** Found during build (not anticipated in
   STEP0): the pure `compute_*` functions have production callers beyond the `/admin/
   quarter-plan/*` routes this task retires — `admin_atoms.py`'s `GET
   /admin/atoms/preview-slotgrid` (admin-only N0→N6 demo, "not touched" per AA-431) and
   `admin_produce.py`'s `POST /admin/produce/run` (the real N7 trigger, explicitly out of scope
   per this task's own "KHÔNG đụng persist layer N7") both call `runway_map()`/`plan_quarter()`/
   `allocate_month()`/`allocate_month_from_db()` directly — and `admin_produce.py`'s `/run`
   **catches `QuarterPlanNotApprovedError` as real control flow**, not incidentally. Forking
   would leave two divergent copies of the same scoring/allocation logic; editing in place with
   backward-compatible optional params (Decision 7) keeps every existing caller working
   unchanged. This finding directly shapes the STOP point below — see there for the full
   consequence.
7. **New `dfs_relevance_by_trip` param on `compute_quarter_plan()` defaults to `None`** →
   treated as "no data for any trip" → flat MED for every trip → a flat, equal +0.1 constant
   (`SIGNAL_SCORE_MAP["MED"] * 0.20`) added to every trip's score. A flat contribution does not
   change any existing caller's RELATIVE ranking — only T7's own new fetch path
   (`v1_planning.py`) builds and passes real per-trip data. This is what makes touching the
   shared, multiply-called function safe.

## STOP point — Gate B replacement (per task instruction, confirmed before persist/status code)

**Built so far, safe/no decision needed**: `services/acp_shared/dfs_relevance.py` (new),
`services/acp_planning/tenant_pool.py` (new), `compute_quarter_plan()`'s 4th weight
(`quarter.py`/`models.py`/`constants.py`, edited in place), `POST
/v1/planning/quarter-plan/preview` (`api/routers/v1_planning.py`, new router, registered in
`main.py`) — pure compute + a read-only preview, no persistence, no "approval" concept touched
either way. 20 new unit tests + 6 existing ones updated for the new `_score_reason()` signature,
full suite re-run clean (1407 passed, 1 skipped — same pre-existing unrelated skip AA-445-02's
own notes already documented, 0 new failures), flake8 clean on every changed/new file.

**Not yet built, blocked on the decision below**: `GET /v1/planning/quarter-plan` (read the
tenant's current plan), `POST /v1/planning/quarter-plan` (finalize/persist), `GET
/v1/planning/slot-grid`, the 2 "Ms. Thu" exception-message edits (`allocator.py:130,297`), the
`approved`/`approved_by` field removal, `approve_quarter_plan()`/
`approve_quarter_plan_version()` removal, retiring `/admin/quarter-plan/pending`+`/approve`
(`admin.py`), and the full frontend (`PlanningTab.tsx`, `/portal/t7-planning`, Sidebar/
breadcrumb entries) — the UI's "chốt kế hoạch" action needs a concrete finalize-endpoint
response shape, which depends on this decision.

**New finding that changes the shape of the original 2-option framing** (STEP0 investigation
didn't anticipate this — found by tracing every production caller of the functions this task
asks to strip Gate B from): removing the `approved`/`approval_status='pending'` concept
entirely, as the task's own wording ("Bỏ hoàn toàn... toàn bộ khái niệm pending/approve") reads
literally, would **break two live admin features that are explicitly out of this task's scope**:

- `admin_atoms.py`'s `GET /admin/atoms/preview-slotgrid` — branches on
  `fetch_approved_quarter_plan()` returning `None` vs. a real approved plan (`demo_mode`),
  calls `approve_quarter_plan()` (in-memory, `approved_by="admin-preview-demo"`) to satisfy
  `compute_slot_grid()`'s Gate B check, and its `version_id=` param path 400s on a
  non-`'approved'` historical version by design (Gate B "N6 must never read an un-approved
  plan, historical or not").
- `admin_produce.py`'s `POST /admin/produce/run` — the REAL N7 trigger — calls
  `allocate_month_from_db()` and **catches `QuarterPlanNotApprovedError` as its actual
  "tenant/quarter has no plan yet" error path** (`400` to the caller). This is not cosmetic; it
  is the real guard stopping N7 from running with no plan.

Both of these read/write `acp_shared.quarter_plan_version.approval_status` and the `QuarterPlan.
approved`/`approved_by` fields directly — deleting those outright, as literally instructed,
would raise `AttributeError`/break their queries at first real call, not just at import time.

**2 concrete options, given this constraint:**

**Option A — Tenant plans auto-approve at creation (AA-440's own hypothesis (a); minimal
blast radius).** T7's `POST /v1/planning/quarter-plan` calls `save_quarter_plan_version()`
(unchanged) then IMMEDIATELY `approve_quarter_plan_version(version_id, approved_by="tenant:
<tenant_id>", pool)` (unchanged) — no human step, no UI "waiting for approval" state, the plan
is "approved" the instant the tenant finalizes it. `admin_atoms.py`/`admin_produce.py` need
**zero code changes** — `fetch_approved_quarter_plan()` finds a real approved version
immediately, `demo_mode` in preview-slotgrid naturally stops firing once a tenant has actually
planned, `QuarterPlanNotApprovedError` still means exactly what it always meant ("no plan
exists yet for this tenant/quarter") and N7's real guard keeps working unchanged. Only the 2
exception message strings need editing (drop "by a human (Ms. Thu)" wording — the check itself,
its type, and its trigger condition all stay). `approval_status` column keeps its existing
values/meaning; `QuarterPlan.approved`/`approved_by` fields stay in the model.
*Tradeoff*: the word "approved"/`approval_status='pending'→'approved'` still exists in the
schema/model even though no human ever approves anything for a tenant plan — arguably
misleading to a future reader, though every field/column comment can be updated to say so
explicitly.

**Option B — New `is_current` model, `approval_status` semantics changed (AA-440's own
hypothesis (b); larger blast radius).** Repurpose `approval_status` to mean "draft" vs.
"current" instead of "pending-for-staff" vs. "staff-approved" (or add a new boolean column
alongside it). Requires updating `fetch_approved_quarter_plan()`'s query (still called by
BOTH admin endpoints), `admin_atoms.py`'s `demo_mode`/`version_id=` branching logic, and
`admin_produce.py`'s error handling — none of which this task's own scope list currently
authorizes touching ("N7 persist layer untouched" — though this is N4-N6 code these two admin
endpoints call, not `allocator.py`'s persist functions themselves, the *practical* effect on
those two live features is the same "must be touched or they break" either way). *Tradeoff*:
cleaner terminology, no vestigial "approved" language for a flow no human approves — but larger
diff, touches 2 files this task said to leave alone, and needs its own admin-side regression
verification before merging.

**Recommendation: Option A.** It satisfies the task's real intent (no human gate blocks a tenant
from planning) with a change contained entirely to `quarter.py`'s 2 exception strings + T7's new
finalize endpoint — zero risk to the 2 out-of-scope admin features, and reversible/extendable
later (Option B's terminology cleanup can still happen as a separate, dedicated task once T7 is
live). Not implemented yet — waiting for Nghiep/Claude Chat's decision before writing any of
this.

### Update (post-STOP round 2) — Year Plan / Quarter Plan relationship, NEW requirement

Nghiep confirmed the principle behind Gate B's replacement ("plan do tenant nào tạo thì tenant đó
tự duyệt") applies to BOTH options above — the choice between A/B is about code shape, not
product intent, and that part is settled. But a new requirement surfaced that the schema
question above didn't account for: **"1 kế hoạch/năm, chia sẵn 4 quý bên trong — sửa 1 quý = sửa
1 phần của CÙNG 1 plan năm đó"** — not 4 independent `QuarterPlanVersion` rows that happen to
share a `year` value, which is what today's schema actually is.

**Confirmed by re-reading the live schema (`api/migrations/092_acp_quarter_plan.sql`,
`quarter.py:310-352`)**: `acp_shared.quarter_plan` is `UNIQUE(tenant_id, year, quarter)` — one
row per QUARTER, not per year. There is no table today that represents "a tenant's 2027 content
plan" as a single addressable thing; a year is currently just 4 unrelated rows that happen to
share a `year` integer. This is a real gap against the new requirement, not a
misunderstanding on my part to correct — confirmed by direct schema read, not assumed.

**#1 — Is the current model compatible, or is a new concept needed?** Not compatible as-is.
`compute_quarter_plan()` itself (the pure scoring function) is FINE unchanged — it inherently
operates on one quarter at a time because its core formula (`runway_fit`) is computed from
`runway.stage(dest, market, month)`, which is fundamentally quarter/month-shaped (BOFU/MOFU
windows differ by month) — there is no version of "compute all 4 quarters' trip selection in one
call" that would even make sense mathematically; the scores themselves are legitimately
different per quarter. What's missing is a **grouping/persistence concept above** the existing
per-quarter rows, not a change to how quarters are scored. Two schema shapes to choose between
(NOT implemented, no migration written — this needs your confirmation first, per your
instruction):

- **Shape 1 (recommended) — additive `year_plan` wrapper.** New table
  `acp_shared.year_plan(year_plan_id, tenant_id, year, status, created_at, UNIQUE(tenant_id,
  year))` + one new nullable FK column `acp_shared.quarter_plan.year_plan_id`. Every existing
  table/column keeps its current meaning exactly as today — this is purely additive, zero risk
  to `quarter_plan_version`'s existing per-quarter version history (the History tab, AA-323
  round 4, already lets a tenant see v1-v5 PER QUARTER — that granularity survives unchanged).
  A tenant's first finalize of ANY quarter in a given year auto-creates (or reuses) that year's
  `year_plan` row and links to it.
- **Shape 2 (heavier, not recommended without a stronger reason) — full annual restructure.**
  Collapse `quarter_plan`+`quarter_plan_version` into one row/version PER YEAR, with all 4
  quarters' data inside one JSON payload. Bigger diff, and it would need to either throw away or
  redesign the existing per-quarter version-history UI concept (AA-323 round 4) — a real
  regression risk to something already shipped, for no requirement this task actually names.

**#2 — Does editing Q2 after Q1 is finalized affect Q1?** This is the actual product decision
still open (not schema shape — behavior). Two options, both buildable on TOP of Shape 1 without
changing which one you pick:

- **(b) Quarters stay independent — recommended.** Each quarter keeps its own
  finalize/edit lifecycle exactly as today (`quarter_plan_version.approval_status` per quarter,
  unchanged); `year_plan` is a grouping/display label only (e.g., a rollup like "3/4 quý đã
  chốt" computed on read, not a gate). Editing/finalizing Q2 never touches Q1's version or
  status at all. This matches how the scoring mechanically works (quarters are genuinely
  different computations, see #1) and needs the LEAST new logic — `year_plan` never gates
  anything, it only groups.
- **(a) Whole-year atomic approval.** `year_plan.status` itself is the thing "chốt" flips;
  finalizing any single quarter after the year was already marked chốt reverts the YEAR's status
  back to draft (or requires a separate explicit "re-finalize year" action) — even though Q1's
  own `quarter_plan_version` payload/approval is technically untouched, the year-level state
  visibly changes because of a Q2 edit. More moving parts (a status-recompute rule to design and
  test), and doesn't obviously match "tenant tự duyệt kế hoạch của mình" any better than (b) does
  — flagging as the alternative, not recommending it.

**#3 — Gate B options re-proposed with this model in mind.** Good news found while working
through this: **Option A from the original STOP survives unchanged under Shape 1 + (b),
regardless of which of (a)/(b) you pick** — `admin_atoms.py`/`admin_produce.py` only ever call
`fetch_approved_quarter_plan(tenant_id, year, quarter, pool)`, i.e. they check the QUARTER's
`approval_status`, and never look at `year_plan` at all (it does not exist in their code path
either way). So:
- Under (b): T7's per-quarter finalize endpoint still just calls `save_quarter_plan_version()` →
  `approve_quarter_plan_version()` immediately, exactly as Option A originally proposed — the
  only addition is auto-creating/linking the `year_plan` row alongside it (a few extra lines,
  not a behavior change to the approval mechanism itself).
- Under (a): the "finalize" action would instead be a year-level endpoint that loops
  `approve_quarter_plan_version()` across that year's 4 quarters at once — still zero changes
  needed to `admin_atoms.py`/`admin_produce.py`, since the thing they read
  (`quarter_plan_version.approval_status='approved'`) ends up set the same way either way; only
  WHAT TRIGGERS the flip differs.

Net: **the Gate B choice (Option A vs B) and the year/quarter shape choice are independent of
each other** — Option A remains the recommendation regardless of which year/quarter answer you
give, since neither combination requires touching the 2 out-of-scope admin files.

**#4 — Schema impact, and effect on already-built/tested work.** Yes, Shape 1 requires a real
migration (new `acp_shared.year_plan` table + 1 new column on `acp_shared.quarter_plan`) — not
written yet, waiting for confirmation per your instruction not to pick column/table specifics
unilaterally. **Zero impact on the 25 tests already passing** — `dfs_relevance.py`,
`tenant_pool.py`, `compute_quarter_plan()`'s new weight, and `POST
/v1/planning/quarter-plan/preview` never read or write `quarter_plan`/`quarter_plan_version`/any
future `year_plan` table at all (preview computes and returns, never persists) — all of that
work is agnostic to how the persistence layer later groups quarters into years, and needs no
rework under either shape or either (a)/(b) behavior.

**Still waiting on**: confirm Shape 1 vs Shape 2 (recommend Shape 1), confirm (a) vs (b) for
cross-quarter independence (recommend (b)), then Option A can be implemented against whichever
combination is chosen — no further unknowns block starting once these 2 are answered.

### Update (post-STOP round 3) — full symmetric detail on both shapes, no recommendation pushed

Nghiep asked for round 2's two open questions laid out WITHOUT nudging toward the recommended
option — Shape 2 in particular was under-specified last round (I described Shape 1 in schema
detail and Shape 2 only in one sentence). Full write-up below, both shapes to the same level of
detail, plus a correction: round 2's "good news, Option A survives either shape unchanged" claim
was **only actually true for Shape 1** — Shape 2 changes that conclusion (see "Consequence for
Gate B" under Shape 2 below). Also: the "Q1 vs Q2" question itself was under-specified — it
actually bundles 3 separable questions, laid out at the end of this section instead of the
single (a)/(b) binary I asked before.

#### Shape 1 — additive `year_plan` wrapper (full detail, same as round 2)

```sql
CREATE TABLE acp_shared.year_plan (
    year_plan_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    year          INT NOT NULL,
    status        TEXT,  -- exact meaning depends on the (a)/(b) answer below
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, year)
);

ALTER TABLE acp_shared.quarter_plan
    ADD COLUMN year_plan_id UUID REFERENCES acp_shared.year_plan(year_plan_id);
```

`acp_shared.quarter_plan`/`acp_shared.quarter_plan_version` keep every existing column/row/
meaning unchanged — this is purely additive. Each of the 4 quarters stays its own
`quarter_plan` row (as today), now with an extra pointer to a shared parent `year_plan` row.
"1 plan năm" is realized as: **one `year_plan_id` value, addressable as a real row, with 4
linked `quarter_plan` children** — not a single flat record containing all 4 quarters' data.

**What Shape 1 can/can't do:**
- Supports EITHER (a) or (b) below (see "Q1 vs Q2" section) — `year_plan.status` can be either a
  real gate (option a) or a pure computed-on-read rollup (option b); the table shape itself does
  not force either behavior.
- Editing Q2 is: create a new `quarter_plan_version` row under Q2's own `quarter_plan` row —
  completely independent write, Q1's row is never touched, regardless of (a)/(b) (the (a)/(b)
  question only decides whether `year_plan.status` ALSO gets recomputed as a side effect of that
  write, not whether Q1's own data changes — it never does, under either Shape).
- Per-quarter version history (`GET .../{tenant_id}/{year}/{quarter}/history`, AA-323 round 4)
  is completely unaffected — each quarter's own version_no sequence keeps working exactly as
  today.
- **Migration/data impact**: zero data loss, zero ambiguity. The 9 real existing rows (per
  AA-447-01's audit: `acp_shared.quarter_plan`/`quarter_plan_version`, tenant_id populated)
  simply get `year_plan_id = NULL` until first touched by new code, OR a one-time backfill
  (`INSERT INTO year_plan (tenant_id, year) SELECT DISTINCT tenant_id, year FROM quarter_plan`)
  creates the missing parent rows retroactively — no row needs to be merged, split, or
  reinterpreted.
- **Consequence for Gate B**: `admin_atoms.py`/`admin_produce.py` never read `year_plan` at all
  (confirmed — neither file's code references anything beyond `quarter_plan`/
  `quarter_plan_version`/`fetch_approved_quarter_plan(tenant_id, year, quarter, pool)`/
  `fetch_quarter_plan_version(version_id, pool)`, all of which keep their EXACT current
  behavior/contract under Shape 1) — genuinely zero changes needed to either file, confirmed
  holds true.

#### Shape 2 — full annual restructure (full detail, this round's addition)

```sql
CREATE TABLE acp_shared.annual_plan (
    plan_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    year                INT NOT NULL,
    current_version_id  UUID,  -- FK added once annual_plan_version exists
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, year)
);

CREATE TABLE acp_shared.annual_plan_version (
    version_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id           UUID NOT NULL REFERENCES acp_shared.annual_plan(plan_id),
    version_no        INT NOT NULL,
    -- ONE JSON blob holding all 4 quarters, keyed by quarter number:
    -- {"quarters": {"1": <QuarterPlan dict>, "2": {...}, "3": {...}, "4": {...}}}
    payload           JSONB NOT NULL,
    source            TEXT,
    approval_status   TEXT NOT NULL DEFAULT 'pending',  -- ONE status for all 4 quarters together
    approved_by       TEXT,
    approved_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`acp_shared.quarter_plan`/`acp_shared.quarter_plan_version` are REPLACED, not kept alongside —
there is now exactly one row (well, one row per version) representing the whole year; "4 quý"
exist only as sub-keys inside one JSON payload, not as 4 separate addressable DB rows. This is
arguably the MORE literal reading of "1 kế hoạch/năm" — there is truly one record — but it comes
with structural consequences the wording alone doesn't make obvious:

- **Approval is structurally forced to be atomic-whole-year — Shape 2 cannot build option (b)
  below.** There is exactly one `approval_status` column per version, covering all 4 quarters'
  sub-payloads at once. "Q1 approved, Q2 still draft" cannot be represented in this schema at
  all — not a policy choice, a structural limitation of "one status column per row." If
  independent-per-quarter approval is ever wanted (now or later), Shape 2 would need to be
  abandoned/migrated away from to get it.
- **Editing Q2 requires a read-merge-write, and creates a "new version of the whole year" even
  though 3/4 of its content is unchanged.** `save_quarter_plan_version()`'s current shape (a
  simple append-only INSERT) would need to become: fetch the current version's payload → copy
  Q1/Q3/Q4's sub-objects forward unchanged → replace the "2" key with the freshly-recomputed
  Q2 → INSERT one new `annual_plan_version` row. This is a materially different function, not a
  small edit.
- **`fetch_quarter_plan_version(version_id, pool)` — admin_atoms.py's own call site breaks.**
  This function currently returns ONE quarter's full plan, addressed by `version_id` alone
  (the row's own `quarter` column, via the JOIN to `quarter_plan`, tells the caller which
  quarter it is). Under Shape 2, a `version_id` addresses a WHOLE YEAR's payload containing 4
  quarters — the function would need an additional `quarter` parameter to know which embedded
  sub-object to extract and return, which `admin_atoms.py`'s existing call
  (`fetch_quarter_plan_version(version_uuid, pool)`, no quarter param, reads
  `version_row["quarter"]` from the result) does not supply and cannot supply without editing
  that file. **This is a real correction to round 2's framing**: I said Option A "survives
  unchanged under either shape" — that is only true for Shape 1. Shape 2 forces a change to
  `admin_atoms.py` regardless of which Gate B option (A or B) is chosen, because the change is
  about what a "version" addresses (one quarter vs. one year), not about approval semantics at
  all.
- **Per-quarter version history becomes hard to read.** AA-323 round 4's history view currently
  shows each quarter's OWN independent version sequence (Q1 could be on v5 while Q2 is still on
  v1). Under Shape 2, `version_no` is shared across the whole year — editing Q1 five times while
  Q2 is touched once means the year's version counter is at least 6, and Q2's one edit doesn't
  have its own clean "v1" identity anymore; it is just "whatever the shared year-version number
  happened to be when Q2 was last touched," interleaved with Q1's edits. A tenant reviewing
  "Q2's history" would see a list of year-versions mostly describing edits to a DIFFERENT
  quarter. This is a real loss of a currently-shipped capability, not just an implementation
  detail.
- **Migration/data impact — real ambiguity, not just extra work.** The 9 existing
  `quarter_plan_version` rows (per-quarter today) would need to be collapsed into equivalent
  annual-level rows. If a tenant has Q1 v1/v2 and Q3 v1 but Q2/Q4 were never created at all,
  there is no non-arbitrary way to backfill what Q2/Q4's "sub-object" should contain in the
  merged payload (an empty/placeholder `QuarterPlan`? synthesized from `compute_quarter_plan()`
  retroactively, which may compute differently today than whenever Q1/Q3 were originally
  planned?) — a real design decision with no clean default, unlike Shape 1's trivial backfill.
- **"1 kế hoạch/năm, chia 4 quý" under Shape 2**: realized as literally as possible — ONE row,
  ONE version, 4 quarters as sub-keys. But because approval is forced atomic (see above), "sửa
  Q2 sau khi Q1 đã chốt" cannot mean "Q1 stays approved, Q2 goes back to draft" — the two live
  options under Shape 2 specifically are: (i) refuse the edit outright once the year is
  approved, tenant must explicitly "re-open" the whole year first, or (ii) allow it, but the
  ENTIRE year (all 4 quarters, including Q1's byte-for-byte-unchanged sub-payload) reverts to
  `'pending'` as a new version — Q1's CONTENT doesn't change, but its EFFECTIVE approval status
  does, purely as a side effect of Q2 being edited. This is a real, structural way Q1 "gets
  affected" that Shape 1 simply does not have (under Shape 1, Q1's row/version/approval_status
  is never touched by a Q2 edit, full stop — the only thing that can move is `year_plan.status`,
  which under Shape 1's option (b) doesn't gate anything at all).

#### "Q1 vs Q2" — the question was underspecified last round; 3 separable questions, not 1

Round 2 asked this as a single (a)/(b) binary ("editing Q2 after Q1 is finalized — does Q1's
approval status change, yes/no"). That conflates three genuinely different questions that don't
have to share one answer — laid out separately here, none decided:

1. **Approval-status coupling** (what round 2's (a)/(b) actually meant): if Q1's
   `quarter_plan_version.approval_status = 'approved'` and Q2 is later edited/re-approved, does
   Q1's own approval_status value change as a mechanical side effect? Under Shape 1 the answer is
   structurally "no, never" (separate rows) regardless of policy; under Shape 2 the answer is
   structurally "yes, always, if edits after approval are allowed at all" (one shared status
   column) — this question is actually answered BY the shape choice, not independently of it,
   which round 2 didn't make clear.
2. **Content-freeze after real-world use** (a NEW question, not covered at all last round): once
   Q1's content has actually been consumed downstream (N6 slot-allocated, N7 produced/published
   content for Q1's window) — is Q1 still editable at all, or does real usage lock it regardless
   of approval status? This is a genuinely different mechanism from "approval" — a plan can be
   `approved` yet still purely hypothetical (nothing produced from it yet) or `approved` AND
   already acted on (content shipped). Neither Shape 1 nor Shape 2 as described addresses this on
   their own — it would need its own check (e.g., "does `acp_v2_slots`/`acp_deliver.pieces` have
   any row referencing this quarter's plan already") independent of whichever schema shape is
   picked.
3. **Calendar/temporal lock** (also NEW, not covered last round): if the real current date has
   already moved past Q1 (e.g., today is in Q2 or later), should the UI/API still allow editing
   Q1 at all — purely because it's in the past — regardless of its approval_status or whether
   anything was produced from it? This is a THIRD, independent mechanism (a date comparison, not
   a DB relationship) that could be layered on top of either shape/either approval answer.

These three are not mutually exclusive — a real system could have all three simultaneously (Q1
mechanically independent from Q2's approval_status under Shape 1, AND Q1 additionally locked
once N7 has produced from it, AND additionally locked once the calendar has passed it). Round 2's
question only addressed #1. **Asking directly rather than presenting forced options this time**:
which of #1/#2/#3 does "sửa Q2 sau khi Q1 đã chốt, Q1 có bị ảnh hưởng không" actually mean to
you — one of them, more than one, or something not listed here? This determines real
implementation work (#2 and #3 in particular are entirely new logic under either shape, not a
consequence of the shape choice) — genuinely waiting on your read of this before doing anything
further, not proposing a default.

### Update (post-STOP round 4 → round 5) — decided: Shape 1 + 2 lock conditions + month-vs-quarter
### question + feedback loop, checked against `aa-marketing-v2` BEFORE proposing anything

**Confirmed settled by Nghiep (round 4, not re-litigated here): Shape 1 (`year_plan` additive
wrapper). Locking = BOTH (a) real content already produced (N6/N7 ran) AND (b) calendar has
passed that period, applied together. Editing a period only ever affects LATER periods, never
earlier ones.**

Before proposing month-vs-quarter or feedback-loop design, read `aa-marketing-v2` in full (not
re-guessed from memory) — Nghiep's own reminder: *"chúng ta đang bỏ qua nghiên cứu của chị Thư"*.
Files read this round: `README.md` (193 lines, full), `aamc/planning.py` (343 lines, full —
module D, all of D1-D5), `aamc/learning.py` (119 lines, full — module H + D6), `aamc/models.py`
(`YearPlan`/`MetricSnapshot`/`UnknownEntry`/`Lesson` classes), `aamc/config.py`
(`CONFIDENCE_ATOM_MIN_POSTS`). Also re-grepped the CURRENT AA-CIS-App repo fresh this round for
any real engagement/metrics table (`engagement`, `MetricSnapshot`, `score_post`, `rollup_atoms`,
`ingest_metrics`, `search_console`, `meta_api`) — zero real hits (the handful of filename matches
returned are `destination_shares`/similar unrelated substrings, confirmed by reading each).

#### Q1 answer — cadence: the research already answers this, and it matches what's already built

`aamc/planning.py`'s own module map (its docstring, line 4): **"D1 runway_map (DET) · D2
derive_yearly · D3 plan_quarter · D4 parse_brief_sentence (Mode B) · D5 allocate_month (DET
allocator) · D7 campaign_overlay."** D3 (`plan_quarter`) selects TRIPS/big-rocks per QUARTER —
this is exactly what `services/acp_planning/quarter.py::compute_quarter_plan()` already is (a
direct port, confirmed by its own docstring: "Ported from aamc/planning.py's plan_quarter()/D3").
D5 (`allocate_month`) allocates ATOMS-TO-SLOTS per MONTH, reading eligibility/cooldown/weight per
atom — exactly what `services/acp_planning/allocator.py::compute_slot_grid()` already is (same
docstring lineage, D5). **There is no month-grained trip-selection tier and no quarter-grained
slot-allocation tier anywhere in the reference design** — the two-tier split (quarter = resource
allocation frame, month = the actual calendar/atom-lock granularity) is not a new idea to invent
for AA-448, it is exactly the architecture already ported into this repo since AA-301. This
directly confirms Nghiep's own round-4 hunch ("quý vẫn là khung phân bổ tài nguyên lớn... trong
khi tháng là nơi thực sự khoá/mở/điều chỉnh") as the reference design's own answer, not a guess.

**Practical consequence**: the 2 lock conditions Nghiep confirmed (real content produced + past
calendar) attach naturally to the MONTH artifact (`SlotGrid`/`acp_shared.acp_v2_runs`/
`acp_v2_slots` — these already exist at month grain, `acp_v2_runs` already has real
`tenant_id, year, month, week, status` columns per migration 096/103) — `compute_quarter_plan()`
itself does not need lock logic added to IT; only the month-level artifact/endpoints do. Whether
that means a NEW column on the existing `acp_v2_runs` table, or a separate new lock-state
mechanism, is still open — not decided here, flagged in the open questions below since it is
itself a real schema question (same class as the Shape 1 discussion, needs its own confirmation
before writing a migration).

#### Q2 answer — feedback loop: real, in the reference design, NOT a new invention — but narrower
#### than "xem phản ứng thật → điều chỉnh kế hoạch quý" might suggest

**Yes, it exists — Module H (`aamc/learning.py`), full docstring: "H2 score · H3 lesson_update ·
H4 adjust (confidence-gated) · H5 report_render. D6 log_unknown."** This directly validates
Nghiep's instinct — this is a real, designed part of the original system, not something invented
this round. But reading the actual code (not just the concept) shows the mechanism is narrower
than "phản hồi → sửa lại kế hoạch quý":

- **H2 `score_post(ws, piece_id, day, values)`** — records one raw metric snapshot PER PUBLISHED
  PIECE (`scope="post"`, keyed by `piece_id`). Requires a real published piece to exist.
- **H4's actual mechanism is `rollup_atoms()`** — NOT a quarter/trip re-selection. It recomputes
  ONLY `atom.weight` (magnitude-capped 0.25-2.0), and ONLY once an atom has been used in
  `CONFIDENCE_ATOM_MIN_POSTS = 3` or more posts (`aamc/config.py:102`) — "below threshold: log
  the observation, don't act." That adjusted weight then feeds into the NEXT month's
  `allocate_month()` (D5) atom-eligibility scoring (`w = a.weight * (1.5 if starred...) *
  distinctiveness_multiplier` — the exact same formula shape
  `services/acp_planning/allocator.py::_eligible_atoms()` already has today, `a.weight` is
  already a live input to it). **The reference design's feedback loop never touches
  `QuarterPlan`/`plan_quarter()`/`compute_quarter_plan()` at all — it only adjusts which ATOMS
  win future MONTHLY slots**, via a field (`atom.weight`) that already exists on `AtomRecord` and
  is already read by the allocator today, just never written to by anything yet.
- **H3 (`lesson_update`/`lesson_summary`) is qualitative**, not numeric — free-text notes
  re-injected into future LLM prompt context, not a scoring mechanism.
- **H5 (`report_render`) is a report only** — "what shipped" + "what we couldn't say," no
  automatic action.
- **The reference design's PRIMARY real feedback mechanism is actually the PRE-publish veto loop
  (Module G2, `aamc/delivery.py`)** — the agency reviews the weekly packet within a 48-hour veto
  window BEFORE anything ships; those vetoes become "Decisions"/"lessons," and 3 same-pattern
  vetoes trigger a generalization prompt ("4 vetoed posts mention homestays — retire those
  atoms?"). This is human review of DRAFT content, not real post-publish engagement data — a
  materially different, and much cheaper-to-build, kind of "feedback" than what H2/H4 need.
  Confirmed this already has a real analog in the current codebase's `trust_ramp.py` (AA-365,
  already ported — a 3-state `propose_only → approve_to_publish → veto_window_auto` ramp,
  AA-440 already documented it as closer to A4 Cross-Tenant Oversight than a hard gate) — but
  that module is about PUBLISH GATING (Gate C / A4 territory), a different concern from T7's
  quarter/month planning, not something this task should fold in.
- **Even the reference build's own H1 (`ingest_metrics`) was never a real live connector.** Its
  full docstring: *"H1 ingest_metrics is a connector surface: Search Console / Meta APIs land
  here; metric snapshots can also be entered manually for now."* No actual Search
  Console/Meta API integration exists anywhere in `aa-marketing-v2`'s code — manual entry was
  always the accepted starting point, by the original design's own admission, not a shortcut
  AA-448 would be inventing.

#### Q3 answer — current data availability, checked fresh this round

Confirmed by direct grep (not memory): **zero tables/columns in the current AA-CIS-App schema
store real post-publish engagement of any kind** (likes/shares/clicks/Search Console/Meta data —
none exist). T11 (Publish/Distribute) is confirmed still not built (per AA-447-01's audit,
re-cited not re-verified this round — `deliver_packet()` only flips `packets.status='delivered'`,
no social API integration, grepped 0 hits repo-wide). **One nuance worth surfacing, not assumed**:
T9 (Final Content Write) DOES already produce real content rows —
`acp_deliver.pieces` has 135 real rows (10 `status='passed'`), per this repo's own CLAUDE.md — so
a real `piece_id` to attach a manually-entered metric to already exists for SOME content, even
though nothing auto-publishes it anywhere yet. Whether that means "a human could manually
copy-paste T9's content somewhere themselves today and then manually report back engagement
numbers against that real `piece_id`" is a workflow question outside what the code can answer —
flagged as a real option, not assumed to be the intended use.

#### Naming collision worth flagging (not a Shape 1 re-litigation — Shape 1 stays chosen)

The reference design already has something LITERALLY called `YearPlan` (`aamc/models.py:208`) —
but it means something completely different from Shape 1's `acp_shared.year_plan` (a grouping/FK
wrapper around 4 `quarter_plan` rows, per round 3's design). The reference `YearPlan` is a
once-per-year, LLM-assisted STRATEGY document — `personas`, `excluded_archetypes`, `pillars`
(content-pillar shares derived from atom-type distribution), `channel_roles`, `posture_options` —
and `allocate_month()` (D5) reads it ONLY to label each slot with a rotating pillar tag
(`pillars[slot_n % len(pillars)]`), not for any approval/gating/grouping purpose. **There is no
parent-child or approval coupling between the reference's `YearPlan` and `QuarterPlan` at all** —
they are two unrelated artifacts that happen to both exist "once per year." This means Shape 1's
`year_plan` table (already decided, staying as-is) and the reference's `YearPlan` concept are
NOT the same thing despite the name collision — flagging this now so a future session porting D2
(`derive_yearly` — personas/pillars/posture) doesn't reuse the `year_plan` table name for a
second, unrelated purpose. Not proposing to port D2 in this task (out of scope, not asked for) —
just naming the collision before it causes confusion later.

#### Scope-size flag (per Nghiep's own explicit ask to raise this if seen)

The task started as "rewrite T7" (one tenant-facing quarter/month planning screen). With Shape 1
+ month-level locking + a feedback loop, the real scope now touches: (1) the new `year_plan`
table (round 3, confirmed), (2) a new month-level lock-state mechanism (this round, not yet
designed — see open question below), (3) a new metrics-snapshot-equivalent table +
`atom.weight`-adjustment logic (Module H's `rollup_atoms()` port) if the feedback loop is meant
to be real code and not just a stubbed data model. That is now closer to "T7 + a meaningful slice
of the reference's Module H" in one branch/PR, not a single self-contained page. Raising this
because Nghiep asked me to if I saw real risk — not un-deciding "gộp luôn" myself, and will
proceed with whatever Nghiep confirms either way.

#### Open questions — trying to bundle everything remaining into this one round

1. **Month-lock mechanism**: extend the existing `acp_shared.acp_v2_runs` table (already
   tenant/year/month/week-grained, migration 096/103) with a lock-state column, or a new
   separate table? (Same class of "real schema change, confirm before writing" as Shape 1/2 was —
   not picking unilaterally.)
2. **Feedback loop scope for THIS task, given Q2's answer above**: given zero real engagement
   data exists and even the reference build never had a live connector either — build (a) the
   data model shell only (a metrics-snapshot-equivalent table + a manual-entry endpoint, atom-
   weight adjustment logic wired but inert until real snapshots exist — matches the reference's
   own "H1 stub, manual entry accepted" precedent), or (b) full atom-weight rollup logic
   (`rollup_atoms()`-equivalent) built and tested against manually-entered data now, or (c)
   something narrower/different than both? And: is "a human manually posts T9 content somewhere
   themselves, then manually reports engagement back against that real `piece_id`" the intended
   workflow, or is real automatic ingestion (Search Console/Meta) actually expected before this
   is useful at all?
3. **Given the scope-size flag above**: still one PR/branch, or split (e.g., year_plan + month
   lock in this branch, feedback loop as its own follow-up ticket)? Nghiep already said "gộp
   luôn" once — asking again only because the concrete shape (2 new tables + adjustment logic,
   not just a UI) is now clearer than it was when that call was first made; happy to proceed
   either way once confirmed.

Nothing implemented this round — analysis only, per instruction not to pick schema specifics
without presenting first.

### Update (round 6) — FINAL decisions, implementation starts now

All open architecture questions are closed as of this round. This is the source of truth for
what gets built — later sections below record what was actually implemented against it.

**1. Schema — Shape 1, unchanged from round 4/5.**

**2. Cadence — unchanged from round 5's research-grounded answer.** Quarter = trip/big-rock
selection (D3/`quarter.py`), month = atom-to-slot allocation (D5/`allocator.py`). No new tier.

**3. Locking — corrected from round 4's wording (round 4 said "only affects later periods,"
which under-specified what happens to the period BEING edited):**
- A week is **hard-locked** (immutable) if EITHER real content was already produced for it
  (N6/N7 ran) OR it is chronologically in the past. Locked weeks never change regardless of
  what happens to later weeks/quarters.
- The **currently-being-edited period** — editing takes effect immediately, but only from the
  real point in time the edit happens forward; already-past/already-produced weeks within that
  same quarter are NOT retroactively recomputed.
- **Later (future, not-yet-started) quarters** may naturally shift as a consequence (they were
  never locked to begin with) — no special handling needed beyond "recompute uses whatever the
  current inputs are when it runs."
- **Implementation shape chosen** (my own engineering call, per "dùng cách bạn thấy hợp lý
  nhất"): **no new schema for lock state.** Lock status is entirely a READ-time computation
  against data that already exists — "produced" = a row exists in `acp_shared.acp_v2_runs` for
  that `(tenant_id, year, month, week)` (already real-time-populated by N7's existing trigger,
  untouched by this task); "past" = `date.today()` has moved past that MONTH (month-grain
  calendar cutoff, not synthetic week-to-real-date mapping — see "Should know" below for why
  week-grain calendar cutoff was NOT attempted). This directly answers round 5's open question 1
  ("mở rộng `acp_v2_runs` hay bảng riêng") — neither: it's a pure read, no write needed at all.
- **Scope boundary, stated plainly**: T7 itself (this task) only ever writes to `quarter_plan`/
  `quarter_plan_version` — it does not persist `acp_v2_slots` rows itself (that stays N7's job,
  `allocate_and_persist_week()`/`admin_produce.py`'s `/run` trigger, both untouched). T7's lock
  check therefore does two things and no more: (a) exposes lock status for display, (b) refuses
  to finalize/re-approve a quarter plan only when the ENTIRE quarter is locked (every week of
  all 3 months already produced-or-past) — it does NOT, and structurally cannot from inside this
  task's scope, guarantee that a LATER re-trigger of N7 for a partially-locked quarter won't
  attempt to reconcile an old vs. new trip selection for the same already-produced week — that
  reconciliation logic lives inside `allocate_and_persist_week()`/`persist_slot_grid()`
  (`_deterministic_slot_id()` hashes in `trip_id`, so a changed trip selection for an
  already-produced week would generate a NEW, non-colliding `slot_id` rather than being blocked
  by the existing `ON CONFLICT (slot_id) DO NOTHING` idempotency guard) — a real, PRE-EXISTING
  gap in N7's own persist layer that predates this task and is not something T7 can close without
  touching that layer, which every round of this task has been told to leave alone. Flagged
  honestly rather than silently assumed solved — the quarter-level lock check materially reduces
  how often this could ever be hit (blocks the fully-locked case outright) but does not
  eliminate it for a still-open, partially-produced quarter. Worth its own follow-up ticket
  against N7, not this one.

**4. Feedback loop — explicitly a NEW extension beyond `aamc`'s Module H, not a restoration.**
Documented as such everywhere it's implemented (matching the T8 §0.5 "formula fit" precedent
Nghiep cited) — `rollup_atoms()`'s CONFIDENCE_ATOM_MIN_POSTS=3 confidence-gate mechanism is kept
verbatim (that part IS the original design), everything downstream of it (the per-post scoring
formula, since travel content has no `capture_rate`/`engaged_time` field anywhere in this app;
the trip-level reallocation suggestion, which `aamc` never had at all — H4 only ever touched
`atom.weight`, never `QuarterPlan`) is new, built and labeled as new.

- **Manual metric entry** (new table, migration — see below): `POST /v1/planning/metrics`,
  `{piece_id, reach, engagement, clicks}` — matches `aamc`'s own H1 precedent ("manual entry
  accepted, no live connector") rather than waiting on a Search Console/Meta integration that
  doesn't exist in either the reference or this repo.
- **Atom weight rollup** (new, `rollup_atom_weights()`): confidence-gated exactly like `aamc`
  (>=3 posts using that atom carry a metric snapshot before its weight moves at all).
  Per-post score formula is NEW (not in `aamc`, which used a travel-content-inapplicable
  `capture_rate`/`engaged_time`): `engagement / max(reach, 1)` (a plain engagement RATE),
  averaged per atom, magnitude-capped into `[0.25, 2.0]` exactly like `aamc`'s own bound.
- **`compute_quarter_plan()` gains a 5th weighted term**, done ONCE now (per Nghiep's explicit
  instruction not to add dfs_relevance then redo the formula a second time for this) —
  `QUARTER_SCORE_WEIGHTS` becomes `{runway_fit: 0.30, richness: 0.20, distinctiveness: 0.20,
  dfs_relevance: 0.15, engagement_adjustment: 0.15}` (sums to 1.0). **No new function parameter
  needed** — `engagement_adjustment` is derived directly from the SAME `atoms_by_trip` dict the
  function already receives (`atom.weight`, already fetched by `tenant_pool.py`, already read by
  N6's allocator — this is the first time N5/`compute_quarter_plan()` reads it too):
  `engagement_component(trip) = min(1.0, avg(atom.weight for atom in this trip's atoms) / 2.0)`
  — this normalizes `aamc`'s own `[0.25, 2.0]` weight range so "weight=1.0" (no feedback data
  yet, or genuinely neutral) maps to exactly `0.5`, matching the SAME "MED"/no-signal midpoint
  convention `distinctiveness`/`dfs_relevance` already use (`SIGNAL_SCORE_MAP["MED"] = 0.5`) — a
  trip with zero adjusted atoms scores neither better nor worse than before this feature existed.
- **`suggest_trip_reallocation()` / `confirm_trip_reallocation()`** — mirrors
  `trust_ramp.py::suggest_ramp_transition()`/`confirm_ramp_transition()`'s exact shape/naming,
  per Nghiep's own suggestion, kept as named (no better name found): `suggest_...()` is pure-ish
  (computes a fresh `compute_quarter_plan()` for the target quarter using current, feedback-
  adjusted atom weights, diffs it against the tenant's last saved plan for that quarter if any,
  returns the diff — never writes); `confirm_...()` always writes an `acp_shared.audit_log` entry
  (reusing the SAME table `trust_ramp.py` already uses, per that module's own "no new logging
  shape" precedent) recording the suggestion + the tenant's accept/reject, and on accept calls
  the SAME `save_quarter_plan_version()`+`approve_quarter_plan_version()` path T7's own finalize
  endpoint uses (Gate B Option A) — a reallocation suggestion, once accepted, becomes a normal
  new quarter plan version, not a special different kind of object.

**5. One PR — confirmed, staying that way unless a new risk surfaces (none has, beyond what's
already flagged above).**

**Build order** (Nghiep's own suggestion, followed as-is): migration (Shape 1 + metrics table) →
Gate B Option A (exception wording + finalize/read endpoints, year_plan auto-link) → month/week
lock (read-only, no schema) → feedback loop (metric entry → atom-weight rollup →
suggest/confirm reallocation, including the 5-weight `compute_quarter_plan()` change) →
frontend.

## Changed

### Round 1 (dfs_relevance + tenant-scoped fetch + preview endpoint)

- New: `services/acp_shared/dfs_relevance.py`, `services/acp_planning/tenant_pool.py`,
  `api/routers/v1_planning.py` (preview endpoint only at this point).
- Edited: `services/acp_planning/quarter.py` (`compute_quarter_plan()`'s new 4th weight +
  `_score_reason()`'s new 4th arg), `services/acp_planning/models.py` (`TripScore.
  dfs_relevance_score`), `services/acp_planning/constants.py` (`SIGNAL_SCORE_MAP`,
  `QUARTER_SCORE_WEIGHTS`), `api/main.py` (router registration), `tests/unit/
  test_aa301_quarter.py` (`_score_reason()` signature).
- New tests: `test_aa448_dfs_relevance.py` (13), `test_aa448_tenant_pool.py` (7),
  `test_aa448_v1_planning.py` (5, preview only).

### Round 6 (Shape 1, Gate B Option A, month/week locking, feedback loop)

- **New migration**: `api/migrations/112_acp_shared_year_plan_and_metrics.sql` —
  `acp_shared.year_plan` (Shape 1) + `acp_shared.quarter_plan.year_plan_id` FK +
  `acp_shared.content_metric_snapshot` (feedback loop manual entry). **NOT applied to any real
  database this session** — no AWS/RDS access from this sandboxed environment (same class of
  limitation AA-445-02's own notes flagged: "requires cis-start, a live-session action"). The
  migration file itself was written, reviewed against this repo's own migration conventions
  (numbered, self-registers into `shared.schema_versions`, `IF NOT EXISTS` guards), but never
  run — applying it is a real next step for a live session with AWS access.
- **New**: `services/acp_planning/lock_status.py` (week/month lock check, pure read, no new
  schema), `services/acp_shared/content_metrics.py` (manual metric entry + confidence-gated
  atom-weight rollup), `services/acp_planning/trip_reallocation.py` (suggest/confirm, mirrors
  `trust_ramp.py`'s exact shape).
- **Edited**: `services/acp_planning/quarter.py` (`save_quarter_plan_version()` now also
  ensures/links a `year_plan` row; `compute_quarter_plan()`/`_score_reason()` gained the 5th
  `engagement_adjustment` term), `services/acp_planning/models.py`
  (`TripScore.engagement_adjustment_score`, `QuarterPlanNotApprovedError`'s docstring),
  `services/acp_planning/constants.py` (`QUARTER_SCORE_WEIGHTS` re-derived to 5 terms,
  `CONFIDENCE_ATOM_MIN_POSTS`/`ATOM_WEIGHT_MIN`/`ATOM_WEIGHT_MAX`/`ENGAGEMENT_RATE_BASELINE`
  added), `services/acp_planning/allocator.py` (2 exception message wording changes only — the
  check/type/trigger condition are unchanged), `api/routers/v1_planning.py` (finalize/read/
  slot-grid/metrics/rollup/suggest/confirm endpoints added), `api/routers/admin.py` (`/admin/
  quarter-plan/pending` and `/admin/quarter-plan/{version_id}/approve` retired; 3 now-unused
  imports removed).
- **Frontend**: `frontend/app/(tenant)/portal/t7-planning/page.tsx` (new route),
  `frontend/app/(tenant)/portal/_components/PlanningTab.tsx` (new — preview/finalize table,
  feedback metric-entry form + rollup trigger, reallocation suggestion panel), `Sidebar.tsx`
  (new nav entry after Atom Curation, before Marketplace, per the STEP0 investigation's
  proposal), `layout.tsx` (`BREADCRUMBS` entry).
- **New tests**: `test_aa448_lock_status.py` (8), `test_aa448_content_metrics.py` (13),
  `test_aa448_trip_reallocation.py` (6), `test_aa448_v1_planning.py` extended to 12 (finalize/
  get/metrics/reallocation wiring added, preview tests fixed for the new lock-status DB call).
  `test_aa320_quarter_plan_persist.py`'s `FakeDB`/`FakeConn` extended to understand the new
  `year_plan` insert/select (existing tests were failing after `save_quarter_plan_version()`'s
  edit until this fix — see "Should know").

## Tradeoffs

- See Decision 3 (additive vs. replace, dfs_relevance) and Decision 5 (owner_scope-only vs. IN
  ('platform', tenant_id)) in round 1 — both chosen with reasoning documented rather than
  silently picked, neither required stopping to ask.
- Round 6: `confirm_trip_reallocation()` re-runs `suggest_trip_reallocation()` internally instead
  of accepting a cached suggestion payload from the client — an extra DB round-trip, deliberately
  accepted for a low-frequency (quarterly) action in exchange for never applying a stale
  suggestion (see `trip_reallocation.py`'s own docstring).
- Round 6: month/week lock status uses MONTH-grain calendar cutoff (not week-grain) specifically
  because no code anywhere in this repo maps `compute_slot_grid()`'s `week` (1-4, a round-robin
  label, not tied to real calendar days) to an actual date range — inventing that mapping was
  explicitly out of scope ("không phát minh cách tính tuần mới"). The "produced" check (real
  `acp_v2_runs` rows) still gives real week-level precision for whichever weeks N7 actually ran.
- Round 6: `ENGAGEMENT_RATE_BASELINE` (0.05) and the plain `engagement / reach` per-post scoring
  formula are self-chosen, uncalibrated against real data — same class of caveat as
  `dfs_relevance`'s own thresholds, flagged the same way (named constant, not hardcoded inline).

## Live Verify (post-round-6, real AWS access)

Nghiep re-authenticated `aa365-admin` MFA mid-session so this could run for real — same
S3-mediated ECS exec pattern every prior live-verify in this repo uses (AA-431/AA-444/AA-445-02).
Pre-merge, so no real deployed HTTP endpoint exists yet for these new routes — followed the same
established pre-merge precedent AA-431 set: overwrite the changed `.py` files directly onto the
running `aa-cis-dev-api` container's disk (`/app`, via `tar` upload — does NOT restart uvicorn,
does NOT affect real traffic already being served by the old in-memory code), then run a fresh
`python3` process that imports the just-written modules and calls the real router functions
directly (real asyncpg pool, real Postgres, no mocks) — functionally equivalent to a real HTTP
call through this router's own dependency-free calling convention (`fn(body, request, tenant)`),
just skipping the actual TCP/ASGI layer since that requires a real deploy. True end-to-end HTTP-
through-API-Gateway verification is a post-merge, post-deploy step for whoever merges this — same
caveat AA-431's own notes already state for this exact situation.

### 1. Migration 112 applied + schema confirmed

ECS (`aa-cis-dev-cluster`/`aa-cis-dev-api`, task def `:127`) and RDS (`aa-cis-dev-db`) both
confirmed running (`desired=1/running=1`/`available`) before starting — not started by this
session. Ran migration 112's SQL via `asyncpg.execute()` (checked `shared.schema_versions` for
`'112'` first, idempotent). Result: `{"status": "applied"}`.

Schema confirmed live via `information_schema.columns`/`pg_constraint` (not assumed from the
file):

| Table | Confirmed live |
|---|---|
| `acp_shared.year_plan` | `year_plan_id` (uuid, PK), `tenant_id` (uuid, NOT NULL, FK → `shared.tenants`), `year` (integer, NOT NULL), `created_at` (timestamptz) — `UNIQUE (tenant_id, year)` |
| `acp_shared.quarter_plan.year_plan_id` | uuid, nullable — FK column present |
| `acp_shared.content_metric_snapshot` | all 9 columns present with correct types; FKs confirmed to `shared.tenants(tenant_id)` and `acp_deliver.pieces(piece_id)` |
| `shared.schema_versions` | `version='112'` row present, `applied_at=2026-08-23T14:30:32Z` |

### 2-3. Live function-level verify — real tenant, real data, all 7 checks pass

Tenant: `test-n1-flow` (`6fbaf284-e3cd-4b4b-b53b-c9a04e8fae8e`), real pre-existing data — 1
`tenant_tour_versions` row, 8 real `owner_scope`-scoped atoms (tour `4bf83a2c-...`), all
`weight=1.0` before this run. A comprehensive Python script ran all of the following in one real
DB session, with full cleanup + an independent re-check confirming the tenant was left exactly
as found (see "Cleanup" below) — chosen over piecemeal manual curl-equivalents because the week-
preservation and feedback-loop checks genuinely need multi-step real state (seeded slots/pieces/
metrics), same shape as AA-431's own "one comprehensive verify script" choice.

**A real bug was found and fixed during this pass** (not a pre-existing issue — introduced by
this task's own new code, caught exactly because this was a REAL DB call, not a mock): both
`finalize_quarter_plan()` and `confirm_trip_reallocation()`'s accept path passed a `source` value
(`'tenant_self_service'`/`'feedback_reallocation'`) that `quarter_plan_version.source`'s CHECK
constraint (migration 092, `IN ('standard','override')`) rejects —
`CheckViolationError: ... quarter_plan_version_source_check`. Fixed using the existing allowed
vocabulary (`'standard'` for tenant finalize, `'override'` for a feedback-reallocation accept) —
see the "fix:" commit. Re-verified clean after the fix; all 7 checks below are from the
POST-FIX run.

| # | Check | Live result |
|---|---|---|
| 1 | Preview reads from tenant's own data, not the platform catalog | `trip_pool_size=1`, returned trip_id = the tenant's real tour `4bf83a2c-...` (not any of the 763 platform-catalog trips) |
| 2 | Finalize auto-approves (Gate B Option A), no human step | `approval_status='approved'`, `approved_by='tenant:6fbaf284-...'` set immediately by the finalize call itself; `year_plan_id` correctly linked |
| 3 | Lock refusal on a fully-locked quarter, clear error (not a generic 500) | `finalize` on Q1 2020 (fully past) → `HTTPException(409)`, detail: `"Q1 2020 is fully locked (every week already produced or in the past) — nothing left to plan."` |
| 4 | Editing a partially-locked quarter is allowed; already-produced weeks are untouched | Seeded a real `acp_v2_runs`+`acp_v2_slots` row for (2031, month 1, week 1) with `status='produced'` and a distinctive `topic_hint`. Confirmed the quarter (11 other weeks still open) is NOT fully locked → re-`finalize()` on it succeeded. Re-read the seeded slot row afterward: **payload byte-for-byte identical** to before — T7's finalize never touches `acp_v2_slots` at all, confirming the design boundary documented above holds in practice, not just by code inspection |
| 5 | Feedback rollup: low engagement → real `tour_atoms.weight` decrease | Seeded 3 real pieces (via real `acp_v2_runs`/`acp_v2_slots`/`acp_deliver.pieces` rows, atom `atom_6d25e9c335`), recorded 3 low-engagement snapshots (`reach=1000, engagement=1` → rate 0.001, well under the 0.05 baseline) via `record_metric_snapshot()`, ran `rollup_atom_weights()`: **`weight` 1.0 → 0.951**, atom present in the returned `moved` dict — confidence gate (exactly 3 posts) correctly cleared it |
| 6 | Adjusted weight reflected in NEXT quarter's `compute_quarter_plan()` scoring | Re-ran `preview_quarter_plan()` for Q2 2031: `engagement_adjustment_score=0.497` for the affected trip — matches the math exactly (1 of the tour's 8 atoms adjusted: `(0.951 + 7×1.0)/8 = 0.9939`, `/2.0 = 0.497`), confirming the averaging-across-all-of-a-trip's-atoms behavior, not just a single-atom shortcut |
| 7 | `suggest`/`confirm` reallocation — suggest never writes, reject still logs, accept applies via Gate B Option A | `suggest_trip_reallocation()`: 0 `quarter_plan` rows existed for the target quarter before OR after calling it. `confirm_trip_reallocation(accept=False)`: `accepted=False` returned, `acp_shared.audit_log` still gained 1 row (never-silently framing confirmed). `confirm_trip_reallocation(accept=True)`: `accepted=True`, real `version_id` returned, a real `quarter_plan` row now exists (via the SAME `save_quarter_plan_version()`→`approve_quarter_plan_version()` path finalize uses) |

### Cleanup — tenant left exactly as found

All seeded rows deleted in the same script's `finally` block (3 metric snapshots, 3 pieces, 4
`acp_v2_slots`, 4 `acp_v2_runs`, 1 legacy `acp_runs` row, `tour_atoms.weight` restored to `1.0`,
2 `quarter_plan_version` rows + 2 `quarter_plan` rows + 1 `year_plan` row + 2 `audit_log` rows
from THIS session's own test finalizes). **Independent re-check afterward** (separate script,
not reusing any state from the verify script): `metric_snapshots=0`, `verify_pieces=0`,
`verify_slots=0`, `audit_log_reallocation=0`, `all_atom_weights_are_1.0=True` (all 8 real atoms).
One exception, correctly left alone: `quarter_plans=1` — inspected it directly, found a REAL
pre-existing row (`year=2026, quarter=3, created_at=2026-08-13`, 10 days before this session,
not created by this task) — not deleted, since this session didn't create it (per the standing
rule: don't delete what you didn't create and can't fully explain).

## Post-merge / post-deploy record

Per Nghiep's explicit instruction ("ci green thì merge luôn, theo dõi deploy, verify, check def
task, báo cáo") — merged rather than left as a PR for separate review, deviating from this
task's own earlier-stated "PR only, Claude Chat merges after review" default. Noted here for
the record, not glossed over.

- **PR #200** (`feature/aa-448-build-t7-planning` → `main`): all 5 required CI checks green
  (Lint, Security Audit, Unit Tests, Integration Tests, Docker Build Check, each run twice) +
  Vercel preview — squash-merged. Contains migration 112; per this repo's own stated convention
  a migration-carrying PR should get a manual look regardless of CI — merged anyway per Nghiep's
  explicit instruction this round, flagged here rather than silently following the general
  policy over the specific instruction actually given.
- **Deploy Dev run 32654612013** (triggered by the #200 merge): all 4 jobs green (Build/Push
  ECR, Deploy Frontend to Vercel, Deploy Lambda Functions, Deploy to ECS Dev incl. the
  workflow's own smoke test). New task def **`aa-cis-dev-api:128`**, service `1/1` running,
  single `PRIMARY` deployment (clean rollout, no stuck old deployment).
- **Real end-to-end HTTP verify, post-deploy** (first time this task's endpoints were reachable
  via the actual domain, not just direct function calls) — minted a real tenant JWT for
  `test-n1-flow` in-container (`api.routers.auth._create_jwt`, same shortcut AA-432's own notes
  used, no API-key login needed) and called `https://api-cis.lumiguides.it.com` directly:
  - `POST /v1/planning/quarter-plan/preview` → **200**, real tenant data (tour "Southern Laos:
    Plateau, Temples & the Four Thousand Islands — 5 Days"), all 5 score components present.
  - `POST /v1/planning/quarter-plan` (finalize) → **200**, `version_id` returned.
  - `GET /v1/planning/quarter-plan?year=&quarter=` → **200**, `approved: true,
    approved_by: "tenant:6fbaf284-..."` — Gate B Option A confirmed via real HTTP, not just the
    pre-merge function-level pass.
  - No `Authorization` header → **401** `{"detail":"Not authenticated"}` — auth boundary intact.
  - **New finding from this real-HTTP pass, NOT caught by the pre-merge function-level verify**:
    the `finalize` response's OWN payload showed `plan.approved: false` even though the DB was
    already `approved: true` (confirmed by the immediately-following `GET`) — a real, if minor,
    inconsistency the pre-merge test harness's own request/response shape didn't happen to
    surface. Root cause: `approve_quarter_plan_version()` only writes the DB row, never mutates
    the in-memory `QuarterPlan` object the handler had already built. Fixed in **PR #201**
    (`fix/aa-448-finalize-approved-response`) — mirrors the existing in-memory
    `approve_quarter_plan()` helper's own pattern (`plan.approved = True` before returning).
    Regression test added.
- **PR #201**: all CI green — squash-merged. **Deploy Dev run 32655384683**: all jobs green,
  smoke test passed. New task def **`aa-cis-dev-api:129`**, `1/1` running.
- **Re-verified live against `:129`** — same finalize call, now returns `plan.approved: true`
  immediately in its own response (`approved_by: "tenant:6fbaf284-..."`), no follow-up GET
  needed to see the correct state.
- **Cleanup**: every quarter/year created by real HTTP calls this round (2032 Q1, 2033 Q1) —
  `quarter_plan_version` unlinked+deleted, `quarter_plan` deleted, `year_plan` deleted.
  Independently re-confirmed `0` remaining rows for tenant `test-n1-flow` across every test year
  touched this entire task (2020, 2031, 2032, 2033) — the tenant is back to exactly its
  pre-session state, real pre-existing data (8 atoms, 1 tenant_tour_version, the 1 unrelated
  13/08/2026 quarter_plan row) untouched throughout.

**Final state**: `main` at `bbb2871` (PR #201's squash commit). ECS `aa-cis-dev-api:129` live.
Both PRs' branches (`feature/aa-448-build-t7-planning`, `fix/aa-448-finalize-approved-response`)
kept (not deleted) per this session's own merge commands (`--delete-branch=false`).

## Should know

- `services/acp_planning/tenant_pool.py` reuses `runway.py`'s `_row_to_trip()` and `quarter.py`'s
  `_row_to_atom()` (both underscore-prefixed "private" functions) directly rather than
  duplicating their row-shape parsing — deliberate, since the new queries return the exact same
  column names/types those functions already expect.
- The old `fetch_trips()`/`fetch_atoms_by_trip()`/`runway_map()`/`plan_quarter()`/
  `allocate_month()` are UNTOUCHED and still used by `admin_atoms.py`'s preview-slotgrid +
  `admin_produce.py`'s real N7 trigger — do not "clean these up" as apparently-dead code in a
  future session without re-checking those two call sites first.
- **`save_quarter_plan_version()`'s edit (year_plan linking) broke `test_aa320_quarter_plan_
  persist.py`'s hand-rolled `FakeDB`/`FakeConn`** (a query-substring-matching fake, not a strict
  call-sequence mock) — fixed by extending the fake to understand the 2 new queries. If that
  function's persist SQL changes again, that fake needs the same treatment; it does not fail
  loudly in an obviously-related way (raises a generic `AssertionError: Unhandled ... query`).
- **Static verification** (sandboxed, no AWS access): `pytest tests/unit/ -q` → 1446 passed, 1
  skipped (same pre-existing unrelated skip prior sessions already documented), 0 failed;
  `flake8 --max-line-length=120` clean on every changed/new Python file; `npx tsc --noEmit`
  clean (0 errors) on the whole frontend; `npx eslint` clean on every changed/new frontend file
  (the 1 remaining `no-explicit-any` in `layout.tsx` is pre-existing, confirmed by running the
  same lint against unmodified `main`).
- **Live verification (real AWS access, same session, after Nghiep re-authenticated MFA) —
  full evidence in the new "Live Verify" section below**, including one real bug this task's own
  code introduced, found and fixed during that pass (`quarter_plan_version.source` CHECK
  violation).
