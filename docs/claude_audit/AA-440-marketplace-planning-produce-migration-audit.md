# AA-440 — Audit: Prep for Quarter Plan/Marketplace/Produce&Deliver → Tenant Self-Service

Audit only. No code changed. Branch `feature/aa-440-marketplace-planning-migration`, created
from `main` (not from the AA-438 audit branch — this is a fresh investigation, not a
continuation). Every claim below is backed by `path:line` or a real query
(`information_schema.columns` + `shared.tenants`, S3-mediated ECS exec, `aa-cis-dev-db`, run
22/08/2026). This task does not decide anything or write any code — it maps what's reusable vs.
what needs rework, for whoever builds T7/Marketplace/T8-T10 next.

**Headline: the codebase is unusually well-prepared for this pivot.** Every pure-computation
function in `services/acp_planning/*` already takes `tenant_id` as a required parameter and is
100% reusable as-is. The two things that actually need rework are narrower than "rewrite the
business logic": (1) the two hardcoded **Gate B/Gate C approval checks** that must be removed
per ADR-2026-038 §0.2's new "no gate" principle, and (2) **one real, currently-live
atom-scoping inconsistency** in the quarter-planning atom fetch that the code's own comments
already flag as a temporary hack awaiting exactly this kind of licensing/self-service build.

---

## 1. Quarter Plan / Gate B → T7

### (a) Pure business logic — 100% reusable, already tenant-scoped by design

| Function | File:line | Reusable? |
|---|---|---|
| `compute_runway_map(tenant_id, year, trips, markets)` | `services/acp_planning/runway.py:155-185` | Yes — pure, no DB/LLM, tenant_id is already a required param |
| `compute_quarter_plan(tenant_id, year, quarter, trips, markets, capacity, specials, runway, atoms_by_trip, excludes)` | `services/acp_planning/quarter.py:141-229` | Yes — pure, unit-testable, tenant-scoped |
| `fetch_tenant_planning_config(tenant_id, pool)` | `services/acp_planning/tenant_config.py:36-53` | Yes — already the single per-tenant read path for markets/channels/capacity |
| `runway_map()`/`plan_quarter()` (async DB wrappers) | `runway.py:228-235`, `quarter.py:272-288` | Yes, with one caveat — see §1c |

### (b) Parts tied to "admin manages ALL tenants at once" — must be rewritten/removed for T7

| Part | File:line | Why it must change |
|---|---|---|
| `GET /admin/quarter-plan/pending` — Gate B queue across every tenant | `api/routers/admin.py:1811-1850` | Cross-tenant admin worklist — no equivalent needed once there's no staff approval step |
| `POST /admin/quarter-plan/{version_id}/approve` → `approve_quarter_plan_version()` | `admin.py:1962-1999`, `quarter.py:355-396` | **This IS Gate B** — ADR §0.2 explicitly retires it. The DB write itself (`approval_status='approved'`, `current_version_id` move) is fine as a *concept* ("this is the tenant's current plan"), but the *human-approval* semantics need to go — see §1b below |
| `compute_slot_grid()`'s hardcoded Gate B check | `allocator.py:128-130`: `if not quarter_plan.approved: raise QuarterPlanNotApprovedError("Gate B: quarter plan must be approved by a human (Ms. Thu) before allocation — never auto.")` | Literally names "Ms. Thu" (a human approver) in the exception message — must be removed or repointed at a tenant-scoped auto-approve/no-approve-needed model |
| `allocate_month_from_db()`'s duplicate Gate B check | `allocator.py:279-301`, same error text | Same — this wrapper exists ONLY to enforce Gate B before N6 runs; if Gate B goes away, this wrapper's whole reason to exist changes |

**Concrete rewrite path (not prescribing, just naming the shape):** `save_quarter_plan_version()`
(`quarter.py:310-352`) already always inserts `approval_status='pending'`. The straightforward
change is either (a) a tenant creating their own plan auto-sets `approval_status='approved'`
(no staff step) — the DB shape survives, only the WHO/WHEN of the status flip changes — or (b)
repurpose the `approval_status` column to mean "draft" vs. "current" instead of
"pending-for-staff" vs. "staff-approved". Either way, `quarter_plan`/`quarter_plan_version`'s
schema itself does not need new columns for this (see §1e) — this is a logic/semantics change,
not a schema change.

### (c) A real, currently-live inconsistency this task's code-reading caught

`fetch_trips()` (`runway.py:205-225`) has its own inline comment, dated 13/08/2026 (AA-323
round 6 Phần B), that is **directly on point for this exact migration**:

> "TEMP... every tenant now reads the SAME full platform catalog... instead of filtering `WHERE
> tenant_id = $1`... Live-DB finding this round: that filter meant EVERY non-aa_internal tenant
> saw 0 eligible trips... Nghiep's explicit call: this is still the development stage —
> product/UX quality over licensing gates — so every tenant shares the full catalog until
> Marketplace/N1 licensing (D3/D4, PRD ACP v2) is actually built and wired into trip
> eligibility. **REVISIT WHEN N1 SHIPS**."

That comment is essentially a pre-written pointer to this task. **But the sibling function,
`fetch_atoms_by_trip()` (`quarter.py:232-269`), was NOT given the same relaxation** — it still
filters:
```sql
SELECT ta.atom_id, ... FROM acp_contract.tour_atoms ta
JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = ta.tour_id
WHERE rt.tenant_id = $1 AND NOT ta.deleted AND NOT ta.is_empty_marker
```
`raw_tours.tenant_id` is, per this same comment and per AA-438's own audit, **always
aa_internal** for all 793 rows (no B2B ingestion pipeline writes `raw_tours` rows for any other
tenant). **Confirmed live**: `acp_contract.tour_atoms` has 2551 rows with `owner_scope
='platform'` and only 15 with `owner_scope=<a real tenant UUID>` (from AA-438-04's live query) —
none of those atoms are reachable by `fetch_atoms_by_trip(tenant_id, pool)` for any real B2B
tenant, because the join key it uses (`raw_tours.tenant_id`) never matches a B2B tenant_id at
all.

**Net effect, right now, today**: if a real tenant called `plan_quarter()`, `fetch_trips()`
would correctly show them the full 763-trip catalog (per the deliberate relaxation), but
`fetch_atoms_by_trip()` would return **zero atoms for every single trip** — every `richness`/
`distinctiveness` score in `compute_quarter_plan()` would compute as 0, silently degrading every
trip's score to whatever `runway_fit`/`forced` alone produce. **This is the one real "must
rewrite" item with an obvious, narrow fix**: `fetch_atoms_by_trip()` needs to filter by
`tour_atoms.owner_scope` (matching how T5/T6/`admin_atoms.py`'s `_resolve_atom_owner_scope()`
already do it), not by `raw_tours.tenant_id` — almost certainly `owner_scope IN ('platform',
$1)` so a tenant sees both the shared platform-curated atoms and their own T6-curated ones,
mirroring the `owner_scope=None`-sees-everything / `owner_scope=<tenant>`-sees-own split
`admin_atoms.py` already established (AA-431, confirmed AA-438-04 §9).

### (d) Rate-limit/quota status

- **`posts_per_week`** (`shared.tenants`, migration 099/AA-384) is already the live
  `capacity_posts_per_week` input to `plan_quarter()`/`compute_slot_grid()` — it directly caps
  how many slots a tenant's plan can produce per week (`total_slots = capacity_posts_per_week *
  4`, `allocator.py:138`). **This already IS a real, working, per-tenant content-volume limit,
  set at tenant setup and freely tenant-adjustable since AA-384** — confirmed live, it varies
  per real tenant (1 for most starters, 3-5 for growth/business, not strictly tied to
  `plan_tier` — see the live table in §5).
- **`rate_limit_rpm`** (set at tenant creation from `PLAN_LIMITS[plan_tier]["rpm"]`,
  `admin.py:35-40,129`) is a real, enforced HTTP request-rate limit on `/v1/*` traffic (confirmed
  live in AA-438-04) — but this caps *API call frequency*, not *quarter plans per quarter* or
  *runs per month* specifically.
- **`tours_quota_monthly`/`api_calls_quota_monthly`** (from `shared.v_tenant_monthly_usage`) are
  tracked and displayed (Settings, Tenant Details, billing usage %) but — grepped every
  reference to `tours_quota_monthly`/`tours_overage`/`quota_tours_pct` in the whole codebase —
  **never enforced anywhere outside the display endpoints** (`admin.py`, `admin_settings.py`,
  `admin_pipeline.py`). Nothing blocks a tenant from creating another quarter plan or triggering
  another N7 run once they exceed this number. **This is a real gap, not a bug** — per the
  ADR's own wording, the mechanism for "limit đặt lúc setup tenant" beyond rpm/posts_per_week
  doesn't exist in code yet and needs new design.

### (e) `tenant_id` column status

`acp_shared.quarter_plan` — **has `tenant_id`** (confirmed live: `plan_id, tenant_id, year,
quarter, current_version_id, created_at`). `acp_shared.quarter_plan_version` has no `tenant_id`
of its own but doesn't need one (reaches it via `plan_id` FK, normal relational design, not a
gap). **No schema change needed for Quarter Plan.**

---

## 2. Marketplace → tenant self-service (T1-style)

### (a) Pure business logic — reusable, but built for a "no tenant yet" world

| Function | File:line | Reusable? |
|---|---|---|
| `_CATALOG_QUERY` (browse/filter `v_trip_registry` + atom richness) | `admin_marketplace.py:72-95` | Yes as a browse query — but see (c), it never filtered by `owner_scope` either |
| `parse_price()` | `services/acp_shared/marketplace_estimates.py` | Yes — pure price parser, no tenant concept involved at all |
| `runway_months()` | same module | Yes — pure estimate from atom count + posts_per_week, no tenant concept |
| `services.acp_planning.runway.parse_duration_days`/`parse_period` | reused as-is (`admin_marketplace.py:33`) | Yes |

### (b) Parts tied to "staff curates FOR a not-yet-onboarded tenant" — must be rewritten

The entire premise of `acp_shared.marketplace_portfolios` (migration 097) is, by its own header
comment, **"the marketplace/portfolio flow runs BEFORE a tenant exists (D4 Mode A / SSP model —
tenant licenses AA's platform-scoped catalog, does not bring its own tours)."** Concretely:

- `SavePortfolioRequest` (`admin_marketplace.py:192-195`) has **no `tenant_id` field at all** —
  by design (there is no tenant yet when a draft portfolio is built).
- `save_portfolio()`'s INSERT (`:242-250`) never writes a tenant_id — there is no column to
  write to (see §2e).
- The auth model is `x-admin-secret` only (staff), with no tenant-JWT path at all — unlike
  `admin_atoms.py`'s `_resolve_atom_owner_scope()` (AA-431) which already supports both.

**Under the new ADR, this whole premise flips**: an *existing* tenant needs to browse and save
their own selection, the same shape T1 (`/v1/tours/pool`) already does for the aa_internal
catalog. This is not a small patch — it's building a genuinely new, tenant-scoped save/finalize
path alongside (or replacing) the pre-tenant one, most likely reusing `_CATALOG_QUERY`'s browse
logic verbatim but adding a tenant-JWT auth path (mirroring `admin_atoms.py`'s AA-431 pattern)
and a `tenant_id` column + ownership check on the portfolio table.

### (c) A second, smaller inconsistency worth carrying into that rebuild

`_CATALOG_QUERY`'s atom-richness aggregate (`admin_marketplace.py:86-94`) has **no
`owner_scope` filter at all** — it counts every non-deleted, non-empty-marker atom for a
`tour_id` regardless of scope:
```sql
SELECT tour_id, count(*) AS atom_count, count(*) FILTER (WHERE distinctiveness = 'HIGH') AS high_count, ...
FROM acp_contract.tour_atoms
WHERE NOT deleted AND NOT is_empty_marker
GROUP BY tour_id
```
Today this is invisible (2551 platform atoms vs. 15 tenant atoms, live count) but the same
question §1c raises applies here too: once real tenants have their own T5/T6 atoms, should a
tenant browsing the shared catalog see richness counted from **platform atoms only** (a
consistent shared baseline every tenant sees the same number for), or also from **other
tenants'** atoms (a cross-tenant data leak, almost certainly wrong), or their own? This needs an
explicit decision when this view is rebuilt — flagged, not decided here.

### (d) Rate-limit/quota status

No mechanism at all today, for the same reason as §1d — Marketplace currently has no tenant
concept to limit. Same "new design needed" conclusion as Quarter Plan.

### (e) `tenant_id` column status

**`acp_shared.marketplace_portfolios` has NO `tenant_id` column** (confirmed live:
`portfolio_id, tour_ids, filters_used, atom_snapshot, status, created_at, finalized_at`) — by
deliberate original design, not an oversight. **A schema change (new column, or a new
tenant-scoped table entirely) is required** to make this tenant-self-service-capable. Not added
in this task (no-code-changes mandate) — flagged for whoever builds T7/Marketplace next.

---

## 3. Produce & Deliver (N7/N8) → T8+T9+T10 (direction unchanged — audited for reuse only)

Per the task's own framing, N7/N8's eventual split into T8 (angle-gate)/T9 (final write)/T10
(QA pass F1-F9) is separately understood as "rework lớn nhất còn lại" (ADR §11.2) — this section
maps reuse-vs-rewrite, it does not propose the T8/T9/T10 boundary itself.

### (a) Pure/reusable logic — already tenant-scoped, further along than Quarter Plan/Marketplace

`api/routers/admin_produce.py`'s trigger endpoint is **already single-tenant-scoped, not an
admin-wide loop**:
```python
@router.post("/run", status_code=202)
async def trigger_produce_run(body: RunRequest, ...):   # body.tenant_id — ONE tenant per call
```
(`admin_produce.py:177-235`). `allocate_month_from_db`/`create_weekly_produce_run`/
`persist_slot_grid`/`fetch_due_slots`/`mark_slot_status`/`allocate_and_persist_week`
(`services/acp_planning/allocator.py`, full file read) are **all** tenant-scoped by required
parameter, with `compute_slot_grid()` even hard-asserting
`if quarter_plan.tenant_id != tenant_id: raise ValueError(...refusing cross-tenant
allocation.)` (`allocator.py:131-132`). `run_slot_production()` (`services/acp_produce
/slot_runner.py`, not re-read line-by-line here, out of scope) is invoked per-tenant per-slot
already. **This whole chain needs the least rework of the three** to become tenant-triggerable
— the trigger endpoint's shape (one tenant, one week, real Bedrock calls, 202+poll) is close to
what a tenant-facing "produce my content" button would look like today, modulo auth (currently
`x-admin-secret` only, would need a tenant-JWT path added, same AA-431 pattern again).

### (b) Parts tied to "admin reviews across ALL tenants" — the actual gate to reconsider

`GET /admin/produce/packets` (`admin_produce.py:304-324`) — **Gate C review queue, no tenant
filter, lists every tenant's `status='ready'` packets on one screen.** `POST
/packets/{id}/gate-c/approve` (`:407-452`) is the staff approval action. This is architecturally
the same shape as Quarter Plan's Gate B queue (§1b) — a cross-tenant admin worklist that ADR
§0.2's "no pre-publish gate" principle would seem to target too, since it is literally a
human-approval step before a tenant's content ships.

**However, worth flagging clearly**: `services/acp_produce/trust_ramp.py` (AA-365)'s underlying
model is a **3-state trust ramp** — `RAMP = ["propose_only", "approve_to_publish",
"veto_window_auto"]` (`trust_ramp.py:41`) — not a rigid always-on gate. Its terminal state,
`veto_window_auto`, is a tenant publishing on their own with AA retaining only a **veto window**
— which reads as a much closer structural match to ADR §0.2's actual "A4 Cross-Tenant
Oversight: hậu-kiểm, có khả năng can thiệp, KHÔNG phải gate chặn trước" language than a
traditional approval gate. **This may already be the right shape for A4**, just not yet reached
by every tenant (a tenant "ramps up" trust over time, per the module's own design intent) — this
observation is offered as useful context for whoever designs T8-T10, not as this task's
conclusion; deciding whether/how to fold Gate C into A4 vs. keep it as a real per-content gate
is explicitly out of scope here.

### (c) Rate-limit/quota status

Same as §1d: `posts_per_week` already shapes weekly slot volume (shared mechanism, since
`allocate_month`/`compute_slot_grid` are the same functions Quarter Plan's allocator uses).
`rate_limit_rpm` applies if/when a tenant-JWT trigger path is added (would flow through the
existing `/v1/*` rate-limit middleware once such a route exists under that prefix). No
Produce-specific "N runs per month" cap exists beyond the slot-count ceiling `posts_per_week`
already implies.

### (d) `tenant_id` column status

**All four tables already have `tenant_id`**, confirmed live:
- `acp_shared.acp_v2_runs`: `run_id, tenant_id, year, week, status, created_at, completed_at,
  month` — RLS-enabled (`tenant_isolation` policy, migration 096).
- `acp_shared.acp_v2_slots`: has `tenant_id` — also RLS-enabled.
- `acp_deliver.packets`: has `tenant_id`.
- `acp_deliver.pieces`: has `tenant_id`.

**No schema change needed for Produce & Deliver's data model.** This is the most
"already-tenant-shaped" of the three areas audited.

---

## 4. Rate-limit/quota mechanism inventory (full picture, task step 4)

| Mechanism | Where | Enforced or just displayed? | Set when |
|---|---|---|---|
| `rate_limit_rpm` (API req/min) | `shared.tenants.rate_limit_rpm`, enforced by `api/middleware/rate_limit.py` (confirmed AA-438-04) | **Enforced, live**, on every `/v1/*` call | Tenant creation, from `PLAN_LIMITS[plan_tier]["rpm"]` (`admin.py:35-40`) |
| `posts_per_week` (content cadence) | `shared.tenants.posts_per_week`, consumed by `compute_slot_grid`/`allocate_month` | **Enforced, live** — directly caps weekly slot count | Tenant creation default, freely tenant-adjustable since AA-384 (not tied to plan_tier — confirmed live, varies per tenant) |
| `tours_quota_monthly` | `shared.v_tenant_monthly_usage` (a computed view) | **Displayed only** — grepped every reference, none outside `admin.py`/`admin_settings.py`/`admin_pipeline.py` display endpoints | Implied by `PLAN_LIMITS[plan_tier]["tours_per_month"]` at creation, never actually enforced anywhere |
| `api_calls_quota_monthly` | same view | **Displayed only** | Same |
| Gate B (Quarter Plan approval) | `acp_shared.quarter_plan_version.approval_status` | Enforced as a **content gate**, not a quota — this is the thing ADR §0.2 says must be removed | N/A |
| Gate C (packet review) | `acp_deliver.packets.publish_mode` (trust ramp) | Enforced as a **content gate** today; structurally closer to a graduated veto-window model (see §3b) | N/A |

**Conclusion for step 4**: a real per-tenant *rate* limit (rpm) and a real per-tenant *content
volume* limit (posts_per_week) both already exist and are enforced today — these already match
the ADR's "giới hạn đặt lúc setup tenant" principle reasonably well. What's genuinely missing is
any enforced monthly/quarterly *usage cap tied to billing plan* (`tours_quota_monthly` etc. are
computed and shown but never block anything) — this is a real gap requiring new design, not a
bug to fix, exactly as the task anticipated.

---

## Summary table

| Mục | Business logic tái dùng (path:line) | Phần phải viết lại (lý do) | Rate-limit/quota | tenant_id column? |
|---|---|---|---|---|
| **Quarter Plan (Gate B) → T7** | `compute_runway_map` (`runway.py:155`), `compute_quarter_plan` (`quarter.py:141`), `fetch_tenant_planning_config` (`tenant_config.py:36`) — all already tenant-scoped, pure/unit-testable | Remove Gate B checks (`allocator.py:128-130`, `:279-301`, both name "Ms. Thu"); remove/repurpose `/admin/quarter-plan/pending` + `/approve`; **fix `fetch_atoms_by_trip()`'s `raw_tours.tenant_id` filter → `owner_scope`-based** (real live inconsistency, not hypothetical) | `posts_per_week` enforced (caps slot count); `rate_limit_rpm` enforced (API only); `tours_quota_monthly` NOT enforced (display-only) | `quarter_plan` ✅ yes; `quarter_plan_version` — via FK, fine |
| **Marketplace → T1-style** | `_CATALOG_QUERY` (`admin_marketplace.py:72`), `parse_price`/`runway_months` (`marketplace_estimates.py`) — pure, no tenant coupling to remove | Whole `marketplace_portfolios` save/finalize flow was built for a PRE-tenant flow (migration 097's own header) — needs tenant-JWT auth path (AA-431 pattern) + tenant-scoped table; catalog's atom-richness aggregate has no `owner_scope` filter either (same class of gap as Quarter Plan's) | None today — no tenant concept in this flow yet | `marketplace_portfolios` ❌ **no tenant_id column at all**, by design — schema change required |
| **Produce & Deliver (N7/N8) → T8-T10** | Entire `allocator.py` (`allocate_month`, `create_weekly_produce_run`, `persist_slot_grid`, `fetch_due_slots`, `mark_slot_status`) + `admin_produce.py`'s `/run` trigger — already single-tenant-scoped, closest to self-service-ready of the three | Gate C review queue (`GET /admin/produce/packets`, no tenant filter) + `/gate-c/approve` — same class of "admin gates all tenants" as Gate B, though `trust_ramp.py`'s veto-window terminal state may already be closer to the ADR's A4 oversight model than a hard gate (flagged, not decided) | `posts_per_week` enforced (shared mechanism with Quarter Plan); no Produce-specific cap | `acp_v2_runs`/`acp_v2_slots`/`packets`/`pieces` ✅ **all have tenant_id**, RLS already enabled on the first two |

---

## Open items — explicitly out of scope / not decided here

- Whether Gate C (`trust_ramp.py`) should be folded into "A4 Cross-Tenant Oversight" or kept as
  a real pre-publish gate — flagged with reasoning (§3b), not decided.
- The exact T8/T9/T10 split boundary for N7/N8 — explicitly out of scope per the task prompt
  ("KHÔNG đổi hướng, vẫn theo nhận định cũ").
- Design of the missing monthly-quota enforcement mechanism (§4) — flagged as a real gap, no
  design proposed.
- `run_slot_production()` (`services/acp_produce/slot_runner.py`) internals — not re-read
  line-by-line; only its call boundary with `admin_produce.py` was checked.
- Whether `owner_scope IN ('platform', tenant_id)` is definitely the right fix shape for §1c/2c
  — named as the obvious direction (matches the existing AA-431 precedent exactly) but not
  implemented or exhaustively verified against every downstream reader of these atom-fetch
  functions.
