# handoff.md — AA-CIS-App
Updated: 12/05/2026 | ECS task def: api:108 | CI: #180 | Commit: 0ea1d62

## STATE
- Branch: develop
- ECS: RUNNING (api:108, desired-count=1) — session continuing
- RDS: AVAILABLE
- DB: 7 tours published (clean after truncate + re-publish)

## DONE SESSION 6 (12/05/2026)

### AA-26 ✅ — 6 bugs fixed
| Bug | Fix | Commit |
|-----|-----|--------|
| BUG-5: seo_context JOIN on keyword_search instead of tour_id | Fixed JOIN condition | 3b5ec63 |
| BUG-6: Upload → S3 only, pipeline never triggered | Added POST /ingest-s3 endpoint | 02d722f |
| Catalog highlights/activities bullet rendering | tryParseJson + newline sanitization | 42ead00 |
| Content length limits (2-3 sentence cap) | Removed limits from prompts.py | db906a1 |
| Export step never called after validation | Call process_export() in run_tour() | d287cfe |
| Dashboard counts inconsistent across tabs | All → published_tours source of truth | 60344a4 |

### AA-41 ✅ — ACP schemas + system rules
- 5 ACP schemas created in DB
- 10 system rules created

### Pipeline stability fixes
- `_pipeline_semaphore = Semaphore(2)` — caps concurrent LLM runs, prevents DB pool exhaustion on bulk upload
- `tours_passed` double-count fixed — removed from run_tour, process_export owns it via COUNT(published)
- `error_message` logging — _run_tour_safe writes exception to pipeline_runs.error_message on failure
- 3-retry with exponential backoff (2s, 4s) in _run_tour_safe before marking failed
- Background tasks: _run_tour_safe replaces bare run_tour call

### Dashboard metrics
- All tour counts (Tours Processed, Total Tours, Auto-Passed) → `gold_aa_internal.published_tours`
- LLM Calls → `generated_content`
- Cost → `pipeline_runs` accumulated
- Source annotation (↳ table · scope) on every stat card

### Manual DB ops
- Truncated all tours + re-published 7 clean tours (quality 10.0 each)
- Manually exported: Enchanted Escapes, Delights of Sri Lanka, Tea Wildlife & Beach, North-East, Sri Lanka Retreat

### ECS logs finding
- Logs → `/ecs/aa-cis-dev` (NOT `/ecs/aa-cis-dev-api` which is empty)
- Stream prefix: `api/api/<task-id>`

## NEXT SESSION — P0 FIRST

### P0: AA-40 — Terraform EventBridge + S3 (AA-CIS-Infra repo)
- Repo: AA-CIS-Infra (separate from AA-CIS-App)
- Target: EventBridge rule on S3 PutObject `raw-inbox/` → trigger /ingest-s3 OR Lambda
- Check if EventBridge already deployed but misconfigured

### P1: AA-42 — CIS EventBridge publish + manifest.json
- Publish pipeline events to EventBridge on tour export
- Generate manifest.json in S3 gold path per published tour
- M1 gate dependency

### Investigate: SEO 0% after truncate
- DataForSEO not triggering after re-publish
- Check: seo_context table empty? SEO node in LangGraph graph firing?
- Likely: run_tour doesn't call SEO enrichment — check graph.py has SEO node wired

## SESSION START COMMANDS (if ECS/RDS stopped)
```bash
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 1 --profile pqnghiep-admin --region us-west-1
aws rds start-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
```

## KEY ENDPOINTS
- API: https://api-cis.lumiguides.it.com
- Frontend: https://aa-cis.lumiguides.it.com (Vercel)
- Langfuse: https://langfuse.lumiguides.it.com
