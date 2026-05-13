# AA-CIS-App — Claude Code Context
# Updated: 13/05/2026 | ECS api:121 | CI #199

## LIVE STATE
- API: https://api-cis.lumiguides.it.com ✅
- Frontend: https://aa-cis.lumiguides.it.com ✅ (Vercel)
- ECS task def: api:121 | CI #199 green
- ECS task ARN: arn:aws:ecs:us-west-1:867490540162:task/aa-cis-dev-cluster/079caf732a524670a20382ccbcb1a026
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

## ACTIVE WORK — 13/05/2026
Session 9 COMPLETE. All Tenant Portal work done.
Commit range: 3847850→9509a77 (12 commits)

### ✅ Done Session 9
- B1 b0cf6a4 | B2 00ed8cc,9509a77 | B3 7f969bd | B4 3847850 | B5 ff138f7
- C1 fa4cbb9 | C2 a6f1426 | C3 1f7fd13 | C4 61e67a9 | C5 3d69941 | C6 bcd992d
- D1 c5dbe83 | D2 2c02ec3 | D3 754e995

### 🔴 Next Session Priority
1. AA-40: Terraform EventBridge + S3 (AA-CIS-Infra repo) — M0 blocker
2. AA-42: CIS publish EventBridge event + manifest.json — M1 gate
3. AA-13: API Gateway — due 31/5
4. Bug 3: quality_score=0.00 — CloudWatch investigate (ECS must be running)

### ⚠️ Open Issues
- AA-28: Multi-select export (Admin+Tenant) — Backlog
- AA-36: No char limits on rewrite fields — Backlog
- Bug 3: quality_score=0.00 all rewrites — needs investigation
- api_task_def_arn hardcoded :21 in main.tf — AA-CIS-Infra (AA-22 tech debt)
## Session 10 Close — 13/05/2026
- ECS desired=0, RDS stopped
- Task def: api:127 | CI #208 | Commit: f070fb4
- M1 COMPLETE: AA-40/42/39 done
- UI Backlog done: AA-27/29/24/28
- Vercel auto-deploy: main → production, develop → preview (Deploy Hook set)
- Next: AA-13 API Gateway (due 31/5)
