# AA-CIS-App — Handoff Session 8 (12/05/2026)

## State
- ECS: api:118 | CI #195 | Deploy #114 | STOPPED (desired=0)
- RDS: aa-cis-dev-db STOPPED
- Vercel: https://aa-cis.lumiguides.it.com (latest deploy)
- Branch: develop | Last commit: 5adf517

## Done this session

### AA-52 — Tenant Portal polling + validator fix
- ba80b99: polling + status badges + toast
- b1a8bb0: is_tenant_rewrite=True → skip name-match, quality_score write fixed
- 030f400: polling stop condition, approve/reject disable, AA original column fix

### AA-25 — Admin Tenants detail view
- 05988c8: fix Failed to load + 4-tab view (Tours/Pipeline/API Usage/Brand)
  - Root cause: v_tenant_monthly_usage wrong columns (total_calls → api_calls_used)
- 0dba680: ORDER BY billing_month DESC
- 5adf517: forbidden_words JSONB parse (backend + frontend)
- DB: lumitest plan_id fixed, INTERNAL_API_KEY rotated

## Next priorities
1. AA-40: Terraform ACP (EventBridge + S3) — AA-CIS-Infra repo
2. AA-42: CIS EventBridge publish + manifest.json (blocked by AA-40)
3. AA-57: Tenant Portal bugs (wait Ms. Thu feedback)

## Schema notes
- tenants PK = tenant_id (NOT id)
- v_tenant_monthly_usage: billing_month, api_calls_used, quota_calls_pct
- tenant_tour_versions.published_tour_id → published_tours.id
- forbidden_words: asyncpg returns JSONB as string → always json.loads()
- pool rewrites do NOT create pipeline_runs rows

## CRITICAL
INTERNAL_API_KEY was rotated this session — new key in Vercel production.
