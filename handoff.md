# AA-CIS-App Handoff — Session 54
Updated: 2026-06-04

## Status
- Branch: feature/aa-169-s2-auto-crash-recovery | Last commit: 4f04017
- ECS: UNKNOWN — verify before starting
- RDS: aa-cis-dev-db — UNKNOWN — verify before starting
- Migrations 052-060: NOT YET APPLIED (dev DB)
- Migration 061: created, not yet applied

## Completed This Session

### AA-169 — S2 Auto Crash-Recovery + Monitoring Fields + schema_versions fix

**DELIVERABLE 1 — ECS startup hook (api/main.py)**
- `_recover_stuck_s2_runs(pool, graph)` added as module-level function
- Queries acp_stage_runs JOIN acp_runs WHERE status='running', metadata?'checkpointer', updated_at < NOW()-2min
- Called in lifespan after graph init (skipped if graph init failed)
- `_do_resume_run` imported from router.py (already existed as module-level fn from AA-112)

**DELIVERABLE 2 — Monitoring fields (already implemented from prior session)**
- `current_iteration`: written by `_with_iteration_update()` in graph.py after each of 7 nodes
- `compute_saved_pct`: written in `_background()` after ainvoke (dataforseo + apify hits / 2)
- `apify_cache_hit`: returned True on cache-hit path in apify.py

**DELIVERABLE 3 — Migration 061**
- `api/migrations/061_fix_schema_versions_058.sql` created
- Backfills schema_versions row for 058 (ON CONFLICT DO NOTHING — safe, idempotent)

**Tests: tests/acp_s2/test_aa169.py — 12/12 green**
**tests/acp_s2/ — 23/23 green**
**Full suite: 383 passed, 24 failed (pre-existing baseline unchanged)**

### Branch
- feature/aa-169-s2-auto-crash-recovery pushed to origin
- NOT YET merged to develop — awaiting CI green

## Next Steps
1. Wait for CI to go green on feature/aa-169-s2-auto-crash-recovery
2. Merge → develop → trigger Deploy Dev
3. Apply migrations 052-061 on dev DB (start ECS + RDS first)
4. Verify: grep "startup_recovery" in ECS logs on restart
5. PR develop → main → Deploy Prod

## Open Issues
- Migrations 052-061 not yet applied to dev DB
- OPENAI_API_KEY needs rotation
- 24 pre-existing test failures (test_s2_idempotency, test_s2_semaphore,
  test_h3_rule_extractor, test_007_rls_isolation) — pre-existing
- feature/aa-112-s2-async-postgres-saver: DO NOT merge
- feature/aa-143-canary: DO NOT merge
- feature/aa-141-run-health-dashboard: DO NOT merge

## Cost Checklist (MANUAL — do not auto-run)
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1
aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
