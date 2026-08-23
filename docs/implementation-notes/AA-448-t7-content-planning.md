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

## Changed

- New: `services/acp_shared/dfs_relevance.py`, `services/acp_planning/tenant_pool.py`,
  `api/routers/v1_planning.py`.
- Edited: `services/acp_planning/quarter.py` (`compute_quarter_plan()`'s new 4th weight +
  `_score_reason()`'s new 4th arg — both backward-compatible, defaults preserve old behavior for
  every caller that doesn't pass the new data), `services/acp_planning/models.py` (`TripScore.
  dfs_relevance_score`, defaulted for old-payload JSON compat), `services/acp_planning/
  constants.py` (`SIGNAL_SCORE_MAP`, `QUARTER_SCORE_WEIGHTS`), `api/main.py` (router
  registration), `tests/unit/test_aa301_quarter.py` (6 `_score_reason()` calls updated for the
  new signature/weights, 1 new test added for the dfs_relevance dominance case).
- New tests: `tests/unit/test_aa448_dfs_relevance.py` (13), `tests/unit/
  test_aa448_tenant_pool.py` (7), `tests/unit/test_aa448_v1_planning.py` (5).
- **Not yet changed** (blocked on STOP point): `allocator.py`, `admin.py`'s `/admin/
  quarter-plan/*` routes, any frontend file.

## Tradeoffs

- See Decision 3 (additive vs. replace) and Decision 5 (owner_scope-only vs. IN ('platform',
  tenant_id)) above — both chosen with reasoning documented rather than silently picked, per
  this task's own "không tự quyết âm thầm nếu ảnh hưởng đáng kể" instruction, but neither
  required stopping to ask (only the Gate B point did).

## Should know

- `services/acp_planning/tenant_pool.py` reuses `runway.py`'s `_row_to_trip()` and `quarter.py`'s
  `_row_to_atom()` (both underscore-prefixed "private" functions) directly rather than
  duplicating their row-shape parsing — deliberate, since the new queries return the exact same
  column names/types those functions already expect.
- The old `fetch_trips()`/`fetch_atoms_by_trip()`/`runway_map()`/`plan_quarter()`/
  `allocate_month()` are UNTOUCHED and still used by `admin_atoms.py`'s preview-slotgrid +
  `admin_produce.py`'s real N7 trigger — do not "clean these up" as apparently-dead code in a
  future session without re-checking those two call sites first.
