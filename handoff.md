# AA-CIS-App Handoff — Session 50
Updated: 2026-06-03

## Status
- Branch: feature/aa-122-s3-context-guardrail | Last commit: d664e6b
- ECS: api:246 (⚠️ STOP if still running)
- RDS: aa-cis-dev-db (⚠️ STOP if still running)
- Migrations 052–059: NOT YET APPLIED (from session 49)
- Migration 060: NOT YET APPLIED (AA-122, requires migration 059 applied first)

## Completed This Session

### AA-122 — S3 Lambda Context Size Guardrail (commits 2936947, d664e6b)

**Branch**: feature/aa-122-s3-context-guardrail (pushed — awaiting CI green → merge to develop)

**What changed:**
- `api/migrations/060_acp_run_context_s3_keys.sql` — ADD COLUMN s2_keywords_s3_key TEXT + s2_report_s3_key TEXT
- `api/schemas/run_context.py` — s2_keywords_s3_key + s2_report_s3_key on RunContext + S2StagePayload
- `api/services/run_context_db.py` — s2 stage columns + get_run_context_validated reads new fields
- `services/acp/s2/tools/synthesize.py` — writes s2_keywords_s3_key (from dataforseo state) to run_context
- `services/acp_s3/run_context.py` — reads s2_keywords_s3_key + s2_report_s3_key from DB row
- `services/acp_s3/handler.py` — load_context_field helper + S3_THRESHOLD_BYTES=512000 + size check
- `services/acp_s3/tests/test_aa122.py` — 6 tests (all green)

**Key design:**
- If `context_bytes > 512_000` → resolve s2_keyword_research from S3 using s2_keywords_s3_key
- Graceful fallback: if s2_keywords_s3_key is None (pre-migration runs), use inline value
- S3 bucket: acp-silver-867490540162 (env: S3_SILVER_BUCKET)

**Tests:** 50/50 acp_s3 tests pass (6 new + 44 existing)

**Critical bugs found during audit (NOT fixed — separate tickets needed):**
1. `s2_keyword_research.keywords` key never populated by S2 → planner always gets empty top_18 keywords (keywords live in S3 only)
2. planner.py `_SONNET` variable = Haiku model ID (naming bug → 7.5x cost overcount)
3. DataForSEO format mismatch: S3 has `search_volume` but planner reads `vol_m1`/`vol_m2`
4. H-3 lesson confidence threshold (≥0.80) not enforced programmatically

## Prior Sessions — Open Issues (carried forward)

### AA-112 — S2 AsyncPostgresSaver + Migration + Cache Tables (commit 63b8853)
**Branch**: feature/aa-112-s2-async-postgres-saver (pushed, DO NOT merge — awaiting review)

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
- Migration 060 not yet applied → acp_run_context s3 offload keys [AA-122]
- OPENAI_API_KEY needs rotation (exposed in session 39)
- API Gateway 29s timeout on long tour rewrites
- EventBridge rule for S4 trigger needs update in AA-CIS-Infra Terraform (source: acp.hitl)
- s2_keyword_research.keywords always empty → planner top_18 always empty (NEW — see AA-122 audit)
- _SONNET var in planner.py = Haiku model (naming+cost bug)

## Next Steps for AA-122 to go live
1. CI green on feature/aa-122-s3-context-guardrail
2. Merge feature/aa-122-s3-context-guardrail → develop
3. Apply migrations 052 → 053 → 054 → 055 → 056 → 057 → 058 → 059 → 060 in order
4. ECS deploy new image after CI green on develop
5. Linear: AA-122 → Done

## Cost Checklist (MANUAL — do not auto-run)
```
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1
aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
```
