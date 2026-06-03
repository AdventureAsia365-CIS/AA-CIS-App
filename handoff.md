# AA-CIS-App Handoff — Session 49
Updated: 2026-06-03

## Status
- Branch: feature/aa-112-s2-async-postgres-saver | Last commit: 63b8853
- ECS: api:246 (⚠️ STOP if still running)
- RDS: aa-cis-dev-db (⚠️ STOP if still running)
- Migration 055 NOT YET APPLIED — needs ECS running
- Migration 056 NOT YET APPLIED — needs ECS running (requires 055 first)
- Migration 057 NOT YET APPLIED — needs 055+056 first
- Migration 058 NOT YET APPLIED — canary tenant flags (is_canary, skip_hitl)
- Migration 059 NOT YET APPLIED — acp_stage_runs.metadata JSONB [AA-112]

## Completed This Session

### AA-112 — S2 AsyncPostgresSaver + Migration + Cache Tables (commit 63b8853)

**Branch**: feature/aa-112-s2-async-postgres-saver (pushed, DO NOT merge to develop — awaiting review)

**Changed files:**
- `services/acp/s2/graph.py` — replaced MemorySaver with AsyncPostgresSaver; returns `(graph, conn)` tuple
- `api/main.py` — lifespan unpacks `(graph, conn)`, stores `app.state.s2_pg_conn`, closes on shutdown
- `services/acp/s2/router.py` — metadata logging: fresh run logs `resume_from_iteration=0`; resume reads iteration from `graph.aget_state()` and logs actual value
- `api/migrations/059_s2_checkpoint_metadata.sql` — adds `metadata JSONB NOT NULL DEFAULT '{}'` to `acp_shared.acp_stage_runs`
- `tests/acp_s2/test_checkpointer.py` — 4 unit tests, all green

**Key design decisions:**
- Cache tables (raw_keyword_cache, raw_html_cache) NOT created — S2 tools already cache via `acp_silver_s2.visibility_reports` + S3
- Single psycopg3 connection for checkpointer (not a pool) — adequate given semaphore-guarded concurrency
- `psycopg.AsyncConnection.connect(database_url)` — no URL format conversion; `postgresql+psycopg://` is SQLAlchemy-only
- LangGraph creates its own checkpoint tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`) via `setup()` — separate from `acp_shared.pipeline_checkpoints`
- Metadata logging wrapped in try/except so graph never fails if migration 059 is pending

**Test results:**
```
4 passed, 2 warnings in 1.74s
tests/acp_s2/test_checkpointer.py::TestCheckpointerType::test_checkpointer_type PASSED
tests/acp_s2/test_checkpointer.py::TestMetadataLoggedFreshRun::test_metadata_logged_fresh_run PASSED
tests/acp_s2/test_checkpointer.py::TestMetadataLoggedResume::test_metadata_logged_resume PASSED
tests/acp_s2/test_checkpointer.py::TestMetadataLoggedResume::test_metadata_resume_defaults_zero_when_no_state PASSED
```

## Prior Sessions — Open Issues (carried forward)

### AA-143 — Synthetic Canary S0→S1 Skeleton Wave 0 (commit 1cd64e0)
**Branch**: feature/aa-143-canary (pushed, DO NOT merge)
- Prerequisites before deploy: apply migrations 055 → 056 → 057 → 058 in order

### AA-141 — Run-Health Dashboard + SLO/Alerting (commit 6546ac0)
**Branch**: feature/aa-141-run-health-dashboard (pushed, DO NOT merge)
- Prerequisites before testing: apply migrations 052 → 053 → 054 → 055 → 056 → 057

## Known Open Issues (carried forward)
- Migration 052 not yet applied → source_status/master_status columns missing
- Migration 053 not yet applied → notifications table missing
- Migration 054 not yet applied → country column missing on tenants
- Migration 055 not yet applied → acp_stage_runs + cost columns
- Migration 056 not yet applied → event_id idempotency (requires 055 first)
- Migration 057 not yet applied → lifecycle columns for stuck-run detection (requires 055+056 first)
- Migration 058 not yet applied → canary tenant flags
- Migration 059 not yet applied → acp_stage_runs.metadata [AA-112]
- OPENAI_API_KEY needs rotation (exposed in session 39)
- API Gateway 29s timeout on long tour rewrites
- EventBridge rule for S4 trigger needs update in AA-CIS-Infra Terraform (source: acp.hitl)

## Prerequisites for AA-112 to work end-to-end
1. Apply migrations 052 → 053 → 054 → 055 → 056 → 057 → 058 → 059 in order
2. ECS deploy new image after CI green
3. Verify checkpointer tables created: `\dt checkpoints checkpoint_writes checkpoint_blobs`

## Cost Checklist (MANUAL — do not auto-run)
```
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1
aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
```
