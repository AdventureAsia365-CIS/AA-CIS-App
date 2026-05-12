# handoff.md — AA-CIS-App
Updated: 12/05/2026 | ECS task def: api:113 | CI: #186 | Commit: 7fd1ba3

## STATE
- Branch: develop
- ECS: RUNNING (api:113, desired-count=1)
- RDS: AVAILABLE
- DB: 12 tours published | avg quality 9.71 | Sonnet T1 active (score 10.0)

## IAM STATUS
- SSO AA-Admin + ECS task role: aws-marketplace permissions for Bedrock Sonnet granted
- T1 Sonnet (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`): WORKING as of 09:44 UTC
- T2 Haiku (`us.anthropic.claude-haiku-4-5-20251001-v1:0`): WORKING (always was)
- T3 GPT-4.1: last-resort fallback only

## DONE SESSION 7 (12/05/2026)

### AA-20 ✅ — Cost tab $0.0000 fix
- `pipeline_runs.llm_model` was never written → NULL for all rows
- Added `llm_model = COALESCE($6, llm_model)` to run_tour() UPDATE
- Replaced hardcoded COST_PER_CALL dict with real queries from pipeline_runs
- Model name normalization: CASE WHEN LIKE '%haiku%' → 'claude-haiku-4-5' etc.
  (groups old shortnames + new full Bedrock IDs into same row)
- avg_cost_per_run = SUM(cost_usd)/COUNT(*) from pipeline_runs WHERE cost_usd > 0

### AA-21 ✅ — Quality tab avg_score showing 0 instead of —
- `parseFloat(m.avg_score ?? 0)` coerced null → 0 before null check
- Fix: `score = m.avg_score != null ? parseFloat(m.avg_score) : null`
- Null shows as `—` in muted grey; non-null still colour-coded

### AA-50 ✅ — SEO step not called in direct pipeline flow
- SEO only existed in Step Functions definition; direct /run-tour flow skipped it
- Added `process_seo()` call inside run_tour() before _rewrite_tour()
- Seed keyword: `"{country} tours"` (BUG-3 rule)
- seo_data passed into LangGraph initial_state["seo"] for keyword injection
- step_name = 'content_generation' now written to pipeline_runs
- SEO verified working: `seo_inserted id=2b55962c` on first run after deploy

### AA-12 ✅ — LLM provider investigation + logging
- `llm_provider` was hardcoded to 'bedrock' via COALESCE even when GPT-4.1 ran
- Fix: derive `actual_provider = "openai" if "gpt" in model_name else "bedrock"`, pass as $7
- Improved fallback log messages:
  - `t1_failed_trying_t2: model=... error=...`
  - `t2_failed_trying_t3: model=... error=...`
  - `t3_fallback_used: model=gpt-4.1 reason=T1 and T2 both failed`
- Root cause of 08:51 GPT-4.1 run: my temp change to anthropic.* base model IDs
  (which require inference profiles) — reverted, not a recurring issue
- `model_hint` field in LLMRequest documented as dead code (ignored by LLMClient)

### AA-51 🆕 — Model selection UI (new issue, not started)
- Dashboard should show which tier (T1/T2/T3) ran per tour
- Add `fallback_used` + `tier` fields to pipeline_runs or generated_content

### Other fixes this session
- Volume tab: Auto-Passed = published_count (was summing pipeline_runs.tours_passed)
- Pass Rate always 100% (published/published) — semantically correct
- tours_passed double-count: removed increment from run_tour, process_export owns it
- _pipeline_semaphore = Semaphore(2) caps concurrent LLM runs
- error_message + 3-retry with backoff in _run_tour_safe

## NEXT SESSION — P0 FIRST

### P0: AA-40 — Terraform EventBridge + S3 (AA-CIS-Infra repo)
- Repo: AA-CIS-Infra (separate from AA-CIS-App)
- Target: EventBridge rule on S3 PutObject `raw-inbox/` → trigger /ingest-s3
- Check if EventBridge already deployed but misconfigured

### P1: AA-42 — CIS EventBridge publish + manifest.json
- Publish pipeline events to EventBridge on tour export
- Generate manifest.json in S3 gold path per published tour
- M1 gate dependency

### P2: AA-51 — Model selection UI
- Show T1/T2/T3 tier per run in dashboard
- Add fallback_used flag to metrics response

## SESSION START COMMANDS (if ECS/RDS stopped)
```bash
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 1 --profile pqnghiep-admin --region us-west-1
aws rds start-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
```

## KEY ENDPOINTS
- API: https://api-cis.lumiguides.it.com
- Frontend: https://aa-cis.lumiguides.it.com (Vercel)
- Langfuse: https://langfuse.lumiguides.it.com
- ECS logs: /ecs/aa-cis-dev (stream prefix: api/api/<task-id>)
