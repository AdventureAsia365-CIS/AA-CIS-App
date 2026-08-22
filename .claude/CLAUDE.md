# AA-CIS-App — Claude Code Context
# Updated: 08/08/2026 (AA-384) | main f521972 + AA-384 branch | latest migration: 099
# NOTE: ECS task def / Deploy Prod # / Vercel Prod hash below are UNVERIFIED as of this update
# (AWS was stopped, not re-checked live this session) — reconfirm at next live session, don't
# trust the stale numbers below without a fresh `aws ecs describe-services` / gh run check.

## LIVE STATE
- API: https://api-cis.lumiguides.it.com ✅ (via API Gateway 4ylo382khg — corrected 22/08/2026,
  AA-432; `owq9as3wjl` was stale/no longer exists, confirmed via `aws apigateway get-rest-apis`)
- AA-432 (this session, part 2 — auth architecture) — **LIVE as of 22/08/2026, verified**:
  `/v1/*`'s API Gateway resource (`/v1/{v1_proxy+}`) changed from `authorizationType: CUSTOM`
  (`tenant-key-authorizer`, required `X-API-Key`) to `NONE`. Root cause (STEP0,
  `docs/claude_audit/AA-432-api-gateway-401-step0.md`): the tenant-portal BFF proxy only ever
  sent `Authorization: Bearer <JWT>`, never `X-API-Key`, so every `/v1/*` call 401'd at the
  gateway edge before FastAPI ever ran — confirmed this was NOT limited to 2 routes, it broke
  the whole `/v1/*` surface for both tenant and staff (`(internal)/*`) traffic. Confirmed safe to
  remove: `get_tenant()` (`api/routers/v1_tours.py`, `v1_exports.py`) decodes the JWT itself and
  never reads any gateway-authorizer context; the `X-API-Key` gate was a redundant coarse edge
  check, not the real auth boundary. **Do NOT re-add an `X-API-Key` requirement to the gateway
  for `/v1/*` without re-reading STEP0 first** — this was a deliberate, reviewed removal, not an
  oversight. JWT (verified in FastAPI) is now the only auth boundary for `/v1/*`, matching NONE
  at the gateway for `/admin`, `/auth`, `/content` already. Per-tenant rate-limit + revoke moved
  to the app layer: `api/middleware/rate_limit.py`'s `rate_limit_middleware` (already wired
  globally on `/v1/*`) now reads the tenant's real `shared.tenants.rate_limit_rpm` + `is_active`
  (Redis-cached 30s, `tenant_meta:{tenant_id}` key) instead of a hardcoded plan-tier RPM bucket
  and a login-time-only `is_active` check — `is_active=false` now blocks within ~30s instead of
  waiting up to 24h for the tenant's JWT to expire. **3 routers
  (`v1_acp.py`, `v1_s1.py`, `v1_s1_from_atom.py`) use a DIFFERENT, unrelated auth dependency**
  (`verify_tenant_api_key`, AA-181 — a real `X-API-Key`/`X-Admin-Secret` header FastAPI itself
  checks, independent of the gateway) — confirmed unaffected by this change either way, don't
  confuse the two auth mechanisms if touching either again.
  **Terraform applied 22/08/2026** via `Terraform Apply Prod` workflow (AA-CIS-Infra, PR #30 —
  merge triggered `Deploy Dev` here too, PR #190): `Apply complete! Resources: 1 added, 2
  changed, 1 destroyed` (new `aws_api_gateway_deployment`, `v1_any` method, `dev` stage
  repointed, old deployment destroyed). **Important fix bundled into the same PR**: the
  deployment's `triggers` hash originally only covered integration URIs + the authorizer
  resource's own id — never any method's `authorization`/`authorizer_id`. The first plan run
  showed a clean 1-attribute method change with NO deployment/stage change, which would have
  applied "successfully" while leaving the `dev` stage pinned to the OLD deployment (API Gateway
  stages serve a frozen snapshot; editing a method doesn't retarget a stage by itself) — the 401
  bug would not actually have gone away. Fixed by adding `v1_any`/`admin_any`/`auth_any`/
  `content_any`'s `authorization` (+ `v1_any`'s `authorizer_id`, coalesced since `NONE` leaves it
  null) to the trigger hash — if touching any of these methods' authorization again, keep them
  in that hash or a future change can silently no-op the same way.
  **Live-verified** (real minted tenant JWT, `test-n1-flow`, no `X-API-Key`): `GET
  /v1/tours/pool` and `/v1/tours/my-versions` → 200 with real data (previously 401 at the
  gateway edge, `x-amzn-errortype: UnauthorizedException`, before FastAPI ever ran — now the
  error body when the JWT itself is bad is FastAPI's own `{"detail":"Invalid or expired
  token"}`/`{"detail":"Not authenticated"}`, confirming requests now reach the app).
  `X-RateLimit-Limit`/`X-RateLimit-Remaining`/`X-RateLimit-Plan` headers present and
  decrementing per call. Revoke verified live: flipped `test-n1-flow.is_active` to `false`, next
  request → `403 {"detail":"Tenant is deactivated"}`; flipped back to `true` afterward (tenant
  restored to its original state). `/docs`, `/openapi.json` (unaffected NONE-auth routes)
  still 200.
- Frontend: https://aa-cis.lumiguides.it.com ✅ (Vercel — AA-103 production)
- ECS task def: api:340 (unverified, see header note) | main 38caa5f pre-AA-384 | Vercel Prod hash unverified
- AA-384 (this session): product-direction correction on AA-309/AA-330's posts_per_week/Mirror
  (posts_per_week is now a free tenant choice, migration 099 — see DB SCHEMA below; Mirror is
  purely informational, no upsell language — see api/routers/admin.py get_tenant_mirror()). Real
  Marketplace UI now lives in THIS repo
  (frontend/app/admin/marketplace) — the AA-ACP-App copy (src/app/(admin)/workspace/marketplace)
  is abandoned, 0 traffic since 09/07/2026, not touched. Repo policy: AA-ACP-App is abandoned
  outright — any new ACP-facing UI work goes into AA-CIS-App, never AA-ACP-App.
- AA-330 (Marketplace catalog/portfolio) + AA-309 (N1 tenant onboarding: seed/angle/Mirror/Gate A)
  SHIPPED (merged main, PR #119) — then AA-384 corrected their posts_per_week/Mirror direction
  (see below). AA-330/AA-309 themselves are NOT reopened by AA-384.
- N7 (content production pipeline: DataForSEO keyword/SERP → Brief → Outline/Draft → Adapt(FB/
  TikTok)/FAQ → F2-F9 gates+repair → Slot scheduling, services/acp_produce/*, migration 096) —
  DONE (AA-368 through AA-380).
- N8 (weekly flywheel delivery: assemble_packet, ready/delivered lifecycle, usage_log,
  services/acp_deliver/*, migration 094) — DONE (AA-367, AA-372).
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
- Pre-ADR-2026-023 note: "Deploy Prod" workflow used to be a STUB/placeholder (no-op), real ECS deploy ran
  via "Deploy Dev" on develop merge (last run #128) — this Dev/Prod split and the develop branch no longer
  exist post-ADR-2026-023 (see CI/CD section below)
- AWS: STOPPED after S84 (cis-stop done — ECS desired=0, RDS stop, NAT stop). cis-start can o dau S85.
- Lambda aa-cis-dev-acp-s4-evaluate: DEPLOYED ✅ (AA-49 H-1)
- Lambda aa-cis-dev-acp-s4-trigger: DEPLOYED ✅ | ALB_INTERNAL_URL: FIXED ✅
- Lambda aa-cis-dev-acp-s3-campaign-planner: DEPLOYED ✅ (AA-45)
- API Gateway: 4ylo382khg (aa-cis-dev-api, stage `dev`; corrected 22/08/2026, AA-432 — see note
  in LIVE STATE above) | Lambda Authorizer: aa-cis-dev-authorizer (TOKEN type, identitySource
  `X-API-Key` ONLY — no Bearer/JWT branch, confirmed via source read, AA-432)
- DB: PostgreSQL 15, aa_cis_dev, secret: aa-cis/dev/rds (plain DSN)
- Models: Bedrock Haiku 4.5 (primary) → Sonnet 4.5 (quality fallback)

## STACK
- Backend: FastAPI (api/main.py → api.main:app), asyncpg, Redis
- Frontend: Next.js React 19, Vercel deploy
- AI: AWS Bedrock (us-west-1), LangGraph orchestration
- Infra: ECS Fargate, RDS PostgreSQL 15, S3, Lambda, Step Functions

## FRONTEND ROUTES (frontend/app/, real as of AA-384)
Admin (frontend/app/admin/*, gated by requireAdmin() in frontend/app/api/admin/[...path]/route.ts):
  /admin/dashboard, /admin/upload (S0), /admin/s1-rewrite, /admin/pipeline/{s1,s2,s3,s4-blog,
  s4-social}, /admin/master-content, /admin/curation (+/preview), /admin/review, /admin/brand,
  /admin/tenants, /admin/marketplace (AA-384 — catalog/portfolio/finalize UI, real repo), /admin/
  run-health, /admin/settings.
  Shared components: frontend/app/admin/_components/{AdminSidebar,adminUi}.tsx — adminUi.tsx is
  the design-token source of truth (A colors, serif/mono/sans, Card/Btn/Badge/TH/TD/LoadingScreen).
  New admin pages should reuse these, not invent new styling.
Content-team-facing (frontend/app/(internal)/*): /catalog, /upload, /brand, /review — older
  route-group split from /admin/*, still live, not part of AA-384's scope.
Tenant portal (frontend/app/(tenant)/portal/*): tenant-facing pipeline view, separate auth
  (/tenant-login).
API proxy convention: every /admin/* page calls same-origin /api/admin/[...path] (never the ECS
  API URL directly from the client) — that route attaches X-Admin-Secret + x-admin-user-id server-
  side after requireAdmin() verification. New admin pages MUST follow this, not fetch API_URL
  client-side.

## DB SCHEMA (Medallion)
shared.*              → tenants, pipeline_runs, membership_plans, tenant_brand_rules
silver_aa_internal.*  → raw_tours, generated_content, seo_context
gold_aa_internal.*    → published_tours
acp_shared.*          → marketplace_portfolios (097), tenant_atom_state + tenant_onboarding (098,
                        N1 Gate A), acp_quota_ledger, audit_log
acp_contract.*        → tour_atoms (079, platform-owned, owner_scope='platform'), v_trip_registry
acp_produce.* / acp_deliver.* → N7 production pipeline / N8 weekly flywheel delivery state

silver_{tenant_slug}.* → per B2B tenant (same structure)
gold_{tenant_slug}.*

### Key columns (verified 11/05/2026, tenants.posts_per_week added AA-384 08/08/2026):
tenants:             tenant_id, name, slug, plan_tier(enum), posts_per_week(int, 1-14, migration
                    099 — AA-384: free tenant choice, NOT derived from plan_tier anymore),
                    rate_limit_rpm, is_active, country
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

## MIGRATIONS + APPROVAL GATES (stable conventions)
- Migrations are plain numbered .sql files in api/migrations/ (099 latest as of AA-384), applied
  against RDS via the global S3-mediated ECS exec pattern (see ~/.claude/CLAUDE.md) — no ORM
  auto-migrate, no psql direct connect (ECS container has neither). Each file self-registers into
  shared.schema_versions (version, applied_at, description) with ON CONFLICT DO NOTHING, so re-runs
  are safe no-ops.
- Two named approval gates in this codebase, same UI pattern (row-locked approve, reject re-
  approval), different subject:
  - **Gate A** (AA-309, acp_shared.tenant_onboarding) — a NEW TENANT's onboarding, approved once,
    flips shared.tenants.is_active true. POST /admin/tenants/{id}/gate-a/approve.
  - **Gate B** (AA-320, services/acp_planning/quarter.py) — a QUARTER PLAN VERSION, REQUIRED before
    it becomes allocatable, never auto-approved. Gate A's approval code explicitly mirrors Gate B's
    pattern (same row-lock/reject-re-approval shape) — they are two instances of one convention,
    not unrelated code.
- PR auto-merge: repo has allow_auto_merge=true, branch protection requires 5 status checks (Lint,
  Security Audit, Unit Tests, Integration Tests, Docker Build Check) and 0 required reviews
  (verified live 08/08/2026) — see "CI/CD — solo-operator mode" below. A PR still needs
  `gh pr merge --auto --squash` run explicitly; it is not automatic on open. A PR carrying a
  migration should NOT be auto-merged regardless of CI outcome — schema changes get a manual look.

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
- ADR-2026-023 (trunk-based, effective 09/07/2026): `develop` branch removed. Feature/fix branch → PR →
  CI required → merge to main via PR — auto-merge enabled once CI passes (see "CI/CD — solo-operator
  mode" section below); human-only merge was the original design, now relaxed for solo-operator use.
  Push to main auto-triggers deploy (paths-filter, single pipeline — no more separate Dev/Prod workflows).
- Image tag: always :latest (never commit hash)
- Lint: flake8 (120 char limit, 2 spaces before inline comment)
- No static AWS keys — GitHub Actions OIDC only
- Vercel: auto-deploys on main push (CIS Admin)

## CI/CD — solo-operator mode (since 31/07/2026, S131)
- Auto-merge is enabled on PRs once all 5 required CI checks pass (Lint, Security Audit,
  Unit Tests, Integration Tests, Docker Build Check). No manual merge click required.
- This is a deliberate simplification for a single-operator team. When a second engineer
  joins, RE-ENABLE human-only merge review: go to repo Settings → General → Pull Requests,
  disable "Allow auto-merge", and require at least 1 approving review in branch protection
  (currently NOT required — only status checks gate merge).
- deploy-prod.yml was removed same session — see .github/workflows/DELETED-deploy-prod.md
  for rollback instructions when a real prod environment exists.

## TESTING
pytest tests/ -v
104 integration tests + 23 E2E Playwright tests baseline

## ACTIVE WORK — 08/08/2026 (AA-384)
AA-103 (all CIS admin pages live on Vercel prod) has been done since Session 31 — see FRONTEND
ROUTES above for the real, current route list instead of a page-by-page table here (this section
was stale from 23/05/2026 until AA-384's CLAUDE.md sync; don't let it go stale again — update it
per-session, not the LIVE STATE bullets which are meant to stay append-only history).

Open thread as of AA-384: the AA-384 Linear issue itself is deliberately left NOT Done by that
session — a product-direction change (posts_per_week/Mirror wording) needs Nghiep's explicit
confirmation, not an agent auto-closing it. Check AA-384's Linear status before assuming it's
settled.

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
