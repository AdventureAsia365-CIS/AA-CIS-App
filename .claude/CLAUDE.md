# AA-CIS-App — Claude Code Context
# Updated: 20/05/2026 | ECS api:141 | CI #224

## LIVE STATE
- API: https://api-cis.lumiguides.it.com ✅ (via API Gateway owq9as3wjl)
- Frontend: https://aa-cis.lumiguides.it.com ✅ (Vercel)
- ECS task def: api:141 | CI #224 green | Deploy Dev #135
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

## MIGRATIONS APPLIED (dev DB)
- 018: brand_identity_columns (tenant_brand_rules extensions)
- 019: tenant_brand_rule_versions table (acp_silver_s2 prep)
- 024: raw_tours review_status/reviewed_by/reviewed_at/review_notes + index
- 027: acp_silver_s2.competitor_inputs table + index

## ROUTERS REGISTERED (main.py)
- v1_tours, v1_exports, v1_pipeline, v1_acp, v1_competitors, v1_s0, admin

## ACTIVE WORK — 20/05/2026
Session 18 COMPLETE. AA-86, AA-88, AA-44 COMPLETE.
Last commits: 5ee8688 (AA-86), 9863b36 (AA-88), 2e4ce29 (AA-44)

### ✅ Done Session 18
- AA-87: brand_system_prompt → LLMRequest.system_prompt wired (was already flowing); added prompt_len logging, is_branded flag, og_tags={"unbranded":true} in generated_content. Commit bd68d74.
- AA-82: migration 019 tenant_brand_rule_versions table (FK → shared.tenants). Commit 24ee254.
- AA-86: validate_node refactor — _FAILURE_MAP 13 codes, 4 sub-scores (brand/seo/structure/quality), failure_codes JSONB populated, validator_fn_version='v2'. Commit 5ee8688.
- AA-88: migration 027 acp_silver_s2.competitor_inputs + v1_competitors.py (4 endpoints, max-10/country, ownership check) + AA-ACP-App portal competitors page. Commit 9863b36.
- AA-44: migration 024 raw_tours review_status + v1_s0.py (GET/PATCH/approve/reject, field_coverage_pct) + AA-ACP-App /workspace/s0/review page (inline edit, bulk approve/reject, coverage badge). Commit 2e4ce29.

### 🔴 Next Session Priority (P0)
1. AA-90: S1 Configured Rewrite Engine — migrations 025/026 + tour_content_versions table + S1 Trigger UI
   - ADR-016 accepted: S0/S1 separation + tour content versioning (published_tours → VIEW)
2. AA-11: Phase 3 Report DOCX → Ms. Thu (Claude Chat, no AWS needed)
3. Add quota rows to membership_plans for 4 new tenants (quota% shows 0% currently)

### ⚠️ Open Issues
- AA-36: No char limits on rewrite fields — Backlog
- api_task_def_arn hardcoded :21 in main.tf — AA-CIS-Infra (AA-22 tech debt)
- New tenant quota_pct always 0% (no membership_plans row) — cosmetic only
- reviewed_by always NULL in S0 review — no user identity in JWT yet

## Session 18 Close — 20/05/2026
- ECS desired=0, RDS stopped
- Task def: api:141 | CI #224 | Deploy #135
- Commits: bd68d74, 24ee254, 5ee8688, 9863b36, 2e4ce29 (AA-CIS-App develop)
- AA-ACP-App commits: 912ee85 (competitors page), 7d56cbc (S0 review page)


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