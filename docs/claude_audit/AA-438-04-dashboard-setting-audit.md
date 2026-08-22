# AA-438 — Audit Dashboard/Settings + Remaining Admin Sidebar Items

Audit only. No code changed. Every claim below is backed by `path:line` or a real DB query
(S3-mediated ECS exec, `aa-cis-dev-db`, run 22/08/2026 16:13 UTC). Continues from
`docs/claude_audit/AA-438-01/02/03`, all read first — this task does **not** re-audit
Upload/S1 Rewrite/Review Queue/Master Content (already audited).

**Headline finding: "Run Health" reads a table that is structurally disconnected from the
pipeline it claims to monitor — and the reason ALL 5 "Pipeline Health" cards on the Dashboard
show idle isn't a per-card bug, it's one root cause that makes every admin-driven action
invisible to that whole panel by design.**

---

## Sidebar inventory (from `AdminSidebar.tsx`, full read)

| Group | Item | Route | Status |
|---|---|---|---|
| ACP v2 — Setup & Approval | Dashboard | `/admin/dashboard` | audited here (parts not covered by AA-438-01) |
| | Tenants | `/admin/tenants` | audited here |
| | Marketplace | `/admin/marketplace` | audited here |
| | Quarter Plan (Gate B) | `/admin/quarter-plan` | audited here |
| | Produce & Deliver (N7/N8) | `/admin/produce` | audited here |
| | Run Health | `/admin/run-health` | audited here — **headline bug** |
| ACP v2 — Atoms | Atomize (N2) | `/admin/atomize` | audited here — **legacy investigation** |
| | Atom Curation | `/admin/curation` | audited here — **legacy investigation** |
| AA Internal Content | Upload (S0) | `/admin/upload` | already audited, AA-438-01 — skipped |
| | S1 Rewrite | `/admin/s1-rewrite` | already audited, AA-438-01 — skipped |
| | Review Queue | `/admin/review` | already audited, AA-438-02 — skipped |
| | Brand Identity | `/admin/brand` | audited here (only referenced indirectly before) |
| | Master Content | `/admin/master-content` | already audited, AA-438-03 — skipped |
| (own row) | Settings | `/admin/settings` | audited here |

---

## 1. Dashboard — the parts AA-438-01 didn't cover

`frontend/app/admin/dashboard/page.tsx` (full read) has no mock/hardcoded data anywhere in the
JSX — every number comes from a `fetch`. Backend: `GET /admin/metrics`
(`admin_pipeline.py:3370-3577`), `/admin/metrics/seo` (`:3582-3657`),
`/admin/metrics/library` (`:3662-3707`).

### 1a. "Model Usage" / "LLM Calls" — real numbers, wrong scope, real undercount

Source: `admin_pipeline.py:3412-3426` —
```sql
SELECT CASE WHEN model_editorial LIKE '%haiku%' THEN 'claude-haiku-4-5' ... END AS model,
       COUNT(*) AS calls, ROUND(AVG(qs.score_overall)::numeric,1) AS avg_score
FROM silver_aa_internal.generated_content gc
LEFT JOIN silver_aa_internal.quality_scores qs ON qs.generated_content_id = gc.id
GROUP BY 1
```

**Two real, confirmed problems, not hypothetical:**

1. **"Calls" = `COUNT(*)` of finished `generated_content` ROWS, not actual LLM API calls.**
   A single row can represent 1-3 `generate_node` retries (`graph.py`'s `MAX_RETRIES=3` loop)
   + 1 `llm_judge` call + up to 1 `brand_audit` call + up to 1 `flag_fix` call + a re-judge call
   inside `revalidate_node` + per-day `nudge_itinerary_day` calls (`_process_itineraries`,
   `graph.py:27-108`). Real query (22/08 16:13 UTC): 228 `generated_content` rows total — the
   real number of LLM invocations behind those 228 rows is easily several times higher. The
   Dashboard's "LLM Calls" card (`src: "↳ generated_content · all runs"`, `page.tsx:84`) is
   honest about its own source in the UI, but that source is a proxy, not a real call count.

2. **This card is scoped ONLY to `silver_aa_internal.generated_content` — the aa_internal S1
   Rewrite pipeline. It structurally cannot ever reflect ACP v2 tenant-facing (T-series) LLM
   usage, including yesterday's AA-436 test.** Confirmed by data, not inference:
   `generated_content_total` = 228, `MAX(created_at)` = 2026-08-21 11:59 (unchanged since
   AA-438-02 — nothing new since). Meanwhile `gold_aa_internal.tenant_tour_versions` (the real
   T2/T3 tenant-rewrite output table) has 23 rows, `MAX(created_at)` = 2026-08-21 15:40 — a
   **different, later** timestamp, in a table `admin_pipeline.py`'s metrics query never touches.
   This matches AA-434's own already-published finding
   (`docs/claude_audit/AA-434-llm-usage-tracking-per-tenant-audit.md`): the tenant rewrite path
   (`services/acp_produce/tenant_pipeline.py` + `v1_tours.py::trigger_rewrite()`) computes
   `cost_usd`/tokens per call in memory and **never persists them anywhere** —
   `tenant_tour_versions` has no cost/model/token column at all. So this isn't just "Model
   Usage doesn't query the right table" — even if it did, **there is nothing there to query**.
   Dashboard's own subtitle claims "All-tenant metrics · API v0.3.0" (`page.tsx:467`) — that
   claim is not true for Model Usage/LLM Calls; both are aa_internal-only, by construction.

### 1b. "Pipeline Health" — same root cause across ALL 5 cards, worse than AA-438-01 found

AA-438-01 flagged one card ("Ingestion Lambda: Idle") as reading the wrong source
(`tenant_api_usage` HTTP-call counts instead of real AWS Lambda invocations). This task traced
**why `tenant_api_usage` itself is basically always empty for anything admin-driven** — and it
applies to all 5 cards, not just Ingestion Lambda.

`admin_pipeline.py:3469-3479` — the sole data source for every Pipeline Health card:
```sql
SELECT endpoint, COUNT(*) calls, ... FROM shared.tenant_api_usage
WHERE called_at >= NOW() - INTERVAL '1 hour' GROUP BY endpoint
```
mapped to service names via `ENDPOINT_SERVICE_MAP` (`:3481-3492`), which includes BOTH
`/v1/pipeline/*` entries AND `/admin/*` entries (`/admin/run-tour`, `/admin/upload-url`).

**Traced who writes `tenant_api_usage` — there is exactly one writer in the whole codebase**:
`shared/services/billing_service.py::track_api_call()`, called from exactly one place,
`api/middleware/rate_limit.py::rate_limit_middleware`. That middleware's very first line
(`rate_limit.py:63`): `if not request.url.path.startswith("/v1/"): return await call_next(request)`
— **no tracking call at all for any non-`/v1/*` path.** Every `/admin/*` route — which is
literally 100% of this Dashboard, Upload, S1 Rewrite, Review Queue, Master Content, Tenants,
Marketplace, Quarter Plan, Produce, Run Health, Atomize, Curation, Brand, Settings — is
excluded from tracking, unconditionally, before the middleware even looks at auth. (It also
skips `/v1/*` calls without a Bearer JWT, and JWTs that fail verification — a further, smaller
narrowing on top.)

**Live-confirmed the practical effect**: called the real `/admin/review-queue/{id}/approve`
endpoint in AA-438-03 (15:50 UTC, same session, ~23 min before this query at 16:13 UTC) —
`tenant_api_usage`'s `MAX(called_at)` is **08:58:44 UTC that same morning**, 7 hours earlier.
My approve call, a completely real admin action, left zero trace in the one table Pipeline
Health reads. Confirmed again by a live, endpoint-filtered query across every one of the 6
still-unaudited admin feature groups (atoms/curation/quarter-plan/produce/run-health
/marketplace) over the last 7 days: **zero rows**, despite real underlying data existing in
all of them (see §2-§7 below).

**Consequence: the "Ingestion Lambda: Idle" card AA-438-01 found is not a special case — every
one of the 5 Pipeline Health cards (Ingestion Lambda, Step Functions Pipeline, Content
Generation, Validation Lambda, Export/Catalog API) is structurally guaranteed to read "idle"
for the entire aa_internal admin workflow, no matter how much real activity happens there.**
Only genuine tenant-JWT-authenticated `/v1/*` traffic could ever light one up — and per this
repo's own architecture notes (`AA-CIS-App/.claude/CLAUDE.md`, "Step Functions Architecture"),
`/v1/pipeline/*` is largely superseded by the direct `/admin/*` flow for aa_internal's own use
today. This isn't a per-card "reads the wrong metric" bug — it's a single, whole-panel design
gap: nobody wired real activity-tracking to admin routes at all.

### 1c. Tenant Breakdown, SEO Intelligence tab, Content Library tab — real, no new bugs found

- Tenant Breakdown (`admin_pipeline.py:3443-3448`): plain `COUNT(*)` join of
  `tenant_tour_versions`/`tenants`, no date filter, no stuck-status gotcha — clean.
- SEO tab (`/admin/metrics/seo`, `:3582-3657`): real queries against `seo_context`/
  `published_tours`, plus a real Redis `INFO stats` call for cache hit rate. No mock.
- Library tab (`/admin/metrics/library`, `:3662-3707`): real, scoped to aa_internal
  `published_tours` (label "Total Published"/"By Country" — this scoping is accurate to its own
  labeling, unlike Model Usage's "all-tenant" mislabel). No stuck-filter pattern found.

---

## 2. Tenants (`/admin/tenants`)

Backend `GET /admin/tenants` (`admin.py:204-327`, full read) — real, live-query, two real result
sets (active `tenants` + `pending_tenants` for is_active=false onboarding, an AA-389 fix
explicitly documented inline). No mock. **Real count, live query: 14 tenants total** (1
`aa_internal` + 13 B2B, several clearly test/dev artifacts by name —
`aa309-verify-c5316bd4`, `aa-384-live-verify`, `test-n1-flow`, `lumitest`, `test-agency`,
`sri-landka` — see the cleanup-plan section of the summary report).

## 3. Marketplace (`/admin/marketplace`)

`api/routers/admin_marketplace.py` (full read) — real, well-documented (AA-330), reuses
`acp_contract.v_trip_registry` (correctly `master_status`/`deleted_at`-filtered, per
AA-438-03 §6) joined to a real `tour_atoms` richness aggregate. `save_portfolio`/
`finalize_portfolio` are real DB writes with real business-decision comments (D2: unparseable
price never drops a tour from results). **Live counts: 9 `marketplace_portfolios` (7
finalized, 2 draft).** No mock, no stuck-filter pattern.

## 4. Quarter Plan — Gate B (`/admin/quarter-plan`)

`admin.py:1759-1975` (full read) — real compute (`plan_quarter`/`runway_map`), real persist
(`save_quarter_plan_version`), real approve gate (row-locked, matches the Gate A/B pattern
documented in `AA-CIS-App/.claude/CLAUDE.md`). **Live counts: 4 plans, 9 versions, all 9
already `approval_status='approved'`** — so the "pending" queue is legitimately empty right
now (every version that ever existed has already been approved), not a bug.

## 5. Produce & Deliver — N7/N8 (`/admin/produce`)

`admin_produce.py` (module docstring + full header read) — this is a genuinely new, real,
first-ever live wiring (AA-405, confirmed by its own STEP-0 recon: `run_slot_production()`
"had zero real callers outside tests" before this). Async 202+BackgroundTask pattern to work
around API Gateway's 29s hard timeout — real Bedrock calls per piece. **Live counts: 12
`acp_v2_runs` (all `status='completed'`), 45 `acp_v2_slots`, 4 `acp_deliver.packets`, 135
`acp_deliver.pieces`.** This is real, working production activity — genuinely the most "alive"
item audited in this task. (Its own code comment references API Gateway id `owq9as3wjl`,
dated 15/08 — that ID is now stale per `AA-432` [confirmed corrected 22/08 to `4ylo382khg`] —
a comment-only staleness, not a functional bug, noted in passing.)

## 6. Run Health (`/admin/acp/run-health`) — the headline bug

`api/routers/acp_health.py` (full read, 308 lines). Real, well-built code — RLS-aware
(tenant JWT sees own runs, admin sees all), computes SLO/SLA breach flags, emits CloudWatch
metrics. The bug is not in this file's logic — it's in **what table it reads**:

```sql
FROM acp_shared.acp_runs r
```

**Live query: `acp_shared.acp_runs` has 0 rows. So does `acp_shared.acp_stage_runs` (0) and
`acp_shared.acp_hitl_requests` (0).** Since `frontend/app/admin/run-health/page.tsx` has
exactly one data source (`fetch('/api/admin/acp/run-health...')`, confirmed — no fallback),
the Run Health page currently shows a permanently empty run list.

**This table is not the same table as the one Produce & Deliver actually uses.** Traced who
writes `acp_shared.acp_runs`: `api/routers/v1_s1.py`, `services/acp/s2/router.py`,
`api/routers/v1_s4_blog.py` — these are exactly the **legacy ACP v1 (S2 Research/S3
Calendar/S4 Blog/S4 Social)** endpoints `AdminSidebar.tsx`'s own AA-390 comment says were
deliberately unlinked from the sidebar because "nobody needs ACPv1 access anymore." Meanwhile
the pipeline that **is** actually live and being used — N7/N8 Produce & Deliver (§5, 12 real
completed runs) — persists its run state in `acp_shared.acp_v2_runs`/`acp_v2_slots`, a
**different table `acp_health.py` never queries.**

**Net effect: Run Health shows nothing, not because there's no real ACP v2 activity to show
(there is — §5's 12 completed N7/N8 runs), but because it's wired to the run-tracking table of
the old, unlinked ACP v1 pipeline instead of the one the currently-live N7/N8 pipeline actually
writes to.** This is a second, independent confirmation of the same class of bug as §1b
(Pipeline Health) and AA-438-01's Ingestion Lambda card — "reads a real but wrong/dead source" —
but at the scale of an entire sidebar page rather than one metric card, and with a clear,
concrete fix direction (point it at `acp_v2_runs`/`acp_v2_slots`/`acp_deliver.packets` instead,
or a UNION of both if ACP v1 might ever run again) that AA-438-01/here can name but does not
implement (out of scope, no-code-changes mandate).

Minor, lower-severity note found in the same file: `"retry_count": 0,  # UNIQUE(run_id, stage) —
upserted in-place` (`acp_health.py:288`) is unconditionally hardcoded — correctly explained in
its own comment (the schema can't currently distinguish a retry from a fresh run), and confirmed
**not rendered anywhere in the FE** (`run-health/page.tsx` only declares the TS field, never
uses it in JSX) — so it's a dead, harmless field today, not a user-visible lie.

## 7. Brand Identity (`/admin/brand`)

`admin_pipeline.py:3793-4066` (full read) — real CRUD over `shared.tenant_brand_rules`,
scoped to the master (`aa_internal`) tenant, version-tracked, real DOCX parsing
(`parse_brand_docx`, real `python-docx`, not a stub). **Live counts: 8 brand-rule rows across
5 tenants** (aa_internal has 1 active version — matches AA-438-02 §5's earlier finding, no
change). No mock.

## 8. Settings (`/admin/settings`)

`frontend/app/admin/settings/page.tsx` + `api/routers/admin_settings.py` (both full read).
**This page is, refreshingly, self-honest about what's hardcoded** — it literally renders a
`<Badge color="amber">hardcoded</Badge>` next to "Brand Audit Threshold" (`page.tsx:62`) and a
`<Badge color="gray">read-only</Badge>` next to "SEO Provider" (`page.tsx:291`). The backing
values are indeed a Python module constant, `PIPELINE_GATES` (`admin_settings.py:15-19`):
```python
PIPELINE_GATES = {
    "brand_audit_threshold": 7.0,
    "dedup_key": "lower(trim(src_name)) + lower(trim(provider))",
    "pipeline_flow": ["generate", "validate", "brand_audit", "flag_fix"],
}
```

`brand_audit_threshold: 7.0` correctly matches `graph.py`'s real `MIN_QUALITY = 7.0` constant
(AA-438-02 §2) — accurate, if slightly mis-named (it's the overall quality gate, not something
specific to the brand_audit node, which itself has no numeric threshold — it returns
categorical `pass`/`flagged`/`manual_check`).

**Real, confirmed inaccuracy found: `pipeline_flow` is stale — it lists only 4 of the 6 real
graph nodes.** The actual graph (`graph.py::build_graph`, confirmed AA-438-02 §2) is
`generate → validate → llm_judge → [brand_audit → flag_fix → revalidate | retry | hitl]`.
Settings' hardcoded list omits `llm_judge` (the GPT-4.1 judge node, added AA-206) and
`revalidate` (added AA-215) entirely — so an admin reading this "Pipeline Flow" chip UI gets a
picture of the pipeline that's missing two real, load-bearing nodes. `trash_retention_days: 30`
(`admin_settings.py:132`) is also a hardcoded literal, but it's honestly labeled "system
default" in the UI (`page.tsx:454`) — same self-disclosure pattern, lower severity.

`SEO Config` and `Tenant Info` tabs are real, live-queried (`shared.tenant_seo_config`/
`shared.tenants`), with a real working PATCH-to-save flow for SEO config — not mock.

---

## 9. PRIORITY: "Atomize (N2)" and "Atom Curation" — confirmed NOT legacy, both load-bearing, different scope than T5/T6

Nghiep's hypothesis was that both are tàn dư now that T5 (auto-atomize in the T2→T3→T5 chain)
and T6 (`/portal/t6-atoms`, AA-431 tenant self-service) exist. **Confirmed false for both, by
code + live data — they operate on a different scope than T5/T6, not a redundant one.**

### Atomize (N2) — atomizes the PLATFORM catalog, T5 never touches this data

- Route: `POST /admin/atoms/decompose` (`admin_pipeline.py:1860-1868`) is a thin alias that
  calls `api/routers/v1_atoms.py::decompose()` **verbatim** — same function the (JWT-gated,
  tenant-facing) `/v1/atoms/decompose` route uses, just reachable through the admin BFF because
  `/v1/*` sits behind the API Gateway Lambda authorizer and the admin BFF can't send a Bearer
  JWT (same shape as AA-230's review-queue alias).
- `decompose()`/`_decompose_inline()` reads from `acp_contract.v_trip_registry` (`v1_atoms.py:
  365-382`) — **the platform's raw/master tour catalog** (all 763 floor tours, not any one
  tenant's rewritten content) — and writes atoms with **`owner_scope` hardcoded to the literal
  string `"platform"`** (`v1_atoms.py:265`, `:288`).
- **T5 (`services/acp_produce/tenant_pipeline.py::run_t5_atomize`, line 195) is a
  completely separate, independent implementation.** Its own docstring: *"T5 — decompose atoms
  from T4 output (tenant-rewritten), owner_scope=tenant_id."* It atomizes ONE tenant's OWN
  rewritten version of ONE tour (from `tenant_tour_versions`), not the platform catalog, and
  writes `owner_scope=<that tenant's UUID>`, never `"platform"`.
- **Live-confirmed the split**: `acp_contract.tour_atoms` (live, non-deleted, non-empty-marker
  rows) has `owner_scope='platform'`: **2551 atoms** (created 21/07→17/08/2026 — this IS
  Atomize(N2)'s real, substantial output) vs. `owner_scope='9fb0a3db-...'` (the "test-agency"
  tenant): **15 atoms** (created 21/08, matching T5's recent test run per §Model-Usage above).
- **Downstream dependency confirmed**: Marketplace's catalog richness aggregate
  (`admin_marketplace.py:86-94`) and the N4-N6 planning preview (`admin_atoms.py`'s
  `preview-slotgrid` → `allocate_month`/`plan_quarter`) both read `acp_contract.tour_atoms`
  filtered the same way — **if Atomize(N2) had never run, there would be zero platform atoms
  for Marketplace or N4-N6 planning to work with at all**, since T5 structurally never touches
  the platform catalog (only ever a tenant's own rewrite). **Conclusion: Atomize (N2) is not
  legacy — it is the only source of platform-scope atoms, and real downstream features (§3
  Marketplace, N4-N6 planning) depend on its output today. Recommend KEEP.**

### Atom Curation — a staff-only SUPERSET view, not a duplicate of T6

- `admin_atoms.py`'s own module header states plainly it does **not** touch `v1_atoms.py`
  (decompose) at all — "a separate, purely additive resource: list/filter + star/delete/edit on
  already-decomposed atoms."
- The AA-431 comment block (`admin_atoms.py:64-83`) is explicit and directly answers the
  question: `_resolve_atom_owner_scope()` returns the **caller's own tenant_id** (forced from
  the verified JWT `sub` claim, never client-suppliable) when called with a tenant Bearer token
  — that's the code path `/portal/t6-atoms` uses — **or `None` (no filter at all) for an
  admin/staff `X-Admin-Secret` caller, "unchanged from before, staff still need to see platform
  + every tenant's atoms for curation/support."**
- **So `/admin/curation` and `/portal/t6-atoms` share the exact same backend endpoints**
  (`GET /admin/atoms`, `PATCH /admin/atoms/{id}`, `PATCH /admin/atoms/bulk`) with **different
  scopes by design**: admin sees platform + every tenant's atoms (a real cross-tenant
  moderation/support capability a tenant self-service view structurally cannot and should not
  have); a tenant sees only their own. This is the same one-endpoint-two-scopes shape this
  repo already used for Brand Identity (AA-424, referenced in the same comment) — a deliberate,
  repeated pattern, not an oversight. **Conclusion: Atom Curation is not legacy — it is the
  staff superset view T6 cannot replace. Recommend KEEP.**

### Recency check (task's ask #1)

`recent_endpoint_traffic_7d` (real query, filtered to atoms/curation/quarter-plan/produce
/run-health/marketplace/decompose endpoint names): **zero rows** — but per §1b, this is fully
explained by `tenant_api_usage` never tracking `/admin/*` traffic at all, regardless of whether
the feature is alive or dead. It is **not** evidence either page is unused — the underlying
data (2551 platform atoms, most recently touched 17/08; 15 tenant atoms, most recently touched
21/08) is real, substantial, and recent enough to indicate ongoing real use, just invisible to
this particular traffic-tracking mechanism (same root cause as §1b, not re-litigated here).

---

## Summary table for this task

| Item | Real/mock | Data source correct? | New bug found |
|---|---|---|---|
| Dashboard — Model Usage | Real | Wrong scope (aa_internal only) + undercounts real LLM calls | Yes (§1a) |
| Dashboard — Pipeline Health | Real | Structurally broken for ALL 5 cards (root cause, not per-card) | Yes (§1b) |
| Dashboard — Tenant Breakdown/SEO/Library tabs | Real | Correct | No |
| Tenants | Real | Correct | No |
| Marketplace | Real | Correct | No |
| Quarter Plan (Gate B) | Real | Correct (all versions already approved) | No |
| Produce & Deliver (N7/N8) | Real, actively used | Correct | No (stale API GW id in a comment only) |
| Run Health | Real code, but reads a dead/wrong table | **Wrong table entirely** | Yes, headline (§6) |
| Brand Identity | Real | Correct | No |
| Settings | Real, self-labels hardcodes | `pipeline_flow` list is stale (missing 2 real nodes) | Yes (§8) |
| Atomize (N2) | Real | N/A — confirmed NOT legacy, distinct scope | No — keep |
| Atom Curation | Real | N/A — confirmed NOT legacy, staff superset of T6 | No — keep |

## Open items — explicitly unconfirmed / out of scope

- Whether `Step Functions Pipeline`/`Validation Lambda`/`Export / Catalog API` (Pipeline Health
  card names) correspond to any AWS resource that still exists at all, vs. being aspirational
  names from an earlier architecture (Step Functions is confirmed bypassed per this repo's own
  CLAUDE.md) — not verified against live AWS resources in this task, only against the code's
  own data source.
- The stale API Gateway id (`owq9as3wjl`) in `admin_produce.py`'s module comment — cosmetic,
  not fixed (no code changes this task).
- Exact per-row count of how many of the 2551 platform atoms vs. 15 tenant atoms are actually
  consumed downstream (e.g., how many appear in a finalized Marketplace portfolio) — not
  computed, out of scope.
