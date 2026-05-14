# AA-CIS-App — Claude Code Context
# Updated: 14/05/2026 | ECS api:137 | CI #218

## LIVE STATE
- API: https://api-cis.lumiguides.it.com ✅ (via API Gateway owq9as3wjl)
- Frontend: https://aa-cis.lumiguides.it.com ✅ (Vercel)
- ECS task def: api:137 | CI #218 green | Deploy Dev #130
- AWS: STOPPED (ECS 0/0, RDS stopped)
- API Gateway: owq9as3wjl | Lambda Authorizer: aa-cis-dev-authorizer
- DB: PostgreSQL 15, aa_cis_dev, secret: aa-cis/dev/rds (plain DSN)
- Tours: 7 in catalog (WanderLux dev session, 15 published Sri Lanka) | 5 tenants | avg quality 9.9
- Models: Bedrock Haiku 4.5 (primary) → Sonnet 4.5 (quality fallback)

## STACK
- Backend: FastAPI (api/main.py → api.main:app), asyncpg, Redis
- Frontend: Next.js React 19, Vercel deploy
- AI: AWS Bedrock (us-west-1), LangGraph orchestration
- Infra: ECS Fargate, RDS PostgreSQL 15, S3, Lambda, Step Functions

## DB SCHEMA (Medallion)
shared.*              → tenants, pipeline_runs, membership_plans, tenant_brand_rules
silver_aa_internal.*  → raw_tours, generated_content, seo_context
gold_aa_internal.*    → published_tours

silver_{tenant_slug}.* → per B2B tenant (same structure)
gold_{tenant_slug}.*

### Key columns (verified 11/05/2026):
raw_tours:          tour_id, tenant_id, src_name, country, duration, price_raw,
                    src_itineraries, src_highlights, src_summary, pipeline_status(enum)
generated_content:  tour_id, aa_name, aa_subtitle, aa_summary, aa_description,
                    aa_highlights(jsonb), aa_itineraries, seo_title, seo_meta,
                    model_editorial, model_schema, status(enum), created_at
published_tours:    tour_id, generated_content_id, aa_name, aa_subtitle,
                    aa_itineraries, seo_title, seo_meta, quality_score,
                    s3_gold_path, published_at
seo_context:        tour_id, keyword_search, top_keywords(jsonb), keyword_ideas(jsonb),
                    provider(enum), fetched_at
pipeline_runs:      id, tenant_id, batch_id, status, cost_usd, llm_model,
                    tours_total, tours_passed, started_at, completed_at

## FASTAPI ROUTE ORDER — CRITICAL
/{id}/full MUST come BEFORE /{id} — FastAPI greedy matching.
NEVER reorder these routes.

## safe() PATTERN
Always use safe() for UUID and Decimal in JSON responses:
from api.utils import safe
return {"id": safe(tour.tour_id), "cost": safe(tour.cost_usd)}

## EXCEL PARSER RULES
File: api/services/excel_parser.py
- COLUMN_MAP: source Excel column name → DB field name
- Column "name" → src_name | "price" → price_raw | "itineraries" → src_itineraries
- Multi-header Excel: row 1 = group labels (skip), row 2 = actual column names
- Provider: title-case normalization ("horizon voyages" → "Horizon Voyages")
- Dedup by src_name + provider when no tour_id_external

## BEDROCK CONFIG
Primary: us.anthropic.claude-haiku-4-5-20251001-v1:0 (~$0.002/tour)
Fallback: us.anthropic.claude-sonnet-4-5-20251001-v1:0 (~$0.02/tour)
Region: us-west-1 | IAM: ECS task role has bedrock:InvokeModel

## SEO SEED RULE (BUG-3 fix)
DataForSEO seed keyword must be country-based, NOT tour name:
seed = f"{tour.country} tours" if tour.country else tour.src_name

## PIPELINE ARCHITECTURE
S3 Bronze upload → Ingestion Lambda → shared.pipeline_runs (status=ingesting)
→ Step Functions (bypassed — tech debt AA-22) → /v1/pipeline/run-tour (ECS)
→ LangGraph: validate → generate → evaluate → seo_context
→ Export: gold layer write + pipeline_runs status=completed

## KNOWN TECH DEBT — DO NOT BREAK
- api_task_def_arn hardcoded :21 in main.tf (AA-CIS-Infra) — do not change
- Step Functions deployed but bypassed — direct API flow only (AA-22)
- webhook_deliveries = 0 — deferred P2
- content_exports table does not exist in shared schema

## CI/CD
- Push to develop → GitHub Actions ci.yml → build → deploy-dev.yml → ECR push → ECS deploy
- Image tag: always :latest (never commit hash)
- Vercel: manual deploy via `vercel --prod` for frontend (Hobby plan)

## TESTING
pytest tests/ -v
104 integration tests + 23 E2E Playwright tests baseline

## ACTIVE WORK — 14/05/2026
Session 11 COMPLETE. Phase 4 COMPLETE.
Last commit: 85ed50d

### ✅ Done Session 11
- AA-57: Tenant detail bugs (quality_score, pipeline→activity tab, aa_internal tours)
- AA-23: Remove Langfuse (~$8/mo saved)
- AA-22: SF fallback router (threshold=15) + HITL IAM fix
- AA-13: API Gateway REST + Lambda Authorizer + 4 usage plans + custom domain
- AA-60: Dashboard all-tenant metrics + all X-API-Key routing fixes

### 🔴 Next Session Priority
1. AA-11: Phase 3 Report DOCX → Ms. Thu (Claude Chat, no AWS needed)
2. Regenerate aa_internal API key: POST /admin/tenants/{id}/rotate-key
3. Disable WAF after verifying API GW rate limiting stable
4. Phase 5 planning: Webhook notifications, B2B self-signup

### ⚠️ Open Issues
- AA-36: No char limits on rewrite fields — Backlog
- api_task_def_arn hardcoded :21 in main.tf — AA-CIS-Infra (AA-22 tech debt)

## Session 11 Close — 14/05/2026
- ECS desired=0, RDS stopped
- Task def: api:137 | CI #218 | Deploy #130 | Commit: 85ed50d
- Phase 4 COMPLETE: AA-13 API Gateway done
- API Gateway: owq9as3wjl | custom domain: api-cis.lumiguides.it.com
