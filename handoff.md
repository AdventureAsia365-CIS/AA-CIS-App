# CIS Session 18 Handoff — 20/05/2026

## Status: Session 18 COMPLETE ✅

## AWS State
- ECS aa-cis-dev-api: desired=0, running=0 (STOPPED)
- RDS aa-cis-dev-db: stopped
- API Gateway: owq9as3wjl (ALWAYS ON — no cost when idle)
- Lambda Authorizer: aa-cis-dev-authorizer (ALWAYS ON — no cost when idle)

## Last Deploy
- ECS task def: api:141
- CI #224 ✅ | Deploy Dev #135 ✅
- Last commit on develop: 2e4ce29 (AA-44)

## Completed This Session

### AA-87 — Brand injection observability (Commit bd68d74)
- brand_system_prompt already wired into LLMRequest.system_prompt via generate_node; confirmed correct
- Added: prompt_len structlog entry per LLM call, is_branded flag in ContentState
- og_tags={"unbranded":true} written to generated_content when brand absent (no migration needed — og_tags column already existed)
- 2 new unit tests asserting brand text in LLMRequest.system_prompt

### AA-82 — Migration 019: tenant_brand_rule_versions (Commit 24ee254)
- CREATE TABLE shared.tenant_brand_rule_versions (version_id, tenant_id UUID FK→shared.tenants, snapshot JSONB, source_docx_s3_key, source_type CHECK('manual','docx_parse'), created_by, created_at)
- FK fix: spec said tenant_brand_rules(tenant_id) but that column is not unique — corrected to shared.tenants(tenant_id)

### AA-86 — Structured failure codes in validate_node (Commit 5ee8688)
- _FAILURE_MAP: 13 codes → (dimension: brand|seo|structure|quality, deduction: float)
- 3 new checks: META_INCOMPLETE_SENTENCE, ITINERARY_STRUCTURE_WEAK, DFS_INTENT_UNDERUSED
- Sub-scores: each dim starts at 10.0, deducts its own codes. quality_score = avg(4 dims)
- quality_scores INSERT: validator_fn_version='v2', individual sub-scores, failure_codes JSONB, passed_count/failed_count
- All 35 tests green (12 unit + 23 integration)

### AA-88 — Competitor URL management (Commits 9863b36, 912ee85)
- Migration 027: CREATE SCHEMA acp_silver_s2; CREATE TABLE competitor_inputs (UUID PK, tenant_id FK→shared.tenants, country, url, label, is_active, added_by UUID, UNIQUE(tenant_id,url))
- v1_competitors.py: GET list + active_count_by_country, POST add (max 10 active/country), PATCH update (COALESCE), DELETE soft-delete 204
- AA-ACP-App: src/app/(tenant)/portal/layout.tsx (sidebar) + competitors/page.tsx (country filter, table, Add URL form, limit badge)
- 8 unit tests: max-10, ownership, URL validation

### AA-44 — S0 Data Quality Review (Commits 2e4ce29, 7d56cbc)
- Migration 024: ALTER raw_tours ADD review_status VARCHAR(20) CHECK('pending_review','reviewed','approved','rejected') DEFAULT 'pending_review', reviewed_by UUID, reviewed_at TIMESTAMPTZ, review_notes TEXT + index
- v1_s0.py: GET /review (5 filters, field_coverage_pct Python fn 7 fields), PATCH /tours/{id} (COALESCE, auto-sets 'reviewed'), POST /approve (bulk, returns count), POST /reject (notes required, 400 if empty)
- AA-ACP-App: src/app/(admin)/workspace/layout.tsx (admin sidebar) + s0/review/page.tsx (filter bar, checkbox table, inline edit, bulk action bar, reject modal, coverage badge green/amber/red, toast)
- 10 unit tests: coverage pct (5 cases), bulk approve count, reject notes

## ADR Decisions This Session
- ADR-016 accepted: S0/S1 separation + Tour Content Versioning
  - tour_content_versions table (not yet built — AA-90)
  - published_tours will become VIEW backed by tour_content_versions
  - Logged in Notion

## Next Session — AA-90 P0

### AA-90: S1 Configured Rewrite Engine
- Migration 025: tour_content_versions table
- Migration 026: published_tours → VIEW (or materialized)
- S1 trigger UI in ACP portal
- Tenant-configured rewrite parameters flow into LangGraph state

### Other backlog
- AA-11: Phase 3 Report DOCX → Ms. Thu (Claude Chat, no AWS needed, can do offline)
- Add quota rows to membership_plans for 4 new tenants (quota% shows 0%)
- AA-36: No char limits on rewrite fields — Backlog

## Start Next Session
```bash
aws rds start-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 1 --profile pqnghiep-admin --region us-west-1
```
Confirm task def is api:141. Confirm CI #224 green on develop.
Read handoff.md → confirm AA-90 as P0 → start.
