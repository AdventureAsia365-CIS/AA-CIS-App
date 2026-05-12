# handoff.md — AA-CIS-App
Updated: 12/05/2026 | ECS task def: api:114 | CI: #188 | Commit: a273a31

## STATE — SESSION CLOSED
- Branch: develop
- ECS: STOPPED (desired-count=0)
- RDS: STOPPED
- DB: 15 published tours | Haiku avg 9.75 | Sonnet avg 10.0 | 12 pipeline_runs completed

## IAM STATUS
- SSO AA-Admin + ECS task role: aws-marketplace permissions for Bedrock Sonnet granted
- T1 Sonnet (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`): ACTIVE
- T2 Haiku (`us.anthropic.claude-haiku-4-5-20251001-v1:0`): ACTIVE
- T3 GPT-4.1: last-resort fallback only

## DONE SESSION 7 (12/05/2026) — ALL CLOSED

### AA-20 ✅ — Cost tab $0.0000 fix
- `pipeline_runs.llm_model` was never written → added to run_tour() UPDATE
- Replaced hardcoded COST_PER_CALL with real pipeline_runs queries
- Model name normalization via CASE WHEN LIKE '%haiku%' → 'claude-haiku-4-5'
- avg_cost_per_run = SUM(cost_usd)/COUNT(*) from pipeline_runs WHERE cost_usd > 0

### AA-21 ✅ — Quality tab avg_score 0 → —
- `parseFloat(null ?? 0)` coerced null → 0 before null check — fixed

### AA-50 ✅ — SEO step wired in direct pipeline flow
- Added `process_seo()` call in run_tour() before _rewrite_tour()
- Seed: `"{country} tours"` (BUG-3 rule) → seo_data passed into LangGraph state
- step_name = 'content_generation' written to pipeline_runs
- SEO verified: seo_context has 1 row (country-level design, acceptable)

### AA-12 ✅ — LLM provider + T1/T2 logging
- llm_provider hardcoded 'bedrock' even for GPT-4.1 runs → fixed, derived from model name
- Improved fallback logs: t1_failed_trying_t2, t2_failed_trying_t3, t3_fallback_used

### AA-51 ✅ — Model selection UI + auto-upgrade
- Upload UI: Model Tier selector (Haiku Default $0.002 / Sonnet Premium $0.02)
- LLMClient routing: "haiku" → T2 direct; "sonnet" → T1→T2→T3
- Auto-upgrade: Haiku score < 8.5 → transparently retry with Sonnet
  (threshold configurable via AUTO_UPGRADE_THRESHOLD env var)
- model_tier threaded end-to-end: UI → ingest-s3 → TourRunRequest → LangGraph state → LLMRequest

### Other fixes this session
- Volume tab: Auto-Passed = published_count (was summing pipeline_runs.tours_passed)
- tours_passed double-count fixed; _pipeline_semaphore Semaphore(2)
- error_message + 3-retry with backoff in _run_tour_safe
- Dedup working: raw_tours may have duplicates; published_tours correctly deduplicated
- llm_provider now writes actual provider ("openai" when GPT-4.1, "bedrock" otherwise)

## NEXT SESSION — P0 FIRST

### P0: AA-40 — Terraform EventBridge + S3 (AA-CIS-Infra repo)
- Repo: AA-CIS-Infra (SEPARATE from AA-CIS-App — different directory)
- Target: S3 PutObject on `raw-inbox/` → EventBridge rule → trigger /ingest-s3
- Check: EventBridge may already be deployed but misconfigured
- Action: `cd ~/projects/aa-cis-infra` (or wherever the Infra repo is)

### P1: AA-42 — CIS EventBridge publish + manifest.json (M1 gate)
- Publish pipeline events to EventBridge on tour export
- Generate manifest.json in S3 gold path per published tour
- M1 gate dependency — blocks release

### P2: AA-51 followup — model_tier in Dashboard metrics
- Show T1/T2/T3 tier per run in dashboard (fallback_used flag)
- Add tier column to model_usage response

## SESSION START COMMANDS
```bash
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 1 --profile pqnghiep-admin --region us-west-1
aws rds start-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
aws sts get-caller-identity --profile pqnghiep-admin
```

## KEY ENDPOINTS
- API: https://api-cis.lumiguides.it.com
- Frontend: https://aa-cis.lumiguides.it.com (Vercel)
- Langfuse: https://langfuse.lumiguides.it.com
- ECS logs: /ecs/aa-cis-dev (stream prefix: api/api/<task-id>)

## DB SCHEMA QUICK REF (verified 12/05/2026)
- shared.pipeline_runs: batch_id, status, tours_total/passed/failed, cost_usd, llm_model, llm_provider, step_name, error_message
- silver_aa_internal.raw_tours: tour_id, src_name, country, batch_id, pipeline_status
- silver_aa_internal.generated_content: tour_id, version_num, status, model_editorial, quality_score
- gold_aa_internal.published_tours: id, tour_id, aa_name, quality_score, published_at
- silver_aa_internal.seo_context: tour_id, keyword_search, top_keywords, fetched_at
