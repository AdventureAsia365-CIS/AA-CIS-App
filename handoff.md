# AA-CIS-App Handoff — Session 43
Updated: 2026-06-02

## Status
- Branch: develop | Last commit: fbfba94
- ECS: api:246 (⚠️ STOP if still running)
- RDS: aa-cis-dev-db (⚠️ STOP if still running)

## Completed This Session

### AA-158 — Admin Settings Page (commit 2df9403)
- `GET /admin/settings` — tenant, brand_rules, seo_config, plan, pipeline_gates
- `PATCH /admin/settings/seo` — edit custom_keywords, target_market, overrides
- 4-tab UI: Pipeline Gates (read-only) | Brand Rules (read-only) | SEO Config (editable) | Tenant Info
- Settings gear icon added to AdminSidebar (admin-only, bottom of nav)

### AA-159 — Tenant Page Rebuild + Count/Country Fixes (commit fbfba94)

**Migration 054** (`api/migrations/054_tenants_country.sql`):
- Adds `country TEXT` column to `shared.tenants`
- Seeds `bluepoppy` country = 'Thailand'
- Must be applied to dev DB before testing

**Backend** (`api/routers/admin.py` — `GET /admin/tenants`):
- Fixed aa_internal count bug: old query did `COUNT(*) FROM gold_aa_internal.published_tours` (included inactive/trashed)
- New query: `COUNT FILTER (WHERE source_status = 'active')` per tenant — only counts active source tours
- Added `lifecycle` object to each tenant: source_active, source_superseded, source_trashed, master_active, master_inactive, master_trashed
- Added `country` field to response
- JOINs: `silver_aa_internal.raw_tours` + `gold_aa_internal.published_tours` filtered by tenant_id

**Frontend** (`frontend/app/admin/tenants/page.tsx`):
- `Lifecycle` type + `LifecycleBar` component: dual row (Source | Master) with color-coded stat pills
  - Source: green=active, gold=superseded, red=trashed
  - Master: green=active, gray=inactive, red=trashed
- New "Lifecycle" column in table replaces old "This Month" count
- "Source Active" column shows correct count (active only)
- Country label with globe icon under tenant slug
- Summary cards updated: 4 cards (Total, Active, Source active, Master active)
- Header subtitle now shows source + master active counts
- Delete/toggle/key rotation: all preserved from previous version

## Prerequisites Before Testing in Dev
1. **Migration 054** must be applied (country column)
2. **Migrations 052 + 053** still pending (source_status/master_status/notifications)
3. ECS must deploy new image after CI green

## Verify SQL (run via DBeaver localhost:15432)
```sql
SELECT slug, country, is_active FROM shared.tenants ORDER BY slug;

SELECT t.slug,
    COUNT(rt.tour_id) FILTER (WHERE rt.source_status = 'active') AS active,
    COUNT(rt.tour_id) FILTER (WHERE rt.source_status = 'superseded') AS superseded,
    COUNT(rt.tour_id) FILTER (WHERE rt.source_status = 'trashed') AS trashed
FROM shared.tenants t
LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tenant_id = t.tenant_id
GROUP BY t.slug ORDER BY t.slug;
```

## Known Open Issues (carried forward)
- Migration 052 not yet applied → source_status/master_status columns missing
- Migration 053 not yet applied → notifications table missing
- Migration 054 not yet applied → country column missing on tenants
- OPENAI_API_KEY needs rotation (exposed in session 39)
- API Gateway 29s timeout on long tour rewrites

## Cost Checklist (MANUAL — do not auto-run)
```
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1
aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
```
