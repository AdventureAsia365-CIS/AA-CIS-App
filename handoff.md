# AA-CIS-App Handoff — Session 44
Updated: 2026-06-02

## Status
- Branch: develop | Last commit: 424676f
- ECS: api:246 (⚠️ STOP if still running)
- RDS: aa-cis-dev-db (⚠️ STOP if still running)

## Completed This Session

### AA-161 — UAT Fixes B1–B7 (commit 424676f)

**B1 — Tenant count**: Already correct from AA-159 (admin.py FILTER WHERE source_status='active'). Verified, no change.

**B2/B3 — Toggle Active↔Inactive (Master Content)**:
- Backend: Added `PATCH /admin/master/{tour_id}/activate` and `PATCH /admin/master/{tour_id}/deactivate` endpoints in admin.py
- Frontend: Added `toggleMasterStatus()` in master-content/page.tsx
- Active tab row: "Set Inactive" button (amber)
- Inactive tab row: "Set Active" button (green)
- Trashed tab: unchanged (only Restore)
- Gate in `_execute_run_tour`: blocks rewrite if `source_status='trashed'` with message "Tour is trashed. Restore before rewriting."

**B4 — Notifications**:
- `list_notifications` now adds `title` (human-readable label) and `message` (tour_name from payload) fields
- AdminSidebar.tsx dropdown uses `n.title` instead of raw `n.event_type`

**B5 — SEO Config Save**:
- Verified code is correct — `tenant_seo_config` table has `id` SERIAL PK, TEXT tenant_id. asyncpg string pass works.
- No code change needed (if table exists after migration 005, PATCH works correctly)

**B6 — File hash block fix**:
- Old: blocked any file if hash matched existing row in raw_sources
- New: extracts clean filename (UUID-stripped basename) from s3_key and stored filename; only blocks if BOTH hash AND filename match
- Different-name same-content files now proceed to parse → tour-level dedup handles

**B7 — Source trash UI (Upload S0)**:
- `tours-ready` endpoint now excludes `source_status='trashed'` tours
- New `GET /admin/tours-trashed` endpoint returns trashed source tours
- `ToursReadySection` in upload/page.tsx:
  - Added "Actions" column with Trash button (red) per row
  - Added "Show Trashed" toggle: reveals trashed tours section below with Restore buttons
  - After trash: tour removed from ready list; after restore: refreshes from API

## Known Open Issues (carried forward)
- Migration 052 not yet applied → source_status/master_status columns missing
- Migration 053 not yet applied → notifications table missing
- Migration 054 not yet applied → country column missing on tenants
- OPENAI_API_KEY needs rotation (exposed in session 39)
- API Gateway 29s timeout on long tour rewrites
- All B1–B7 fixes require migrations 052+053 to be applied first

## Prerequisites Before Testing in Dev
1. Apply migration 052 (source_status/master_status enums + columns)
2. Apply migration 053 (shared.notifications table)
3. Apply migration 054 (tenants.country column)
4. ECS deploy new image after CI green

## Cost Checklist (MANUAL — do not auto-run)
```
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1
aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
```
