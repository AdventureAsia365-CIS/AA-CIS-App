# AA-438 — Admin Tier Audit: Full Summary (Tasks 01→04)

Consolidates `AA-438-01-a0-a1-audit.md`, `AA-438-02-a1-a2-audit.md`, `AA-438-03-a2-a3-audit.md`,
`AA-438-04-dashboard-setting-audit.md` — the complete admin-tier audit of AA-CIS-App, run
22/08/2026 on branch `feature/aa-438-admin-tier-audit`. No code changed across all 4 tasks
except one deliberate, explicitly-authorized live action (AA-438-03: approved 1 real hitl tour
through the real endpoint — see that report §3, not reversible).

This is the handoff document for whatever comes next — read this one first; the 4 underlying
reports have the full evidence trail (`path:line` + real query/response) behind every line
below.

---

## What the pipeline actually is, confirmed end-to-end

```
A0 Upload (S0)  →  A1 S1 Rewrite  →  A2 Review Queue (hitl gate)  →  A3 Master Content (published_tours)  →  T1 Tour Selection (tenant pool browse)
   raw_tours         generated_content    review_queue                  gold_aa_internal.               v1_tours.py::browse_pool
   (silver)          (status=approved/          (review_status=          published_tours
                      hitl)                      pending/approved/
                                                  rejected)
```

Every arrow above is now confirmed by real code + a real query or a real live test — not
inferred. A0→A1 and A2→A3 are automatic within one request; A1→A2 (hitl branch) is decided
inside `_is_publishable()` (admin_pipeline.py), fed by the graph's `should_retry()` edge, not
inside the LangGraph itself.

---

## All confirmed bugs/gaps, in one list (per-task detail in the linked report)

| # | Bug/gap | Where | Severity | Task |
|---|---|---|---|---|
| 1 | `pipeline_runs.status` stuck at `'ingesting'` forever whenever a batch has ≥1 hitl tour — no code path ever flips it, since it only advances on ALL-tours-published (`pending==0`) | `services/export/handler.py` | Dashboard-only (double-checked in 02 and 03 — never gates real pipeline behavior) | 01 |
| 2 | Dashboard's own "Pipeline Activity (7d)"/"Pass Rate" bucket by `started_at` (ingest time, not rewrite time) AND filter `status != 'ingesting'` — combines with #1 to guarantee the table reads empty even during real, active rewriting | `admin_pipeline.py:3381-3395` (`GET /admin/metrics`) | Confirmed real, dashboard-only | 01 |
| 3 | Possible double-fire of ingestion: a real S3-triggered Lambda (`aa-cis-dev-ingestion`) AND the admin Upload page's in-process `process_file()` call both fire on the same S3 object | `api/routers/admin_pipeline.py` upload path | **Unconfirmed** — architecturally likely, not verified via CloudWatch | 01 |
| 4 | `pipeline_runs` accounting UPDATE silently skipped when `batch_id` isn't a valid UUID (ad-hoc/verification runs) — no error surfaced anywhere | `admin_pipeline.py:709-714` | Minor, logged only | 01 |
| 5 | Reject (`/admin/review-queue/{id}/reject`) never resets `generated_content.status` back from `'hitl'` — a rejected tour stays labeled `hitl` forever, invisible in the Review Queue's default "pending" filter | `api/routers/v1_pipeline.py::reject_review` | **Real, confirmed live** — 2 of 39 real rows affected | 02 |
| 6 | 11 `review_queue` rows for a different tenant (`9fb0a3db-...`, "test-agency") are orphaned — `review_status='pending'` but no matching `generated_content` row exists at all | live query | Flagged, not investigated (out of scope, likely a per-tenant-schema mismatch) | 02 |
| 7 | `published_tours`' `ON CONFLICT (tour_id) DO UPDATE` only refreshes 4 of 18 columns (`generated_content_id`/`aa_name`/`quality_score`/`published_at`) — re-publishing a tour after a later rewrite leaves `aa_subtitle`/`seo_title`/`seo_meta`/etc. stale from the tour's FIRST-ever publish | `shared/repository/published_catalog_repository.py:29-33` | **Real, confirmed live** — caught mid-test, affects every tour republished more than once | 03 |
| 8 | `/v1/tours/pool` (T1's real tenant-facing pool browse) has zero `master_status`/`deleted_at` filter — unlike `acp_contract.v_trip_registry` which correctly filters both — so a tour an admin trashes/deactivates in Master Content stays fully visible and rewritable to every tenant | `api/routers/v1_tours.py::browse_pool`, `:104-128` | **Real, confirmed by code comparison** | 03 |
| 9 | `shared/services/export_service.py` (`ExportService.publish_tour()`) is dead code — zero callers anywhere, references `slug`/`country`/`is_active` columns that don't exist on the real `published_tours` table | dead file | Low severity, misleading if read cold | 03 |
| 10 | The tour live-tested in 03 scored 9.0/10 overall, 10/10 on brand fit, with a brand-audit narrative reading as an outright compliment — yet `brand_audit_status='manual_check'` blocked it from publish for 59 days | live data, `quality_scores` row | **Concrete evidence** for the brand_audit-too-strict hypothesis (deliberately not investigated further — flagged for a dedicated follow-up task) | 03 |
| 11 | Dashboard "Model Usage"/"LLM Calls": `calls` = `COUNT(*)` of finished `generated_content` rows, not real LLM API calls — undercounts by however many retries/judge/brand_audit/flag_fix/nudge sub-calls each row actually took | `admin_pipeline.py:3412-3426` | **Real, confirmed** | 04 |
| 12 | Same card is scoped ONLY to `silver_aa_internal.generated_content` — structurally cannot ever reflect ACP v2 tenant-facing (T-series) LLM usage. Confirmed: `tenant_tour_versions` (the real tenant-rewrite table) has zero cost/model/token columns at all (also independently confirmed by the earlier `AA-434-llm-usage-tracking-per-tenant-audit.md`) | same | Dashboard's "All-tenant metrics" claim is false for this card | 04 |
| 13 | **All 5 "Pipeline Health" cards are structurally guaranteed to show idle for 100% of admin-driven (`/admin/*`) activity** — traced to one root cause: `tenant_api_usage` (the sole data source) is only ever written by `rate_limit_middleware`, which unconditionally skips every non-`/v1/*` path before it even checks auth. Live-confirmed: an admin action performed in this same session left zero trace in the table | `api/middleware/rate_limit.py:63`, `shared/services/billing_service.py` | **Real, confirmed live, root-caused** — generalizes AA-438-01's narrower "Ingestion Lambda: Idle" finding to the whole panel | 04 |
| 14 | **Run Health reads `acp_shared.acp_runs`, which has 0 rows** — written only by the legacy, deliberately-unlinked ACP v1 (S2/S3/S4 blog/social) endpoints. The pipeline that's actually live and running (N7/N8 Produce & Deliver — 12 real completed runs) persists to a *different* table, `acp_shared.acp_v2_runs`, which Run Health never queries | `api/routers/acp_health.py`, `frontend/app/admin/run-health/page.tsx` | **Real, confirmed live — headline finding of task 04** | 04 |
| 15 | Two tables named `acp_runs` exist in two different schemas (`shared.acp_runs`, old A0-A3 manifest tracker, batch-keyed; `acp_shared.acp_runs`, old ACP v1 run tracker, run_id-keyed) — a naming collision that nearly caused a misreading during this audit itself | migrations 009 vs. later N-series migrations | Naming trap, not a functional bug — flagged so nobody else falls for it | 04 |
| 16 | Settings' "Pipeline Flow" chip UI is a hardcoded 4-node list (`generate/validate/brand_audit/flag_fix`) missing 2 real graph nodes (`llm_judge`, `revalidate`) | `api/routers/admin_settings.py:15-19` | Real, confirmed by comparison to `graph.py::build_graph` | 04 |
| 17 | `retry_count: 0` hardcoded unconditionally in Run Health's response, with a self-explaining comment (schema can't track it) — confirmed dead, not rendered anywhere in the FE | `api/routers/acp_health.py:288` | Very low severity | 04 |
| 18 | `published_tours` total count: 71 now vs. 72 reported in AA-438-01 — a 1-row gap that predates the AA-438-03 live test (which only updated an existing row) and was not investigated | live query | Flagged, out of scope | 03 |

**Confirmed NOT bugs (investigated on suspicion, ruled out):**
- "Atomize (N2)" and "Atom Curation" are **not** legacy/redundant with T5/T6 — see the sidebar
  table below. Both are real, load-bearing, different-scope flows; recommend keeping both.
- Quarter Plan (Gate B), Produce & Deliver (N7/N8), Marketplace, Tenants, Brand Identity, SEO
  Intelligence tab, Content Library tab — all real, live-queried, no mock data, no stuck-filter
  pattern found.

---

## Data Cleanup Plan

Nghiep's decision (Linear AA-438 comment thread): **after both AA-438 (Admin tier, this audit)
and AA-439 (Tenant tier, T0-T11) are fully audited**, wipe all build/test data and keep only
the ~700+ raw source tours, then run the whole pipeline again from a clean state.

What this audit found that's relevant to that cleanup, for reference when it happens:

- **Test/dev tenants to remove**, live count 14 tenants total, `aa_internal` + 13 B2B — several
  are clearly test/verify artifacts by name, not real prospects: `test-agency`
  (`9fb0a3db-...`, also the source of the 11 orphaned `review_queue` rows, bug #6, and the 15
  tenant-scope `tour_atoms` from the recent T5 test), `lumitest`, `sri-landka`,
  `aa309-verify-c5316bd4`, `aa-384-live-verify`, `test-n1-flow`. Real-looking business tenants
  to keep: `wanderlux-travel`, `exploreasia-co`, `peakadventures`, `atlas-hearth`,
  `terra-family-expeditions`, `trail-pulse`, `wildkind-travel`.
- **The 39 (now 38) hitl `generated_content` rows** (ages 1-59 days, task 02) and the live
  -published test row from task 03's approve test are all part of the same "build/test" data
  this cleanup is meant to clear — no special handling needed beyond what the cleanup already
  plans to do (they live in `silver_aa_internal.generated_content`/`gold_aa_internal
  .published_tours`, both presumably in scope for the wipe).
- **`acp_contract.tour_atoms`**: 2551 `owner_scope='platform'` atoms (real Atomize(N2) output,
  21/07→17/08) + 15 `owner_scope=<test-agency>` atoms (T5 test output, 21/08) — both would need
  re-generating post-cleanup since Marketplace/N4-N6 planning depend on the platform atoms
  existing (bug analysis, §Atomize(N2) below).
- **Do not let the cleanup silently "fix" any of the 18 confirmed bugs above** — none of them
  are data problems; they're code/config problems (stuck status columns, wrong table reads,
  partial UPSERTs, missing filters) that will reproduce immediately on the next real run unless
  separately fixed. A clean data slate does not fix bug #7 (partial UPSERT), #8 (missing T1
  filter), #13/#14 (wrong metrics tables), or #16 (stale hardcoded pipeline flow).

---

## Sidebar Admin — Legacy vs Tenant-Facing Overlap

All 13 real sidebar items + Settings, per the full `AdminSidebar.tsx` read (task 04).

| Sidebar item | Real route / backend | Tenant-facing equivalent? | Recommendation |
|---|---|---|---|
| Dashboard | `/admin/dashboard` → `GET /admin/metrics(+/seo,+/library)` | None | **KEEP** — admin-only aggregate view |
| Tenants | `/admin/tenants` → `GET/POST /admin/tenants` | None (a tenant can't manage other tenants) | **KEEP** |
| Marketplace | `/admin/marketplace` → `admin_marketplace.py` | None found | **KEEP** — staff curates catalog portfolios for tenants |
| Quarter Plan (Gate B) | `/admin/quarter-plan` → `admin.py` quarter-plan handlers | None (approval gate, staff-only by design, same pattern as Gate A) | **KEEP** |
| Produce & Deliver (N7/N8) | `/admin/produce` → `admin_produce.py` | None found in this audit (trigger + Gate C approve) | **KEEP** |
| Run Health | `/admin/run-health` → `GET /admin/acp/run-health` | Partial — same endpoint supports a tenant JWT to see only their own runs (`acp_health.py::_get_caller`) | **KEEP** — but fix bug #14 (wrong table) separately |
| Atomize (N2) | `/admin/atomize` → `POST /admin/atoms/decompose` → `v1_atoms.py::decompose()`, `owner_scope='platform'` | T5 (`run_t5_atomize`) — but T5 atomizes a tenant's OWN rewritten content (`owner_scope=tenant_id`), never the platform catalog | **KEEP — confirmed NOT legacy.** Sole source of platform-scope atoms; Marketplace + N4-N6 planning depend on it |
| Atom Curation | `/admin/curation` → `GET/PATCH /admin/atoms*`, `owner_scope=None` (staff, no filter) | `/portal/t6-atoms` (AA-431) — same backend, `owner_scope` forced to caller's own tenant_id | **KEEP — confirmed NOT legacy.** Staff cross-tenant + platform superset view; T6 is the scoped subset, not a replacement |
| Upload (S0) | `/admin/upload` → `admin_pipeline.py` ingest handlers | None — aa_internal-only raw ingestion (per AA-438-01) | **KEEP** |
| S1 Rewrite | `/admin/s1-rewrite` → `_execute_run_tour` → `graph.py` | None overlapping — tenant's own rewrite (T2) is a separate pipeline/table (`tenant_tour_versions`, no cost tracking, per AA-434) | **KEEP** — separate aa_internal content-authoring flow |
| Review Queue | `/admin/review` → `review_queue` + `approve_review`/`reject_review` | None found — T3 (tenant QA gate) is fully automatic, no manual tenant-facing review UI | **KEEP** |
| Brand Identity | `/admin/brand` → `admin_pipeline.py` brands handlers | **Not confirmed either way this session** — `tenant_brand_rules` exists per-tenant too, but no tenant-facing brand-editing UI was found or looked for | **KEEP for now** — re-check when AA-439 (Tenant tier) audits tenant-facing settings/brand pages |
| Master Content | `/admin/master-content` → `admin.py::get_tenant_details` (is_internal branch) | T1 Tour Selection (`/v1/tours/pool`) reads the *same* `published_tours` table | **KEEP** — different capability: admin manages (trash/restore/activate) the master catalog; T1 only browses it read-only for rewrite selection |
| Settings | `/admin/settings` → `admin_settings.py` | None | **KEEP** — but fix bug #16 (stale `pipeline_flow` list) separately |

**Net conclusion: zero sidebar items are confirmed legacy/redundant.** Nghiep's specific
suspicion (Atomize N2 / Atom Curation) was the most concrete candidate and is the one this
audit could actually disprove with code + live data — both operate on genuinely different
scope than their tenant-facing counterparts, not overlapping. Brand Identity is the one open
question, deferred to AA-439 rather than guessed at here.

---

## Reports index

- `AA-438-01-a0-a1-audit.md` — Upload (S0) → S1 Rewrite (A0→A1), DFS confirmation, the
  `pipeline_runs` stuck-`ingesting` root cause.
- `AA-438-02-a1-a2-audit.md` — S1 Rewrite → Review Queue (A1→A2), hitl gate mechanics, reject
  status-reset gap.
- `AA-438-03-a2-a3-audit.md` — Review Queue → Master Content (A2→A3), live approve test,
  partial-UPSERT bug, T1 filter gap, brand_audit evidence.
- `AA-438-04-dashboard-setting-audit.md` — Dashboard tabs, Tenants, Marketplace, Quarter Plan,
  Produce & Deliver, Run Health, Brand Identity, Settings, Atomize/Curation legacy
  investigation.

## Explicitly open items carried forward (not this audit's job to resolve)

- ADR-2026-038's actual text — never found in any of the 4 repos; needs a Notion/Linear lookup
  outside this environment.
- Brand_audit/DFS threshold strictness — a live data point exists (bug #10) but deliberately
  not investigated; flagged as its own follow-up task.
- Brand Identity's tenant-facing equivalent (if any) — deferred to AA-439.
- The 11 orphaned `review_queue` rows and the 72→71 `published_tours` gap — flagged, not
  chased down.
- Whether Pipeline Health's named services (Step Functions Pipeline, Validation Lambda, etc.)
  correspond to any AWS resource that still exists — not checked against live AWS in this task.
