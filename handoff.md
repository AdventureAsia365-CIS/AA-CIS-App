# AA-CIS-App Handoff — Session 38
Updated: 2026-05-27

## Status
- Branch: develop | Last commit: 755092b (merged fix/aa-129-final-pass)
- ECS: api:185 (⚠️ STOP if still running)
- RDS: aa-cis-dev-db (⚠️ STOP if still running)

## Completed This Session (AA-129 Final Pass)

### Bug Fixes

**B2: Save (new version) → "Save failed"**
- Root cause: `frontend/app/api/admin/[...path]/route.ts` was missing `export const PUT = handler`
- PUT /api/admin/brands/{name} → 405 Method Not Allowed → UI shows "Save failed"
- Fix: added `export const PUT = handler;`
- File: `frontend/app/api/admin/[...path]/route.ts`

**B4: Brand dropdown shows deleted/duplicate brands**
- Root cause: `list_brands` WHERE clause had no `is_active = true` filter
- Deleted brands (all versions is_active=false) still appeared in S1 rewrite dropdown and brand list
- Fix: added `AND is_active = true` to list_brands WHERE clause
- Also normalized `COALESCE(brand_name, 'default')` consistently
- File: `api/routers/admin_pipeline.py`

**B3: Delete brand — no feedback on failure**
- Root cause (visual): after delete + reload, deleted brand reappeared (B4 fix resolves this)
- Additional fix: `deleteBrand()` now shows `setMsg({ text: e.detail || "Delete failed", ok: false })` on non-ok response
- File: `frontend/app/admin/brand/page.tsx`

**B1: DOCX parse → 403 (not a code bug)**
- The proxy already handles multipart correctly (arrayBuffer + Content-Type with boundary forwarded)
- 403 = ADMIN_SECRET env var mismatch or not set in Vercel → ops verification needed
- ⚠️ Verify: Vercel env var ADMIN_SECRET = `cis-admin-10ec56e26d5fd322e7cac2dbec7f3903`

### Master Content Enhancements

**Part 2: VersionCompareModal — Full Screen (in-place rewrite)**
- Position: `fixed`, `left: 240px` (sidebar width), `width: calc(100vw - 240px)`, `height: 100vh`
- 2 columns, each independently scrollable
- Version selector dropdowns in each column header (can switch which versions to compare)
- Score bars: Overall, Brand, SEO, Structure with numeric values
- Rewrite Config section: Model, Brand Identity, SEO Mode, DataForSEO (Live/Mock), Cost
- All content fields: Tour Name, Subtitle, Summary, Itineraries, SEO Title (char count), SEO Meta (char count + red if >170), Description
- Keywords from seo_context.top_keywords

**Part 3: Sticky 3-Section Layout**
- Outer container: `height: 100vh`, `display: flex`, `flex-direction: column`, `overflow: hidden`
- Section 1 (header + stats): `flexShrink: 0`, ~135px fixed
- Section 2 (tours): `flex: 1`, `display: flex`, `flex-direction: column`, own scroll, sticky inner filter header
- Section 3 (pipeline runs): `height: 280px`, `flexShrink: 0`, inner scroll
- Visible border-bottom separating sections 2 and 3

**Part 4: Tour Table Filters**
- Added: Country dropdown (populated from unique countries in tour list)
- Added: Score filter (All / 9.5+ / 9.0+ / 8.0+ / Below 8.0)
- Added: Version filter (All / v1 only / v2+ / v3+)
- Kept: text search + Status filter
- All filters: client-side AND logic
- Count label: "X of Y tours" when filtered

**Backend: get_tour_version_detail enhanced**
- Added: `score_brand`, `score_seo`, `score_structure` from quality_scores JOIN
- Added: `metadata` JSONB extraction (seo_mode, dataforseo_used, llm_cost_usd, brand_rule_id)
- Added: `brand_name` via LEFT JOIN shared.tenant_brand_rules ON id = (metadata->>'brand_rule_id')::uuid
- Added: `top_keywords` via LATERAL JOIN silver_aa_internal.seo_context ORDER BY fetched_at DESC LIMIT 1

**adminUi.tsx: SLabel now accepts optional `style` prop**

## Next Session Priority
1. **⚠️ Apply migrations 043-045 to dev DB before UAT**:
   ```sql
   -- Run in order via ECS exec or DBeaver tunnel
   -- 043: ALTER TABLE shared.tenant_brand_rules ADD COLUMN IF NOT EXISTS brand_name TEXT;
   -- 044: see api/migrations/044_fix_brand_rules_unique_constraint.sql
   -- 045: see api/migrations/045_drop_one_active_per_tenant_index.sql
   ```
2. **CI green** → Deploy Dev (ECS must be running with new image)
3. **Verify Vercel ADMIN_SECRET env var** = `cis-admin-10ec56e26d5fd322e7cac2dbec7f3903` (fixes B1 parse-docx 403)
4. **Manual UAT** (ECS + RDS must be running):
   - /admin/brands: create brand → Save should work (B2 fix)
   - /admin/brands: delete brand → brand disappears from list (B4 fix)
   - /admin/brands: DOCX upload → if still 403, check Vercel ADMIN_SECRET
   - /admin/s1-rewrite: brand dropdown shows only active brands
   - /admin/master-content: version compare opens full-screen (no sidebar overlap)
   - /admin/master-content: country/score/version filters work client-side
   - /admin/master-content: sticky 3-section layout scrolls correctly
5. AA-47: WordPress Docker UAT setup (still pending)

## Known Open Issues
- Migration 043-045 not applied to dev DB yet — MUST run before UAT
- B1 (403 parse-docx) likely Vercel ADMIN_SECRET env config issue — not code bug
- python-docx and xlsxwriter need ECS rebuild (requirements.txt updated in session 36)
- Lambda s4-trigger ALB_INTERNAL_URL is placeholder — blocks E2E UAT
- api_task_def_arn hardcoded :21 in main.tf (AA-22 tech debt)
- TS errors in .next/dev/types/validator.ts (stale cache from Session 31) — NOT new errors

## Cost Checklist (MANUAL — do not auto-run)
```
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1
aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
```
