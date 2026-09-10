# AA-544 Stage 1 — first pool-switch canary: `GET /v1/publish-log/pending`

Part of AA-544's approved 7-stage rollout. Stage 1 = wire exactly ONE low-risk `/portal/*` route
to the new `aa_app_user` pool, behind a default-off flag, before expanding further.

## Decisions

- **Route chosen: `GET /v1/publish-log/pending`** (`list_pending()`, `v1_publish.py`), not `GET
  /v1/tours` (Round 2's original suggestion). Live-DB audit before picking found Round 2's pick
  would have been wrong: `gold_aa_internal.published_tours` is 100% owned by the `aa_internal`
  sentinel tenant today (the real architecture moved to `tenant_tour_versions`, AA-425/500) — a
  real tenant's RLS-scoped query against it (or the `raw_tours` it joins, also
  sentinel-owned + `FORCE RLS`) would silently return `NULL`/empty results, not an error. Checked
  2 more obvious candidates (`GET /v1/tours/my-versions`, `GET /v1/billing`) — both `JOIN` (not
  `LEFT JOIN`) straight into `published_tours`, so under real RLS they'd return **completely
  empty** for every tenant — `my-versions` is literally "My Catalog," the tenant portal's core
  feature. All 3 ruled out. `GET /v1/publish-log/pending` was picked because all 4 tables it
  touches (`content_piece`, `angle_gate_request`, `angle_gate_option`, `publish_log`) are owned
  by the SAME tenant end-to-end (T8→T9→T11, no shared-pool/admin-owned crossover) — no
  JOIN-silently-empties-or-nulls risk — 3 of the 4 have real RLS enabled (`app.tenant_id`, the
  live GUC), already GRANTed to `aa_app_user` in Stage 0, GET-only (no write risk), and it's real
  live traffic (`/portal/t11-publish`). `GET /v1/quota` was also considered and rejected: simpler
  and zero-JOIN-risk, but its target table (`shared.tenant_rewrite_usage`) has no RLS at all — a
  leak test there would validate nothing about the RLS+GUC mechanism — and it also turned out to
  have no real frontend caller today (dead UI, per `ApiTab.tsx`'s own comment).
- **No Terraform/ECS task-def change.** Rather than wiring a new `DATABASE_URL_APP_USER` secret
  through the ECS task definition (a second repo, a second deploy pipeline, for a 1-route
  canary), the new pool's DSN is fetched directly via `boto3` Secrets Manager at app startup —
  the exact same pattern `v1_integrations.py`'s `_get_secret()` already uses for CMS credentials,
  just applied to `aa-cis/dev/rds-app-user` (Stage 0's secret) instead.
- **Feature flag via Redis, not an env var.** An env-var flag would need a new ECS task-def
  revision (redeploy) to toggle either direction. A Redis key (`aa544:stage1:publish_pending_pool`,
  fail-closed on any read error) mirrors `rate_limit_middleware`'s existing `tenant_meta` cache
  pattern (AA-432) — toggle instantly, no deploy, in either direction.
- **`SET LOCAL`, never session-level.** `app.tenant_id` is set via `set_config(..., true)` inside
  an explicit `asyncpg` transaction (`acquire_scoped_conn()`), scoped to that one transaction —
  this is the direct fix for the exact risk AA-544's own investigation flagged as the worst case
  ("GUC leak on a reused pooled connection"). Verified, not just asserted — see Live-verify below.

## Changed

- New `api/core/aa544_tenant_pool.py` — `create_tenant_pool()` (best-effort second pool),
  `stage1_flag_enabled()` (fail-closed Redis check), `acquire_scoped_conn()` (the pool-selection +
  transaction-scoped GUC helper). Explicitly documented as canary-scoped — not to be imported into
  other routers ahead of Stage 2's own report-then-confirm step.
- `api/main.py` — `lifespan()` creates `app.state.tenant_pool` (best-effort, `None` on any
  failure) alongside the existing `app.state.pool`; closes it on shutdown if it came up.
- `api/routers/v1_publish.py::list_pending()` — now acquires its connection via
  `acquire_scoped_conn()` instead of `request.app.state.pool` directly. Query text unchanged.
  Logs `used_tenant_pool` per call for observability.
- New `tests/integration/test_aa544_stage1_tenant_pool_leak.py` — real-RDS concurrent-tenant leak
  test, skipped by default (CI has no RDS network path), run manually with
  `AA544_RUN_REAL_RDS_TESTS=1` from inside the ECS task.

## Tradeoffs

- The canary route (`GET /v1/publish-log/pending`) has genuinely low traffic today (T11 Publish
  tab, not the highest-traffic tenant page) — a deliberate choice for Stage 1 (prove the
  mechanism with real but limited blast radius), not necessarily the most "representative" route.
  Stage 2+ picks a higher-traffic route once this one has soaked.
- Did not generalize `acquire_scoped_conn()` into a decorator/dependency usable by every router
  yet — Stage 1 is explicitly a 1-route canary; premature generalization would make it harder to
  isolate a regression to exactly this one route if something goes wrong.

## Should know

- **Live-verify, real RDS dev, before any HTTP-level test (via ECS exec, independent of deployed
  app code)**: 300 concurrent coroutines, pool `max_size=2` (heavy physical-connection reuse
  forced), random tenant per call across `wanderlux-travel` (real, 4 approved+unpublished
  blog/facebook pieces after the real query's own channel+publish filters — not the raw "8
  approved" count from an earlier, less precise check), `exploreasia-co` (real, 0 rows), and 8
  synthetic tenant IDs matching no real row. Result: **0 errors, 0 leaks** — every non-wanderlux
  call saw exactly 0 rows every time, wanderlux saw exactly 4 every time, GUC readback always
  matched the tenant that set it. Re-ran at 60 iterations first (also 0 errors) before scaling to
  300 for stronger confidence.
- **Full end-to-end HTTP verify (real tenant JWT, real domain, flag ON → OFF → deleted)**: pending
  until this PR is deployed — the leak test above runs independently of the deployed app (raw
  asyncpg against RDS), but confirming the actual `GET /v1/publish-log/pending` HTTP response is
  byte-identical with the flag on vs. off requires the new code to be live in ECS first. Will be
  done as a follow-up comment on AA-544 post-deploy, before declaring Stage 1 fully verified.
- Default state after this PR merges and deploys: flag unset in Redis → `stage1_flag_enabled()`
  returns `False` → `acquire_scoped_conn()` falls back to `app.state.pool` (`aa_cis_admin`) →
  **identical behavior to before this PR**, for this route and every other route. Turning the
  canary on is a separate, deliberate `redis-cli SET aa544:stage1:publish_pending_pool true` step,
  not something this PR does by merging.
