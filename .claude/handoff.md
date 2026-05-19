# CIS Session 12 Handoff — 19/05/2026

## Status: AA-85 COMPLETE ✅

## AWS State
- ECS aa-cis-dev-api: desired=0, running=0 (STOPPED)
- RDS aa-cis-dev-db: stopping
- API Gateway: owq9as3wjl (ALWAYS ON — no cost when idle)
- Lambda Authorizer: aa-cis-dev-authorizer (ALWAYS ON — no cost when idle)

## Last Deploy
- ECS task def: api:138 (new image from this session)
- CI #220 ✅ | Deploy Dev #132 ✅
- Commits: d09a786, 2b9ea74

## Root Cause of "Failed to load tenant details" — FOUND & FIXED

**Primary crash (AA-85):**
`v_tenant_monthly_usage` returns `api_calls_quota_monthly = NULL` for new tenants
(no quota row in membership_plans). `int(None)` → `TypeError` → 500.

**Secondary crash:**
`voice_examples` JSONB returned as raw JSON string by asyncpg. `dict(string)` → 
`ValueError`. Fixed with `_parse_jsonb()` helper.

**Existing tenants (WanderLux etc.) were not affected** because they have rows in
the view (from API usage), so `api_calls_quota_monthly` was always an integer.

## Completed This Session (AA-85)

### Task 1 — Root cause
- `v_tenant_monthly_usage.api_calls_quota_monthly = NULL` for new tenants
- `int(NULL)` raises `TypeError` at admin.py:375 → 500

### Task 2 — API fix (admin.py)
- COALESCE(api_calls_quota_monthly, 0) in usage query
- Removed `created_at` from brand_rules SELECT (only `updated_at` needed)
- Added 7 new brand identity columns to SELECT with COALESCE guards
- Fixed `last_updated` to never crash on None
- Added `_parse_jsonb()` helper for JSONB-as-string defence

### Task 3 — Migration 018 + Brand seeding
- `api/migrations/018_brand_identity_columns.sql` created
- Applied to dev DB: 8 new columns added to `shared.tenant_brand_rules`
- Default rows inserted for 3 tenants (wildkind-travel already had one)
- Full brand identity seeded for all 4 tenants

### Task 4 — CatalogTab UI overflow fix
- Right-side editorial panel: `display:flex, flexDirection:column, maxHeight:calc(100vh-120px)`
- Header: `flexShrink:0`
- Content area: `flex:1, overflowY:auto, minHeight:0`
- SEO Health and Actions no longer cut off

### Task 5 — End-to-end verified
All 4 new tenants return HTTP 200:
- atlas-hearth: brand_type="Luxury cultural travel brand" ✅
- terra-family-expeditions: brand_type="Premium family adventure travel brand" ✅
- trail-pulse: brand_type="Young active adventure travel brand" ✅
- wildkind-travel: brand_type="Responsible nature and conservation travel brand" ✅

## DB State After Session
- `shared.tenant_brand_rules` new columns: brand_type, core_idea, customer_segment,
  customer_mindset, voice_examples, source_docx_s3_key, rewrite_language, target_markets
- All 4 new tenants seeded with full brand identity

## Next Session
1. AA-11: Phase 3 Report DOCX → Ms. Thu (Claude Chat, no AWS needed)
2. Regenerate aa_internal API key: POST /admin/tenants/{id}/rotate-key
3. Disable WAF after verifying API GW rate limiting stable
4. Phase 5 planning: Webhook notifications, B2B self-signup
5. Consider: add quota row to membership_plans for new tenants (so quota % shows correctly)

## Start Next Session
```
aws rds start-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 1 --profile pqnghiep-admin --region us-west-1
```
