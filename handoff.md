# AA-CIS-App Handoff — Session 55
Updated: 2026-06-04

## Status
- Branch: develop | Last main commit: 7db3aac
- ECS: api:271 RUNNING (desiredCount=1) — STOP after session
- RDS: aa-cis-dev-db RUNNING — STOP after session
- Deploy Prod #26925352670: SUCCESS ✅
- Migrations 058+061 APPLIED on dev DB ✅ (052-057, 059-060 applied previously)

## Completed This Session

### AA-169 — S2 Auto Crash-Recovery + Monitoring Fields — SHIPPED TO PROD ✅

**feature/aa-169-s2-auto-crash-recovery → develop → main → Deploy Prod**

- `_recover_stuck_s2_runs(pool, graph)` in api/main.py lifespan — ECS startup hook
- `_with_iteration_update()` wraps 7 LangGraph nodes → writes current_iteration per step
- `compute_saved_pct` written after ainvoke (dataforseo + apify cache ratio)
- Migration 061 applied: schema_versions row for 058 backfilled ✅
- ECS log confirmed: `startup_recovery_none` on api:271 restart ✅

**Tests: 12/12 green (test_aa169.py) | 23/23 green (acp_s2/) | 383 passed total**

### CI/CD chain
- CI #26925124216 ✅ | Deploy Dev #26925124227 ✅ | Deploy Prod #26925352670 ✅
- ECS task def: api:271

## Open Issues
- OPENAI_API_KEY needs rotation
- 24 pre-existing test failures (test_s2_idempotency, test_s2_semaphore,
  test_h3_rule_extractor, test_007_rls_isolation) — pre-existing
- feature/aa-112-s2-async-postgres-saver: DO NOT merge
- feature/aa-143-canary: DO NOT merge
- feature/aa-141-run-health-dashboard: DO NOT merge

## Cost Checklist (MANUAL — do not auto-run)
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1
aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
