# AA-CIS-App — Handoff Session 10 (13/05/2026)

## State
- ECS: api:127 | CI #208 | STOPPED (desired=0)
- RDS: aa-cis-dev-db STOPPED
- Vercel: https://aa-cis.lumiguides.it.com (Production: Hn6pUVzWr)
- Branch: develop | Last commit: f070fb4
- M1 milestone: COMPLETE

## Done this session

### AA-40 — Terraform EventBridge + S3 medallion (AA-CIS-Infra)
- EventBridge bus `aa-cis-dev-acp-events` + Scheduler rules + S3 bronze/silver/gold buckets + Secrets Manager
- Terraform applied, CI green
- IAM additions: aa-cis-dev-role (CI) + aa-cis-dev-ecs-task-role (PutEvents)

### AA-42 — CIS publish EventBridge event + manifest.json
- EventBridge publish after pipeline complete
- manifest.json → S3 gold path
- GET /v1/acp/s1-keywords endpoint
- DB: shared.acp_runs table (migration 009 applied)

### AA-39 — seo_mode dropdown
- Wired seo_mode to pipeline run API
- 3 modes: dataforseo / custom_keywords / disabled

### AA-28 — Multi-select export CSV + XLSX
- CSV: tab-delimited (\t), UTF-8 BOM, no quotes, replaces \n in values
- XLSX: SheetJS (xlsx package), 21 columns full for Admin, 14 for Tenant
- Admin: fetches /api/tour-full/{id} per tour → includes supplier extras + SEO keywords
- Tenant: fetches /api/tenant/v1/tours/versions/{id} → includes subtitle, itineraries, SEO fields
- Async export with loading state on buttons

### AA-27 — Admin Catalog UI
- Filter bar (country, status, score range, date range)
- Highlights as bullet list
- SEO keywords section + Audit/Validation panel
- Inclusions/Exclusions rendered per line

### AA-29 — Tenant itinerary format
- Newlines per day preserved in My Catalog view

### AA-24 — Dashboard Cost tab
- Fixed m.total_cost (was m.cost → undefined → $0)

### Vercel auto-deploy
- main → Production (Deploy Hook set in CI)
- develop → Preview

### AA-1/2/3/4 — Linear onboarding issues: closed
### AA-54 — Cancelled (wrong diagnosis)

## Next priorities
1. AA-13: API Gateway REST + per-tenant rate limiting + Terraform (due 31/5)
2. Phase 3 Report DOCX for Ms. Thu (overdue)
3. Bug 3: quality_score=0.00 all rewrites — CloudWatch investigate (ECS must be running first)
4. AA-28: Full column export — Backlog (done for both Admin + Tenant)
5. AA-36: No char limits on rewrite fields — Backlog

## Schema notes (carried forward)
- tenants PK = tenant_id (NOT id)
- v_tenant_monthly_usage: billing_month, api_calls_used, quota_calls_pct
- tenant_tour_versions.published_tour_id → published_tours.id
- forbidden_words: asyncpg returns JSONB as string → always json.loads()
- pool rewrites do NOT create pipeline_runs rows
- acp_runs table: shared.acp_runs (migration 009)
