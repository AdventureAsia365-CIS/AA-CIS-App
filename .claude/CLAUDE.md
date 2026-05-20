# AA-CIS-App — Claude Code Context
# Updated: 21/05/2026 | ECS api:151 | CI #241

## LIVE STATE
- API: https://api-cis.lumiguides.it.com ✅ (via API Gateway owq9as3wjl)
- Frontend: https://aa-cis.lumiguides.it.com ✅ (Vercel)
- ECS task def: api:151 | CI #241 green | Deploy Dev #147
- AWS: STOPPED (ECS desired=0, RDS stopped)
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

## ACTIVE WORK — 21/05/2026
Session 22 COMPLETE. AA-45 COMPLETE.
Last commit: ae2ba56 (AA-CIS-App) | 2a37231 (AA-ACP-App)

### ✅ Done Session 22 (AA-45 — S3 Campaign Planner)
- services/acp_s3/: Lambda handler — skeleton-then-expand (Sonnet), ads (Haiku), 5 validators, 3-tier lessons
- api/routers/v1_s3.py: POST /v1/s3/run, GET /v1/s3/runs/{id}, POST /v1/hitl/gate2/{id}/approve|reject
- migrations/versions/031_acp_silver_s3_v2.sql: ads_plan + acp_run_context + acp_lessons_agency/shared + ALTER content_calendars
- Gate 2 HITL: audit_log mandatory, NEVER auto-approve, notes required on reject, double-submit 409 guard
- Portal page AA-ACP-App: src/app/(admin)/workspace/s3/review/page.tsx — calendar + ads accordion + funnel bar + approve/reject modals
- CI #241 ✅ | Deploy Dev #147 ✅

### 🔴 Next Session Priority (Session 23)
1. Apply migration 031 via S3-mediated ECS exec (RDS must be running FIRST)
2. Deploy Lambda aa-cis-dev-acp-s3-campaign-planner via AA-CIS-Infra Terraform
3. AA-89: B2B self-approval — migration 021

### ⚠️ Open Issues
- Migration 031 NOT yet applied to live DB — apply when RDS started next session
- Lambda aa-cis-dev-acp-s3-campaign-planner NOT yet deployed to AWS (Infra work pending)
- AA-36: No char limits on rewrite fields — Backlog
- api_task_def_arn hardcoded :21 in main.tf — AA-CIS-Infra (AA-22 tech debt)
- New tenant quota_pct always 0% (no membership_plans row) — cosmetic only

## Session 22 Close — 21/05/2026
- ECS desired=0, RDS stopped
- Task def: api:151 | CI #241 | Last deploy #147
- Commits: ae2ba56 (AA-CIS-App AA-45), 2a37231 (AA-ACP-App portal)


## Implementation Notes Pattern

For every Linear issue involving code changes, maintain a parallel notes file
**while implementing** (not after).

**Path:** `docs/implementation-notes/<ISSUE-ID>.md`

### Required sections
- **Decisions** — choices made that were not specified in the Linear issue
- **Changed** — what was modified vs. the original requirement
- **Tradeoffs** — what was weighed and why
- **Should know** — anything the reviewer needs before reading the diff

### Example
```md
## AA-87: S1 Brand Injection Fix
- Decision: inject system_prompt at invoke_model(), not LangGraph node (node cached)
- Changed: _call_llm() signature 2→3 args (added brand_context)
- Tradeoff: prompt_len logging adds ~$0.02/mo CloudWatch cost — accepted
- Should know: empty system_prompt → flag "unbranded", do not raise exception
```

### Trigger
Create the file when starting any task: "implement AA-XX", "fix AA-XX", "build AA-XX"
Update incrementally as decisions are made — not in one batch at the end.