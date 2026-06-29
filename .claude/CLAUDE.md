# AA-CIS-App — Claude Code Context
# Updated: 29/06/2026 (S84) | ECS api:340 | main 38caa5f (Deploy Prod #137) | Vercel Prod Ready

## LIVE STATE
- API: https://api-cis.lumiguides.it.com ✅ (via API Gateway owq9as3wjl)
- Frontend: https://aa-cis.lumiguides.it.com ✅ (Vercel — AA-103 production)
- ECS task def: api:340 (FE-only S84, ECS khong dung — :340 tu deploy khac, can xac minh) | Deploy Prod #137 | main 38caa5f | Vercel Prod 38caa5f Ready
- AA-241 [AA-234 Phần C] SHIPPED Prod (S84): Review Queue UI full 11-field edit + fail markers + revalidate gate + reviewer audit. AA-234 epic DONE. AA-242 (Regenerate) tach doc lap Backlog.
  /admin/review-queue now returns full editable gc fields + audit columns (human_edited/reviewed_by/
  edited_at/revalidate_passed) + a `failures` array re-derived on CURRENT content via
  _derive_field_failures (shared _VALIDATE_FORBIDDEN/_CODE_FIELD_MAP consts from graph.py + seo_meta_utils
  thresholds — no logic copy). A code whose field a reviewer has since fixed is NOT re-surfaced. No new
  migration (still 072). 12/12 unit tests. Carryover AA-241 (Phần C) — edit UI maps 1:1 to PATCH fields.
- AA-234 Phần A SHIPPED Prod (S82): re-validate human-edited review content before approve. Reviewer
  edits a version in place (full fields, no new version) → async re-validate (build_revalidation_graph:
  validate→judge→brand_audit→human_edit_gate, NO flag_fix) → approve gated on revalidate_passed. Hard-block
  codes (META_TOO_SHORT/FORBIDDEN_WORD/etc) fail the gate even at high score. Migration 072.
- AA-233 SHIPPED Prod (S82): _execute_run_tour return dict surfaces fallback_used (was None; DB correct since AA-224)
- S82 backlog cleanup: AA-221 canceled (dup AA-223), AA-236 canceled (dead Lambda path), AA-160 deferred
- AA-238 + AA-239 SHIPPED Prod (S81): seo_meta band-guard — forbidden-word pad no longer accepted as
  in-band (D1: forbidden-free is a HARD band criterion; unified _seo_meta_forbidden ∪ tenant list) +
  sentence salvage picks longest complete-sentence prefix ≥140 instead of last-period-only/downward
  (D3); un-fixable cases escalate to _rerepair_meta → manual_check/HITL rather than reaching gold
- AA-235 SHIPPED Prod (S79): keyword_ideas shape guard — _as_list guarantees a list (dedup 4 inline
  copies → 1 module-level helper), FE Array.isArray guard in DfsCompareSection, writer persists [] on
  empty DFS + custom_keywords read-guard. Backfilled 21 legacy {seed:null} object rows → []. Fixes the
  28-version-tour Version Compare crash ("o is not iterable") + export-docx 500 (keyword_ideas[:25] on
  dict). Follow-up AA-236 = route effective_seed through build_seed() (seed quality, doubled "tours")
- AA-223 SHIPPED Prod (S79): async run-tour 202+job poll, pipeline_jobs table
- AA-205 SHIPPED (S71): post-repair seo_meta band guard — extract seo_meta_utils (single source of
  truth, breaks graph↔flag_fix circular import) + best_meta_candidate deterministic salvage +
  bounded _rerepair_meta (1 LLM call). Under-140 repair output can no longer clear the 7.0 gate into gold
- AA-215 SHIPPED (S70): revalidate node (flag_fix → revalidate → END) — re-validate+re-judge repaired content
- AA-213 SHIPPED (S70): persist fallback_used + score_overall + batch_id + revalidate_* to generated_content.metadata
- AA-214 SHIPPED (S70): .flake8 aligned to CI (max-line-length 120 + extend-ignore + exclude)
- AA-211/212 SHIPPED (S69): export gate + HITL review_queue re-wire
- AA-198 [F1] SHIPPED: brand_identity_id resolver + /admin/brand-rules + s1 brand-picker
- AA-197 [F2] SHIPPED: DataForSEO rebuild — buyer-market location, seed builder, real keyword_ideas
- "Deploy Prod" workflow = STUB/placeholder (no-op) — real ECS deploy runs via "Deploy Dev" on develop merge (last run #128)
- AWS: STOPPED after S84 (cis-stop done — ECS desired=0, RDS stop, NAT stop). cis-start can o dau S85.
- Lambda aa-cis-dev-acp-s4-evaluate: DEPLOYED ✅ (AA-49 H-1)
- Lambda aa-cis-dev-acp-s4-trigger: DEPLOYED ✅ | ALB_INTERNAL_URL: FIXED ✅
- Lambda aa-cis-dev-acp-s3-campaign-planner: DEPLOYED ✅ (AA-45)
- API Gateway: owq9as3wjl | Lambda Authorizer: aa-cis-dev-authorizer
- DB: PostgreSQL 15, aa_cis_dev, secret: aa-cis/dev/rds (plain DSN)
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

## CRITICAL RULES
- raw_tours PK = tour_id (NOT id)
- published_tours has NO country column → always JOIN raw_tours ON tour_id
- seo_context has NO country column → JOIN raw_tours
- All UUIDs: default=str in json.dumps()
- Schema-qualify all queries: silver_aa_internal.raw_tours (not just raw_tours)
- max_tokens = 4096 (NOT 2000 — JSON truncation bug fixed)
- generate() is SYNCHRONOUS (asyncio deadlock fix, Python 3.12)
- Log group: /ecs/aa-cis-dev (CORRECT) | /ecs/aa-cis-dev-api (WRONG — always empty)

## CONTENT QUALITY RULES (aa_internal tenant)
- aa_name MUST be rewritten (not src_name passthrough)
- seo_meta forbidden: hostel, budget, public transport, cheap, backpacker, dorm
- Subtitle must differ clearly between V1/V2/V3 configs
- Brand: "Discreet Executive Adventure" | Target: 40-60 senior professional $250k+
- Forbidden words: deals, cheap, book now, instant booking, epic
- CTA: "Design This Journey"

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

## AWS PATTERNS (WSL2)
- Single-line commands only (multi-line backslash hangs in WSL2)
- ECS has no AWS CLI → use boto3 for S3 upload from container
- S3-mediated ECS exec: write script → upload S3 → presign → ECS execute-command
- DBeaver tunnel: cis-tunnel alias → localhost:15432
- SSM only, no SSH port 22

## SESSION ALIASES (~/.zshrc)
```bash
cis-start  # start NAT Instance + RDS + ECS
cis-stop   # stop ECS + RDS + NAT Instance
cis-status # check NAT instance state
```

## KNOWN TECH DEBT — DO NOT BREAK
- api_task_def_arn hardcoded :21 in main.tf (AA-CIS-Infra) — do not change (AA-22)
- Step Functions deployed but bypassed — direct API flow only
- webhook_deliveries = 0 — deferred P2
- content_exports table does not exist in shared schema
- Lambda DATABASE_URL plaintext → Secrets Manager (P4-S6)
- mobile_card_text no prompt → always NULL
- AA-36: No char limits on rewrite fields — Backlog

## CI/CD
- Push to develop → GitHub Actions ci.yml → build → deploy-dev.yml → ECR push → ECS deploy
- Push to main → Deploy Prod CI auto-triggers
- Image tag: always :latest (never commit hash)
- Lint: flake8 (120 char limit, 2 spaces before inline comment)
- No static AWS keys — GitHub Actions OIDC only
- Vercel: auto-deploys on main push (CIS Admin)

## TESTING
pytest tests/ -v
104 integration tests + 23 E2E Playwright tests baseline

## ACTIVE WORK — 23/05/2026
### AA-103 COMPLETE ✅ (Session 31)
All CIS admin pages merged to main, Vercel production deployed.

| Page | URL | Status |
|------|-----|--------|
| Upload (S0) | /admin/upload | ✅ Live |
| S1 Rewrite | /admin/pipeline/s1 | ✅ Live |
| Master Content | /admin/master-content | ✅ Live |
| Dashboard | /admin/dashboard | ✅ Live |
| Tenants | /admin/tenants | ✅ Live |

Route conflict fix: (admin) route group → admin/ real directory (Session 31 commit 5b6face)

### Next Priority
1. Manual UAT all pages on production (ECS + RDS must be running)
2. WordPress Docker UAT setup (docker/wordpress-uat + ngrok + Secrets Manager)
3. Verify aa_internal tenant UUID in DB (Gate 1 hardcodes this)

## Implementation Notes Pattern
For every Linear issue involving code changes, maintain a parallel notes file
while implementing (not after).

Path: docs/implementation-notes/<ISSUE-ID>.md

Required sections:
- Decisions — choices made not specified in Linear issue
- Changed — what was modified vs. original requirement
- Tradeoffs — what was weighed and why
- Should know — anything reviewer needs before reading the diff

Trigger: create when starting any task — "implement AA-XX", "fix AA-XX", "build AA-XX"
Update incrementally as decisions are made — not in one batch at the end.
