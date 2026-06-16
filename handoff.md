# AA-CIS-App Handoff — Session 58
Updated: 2026-06-16

## Status
- Branch: develop @ c4dacb3 | main @ 883a3cd (both pushed; docs commit on top of each)
- ECS: aa-cis-dev-api task def **api:304** — digest == ECR :latest (sha256:a65dfcd…230b67) — **RUNNING, STOP after session**
- RDS: aa-cis-dev-db **RUNNING — STOP after session**
- CI on PR #38: green ✅ | Deploy Dev: SUCCESS ✅ | Deploy Prod: success but STUB (no-op)

## Completed This Session — AA-193 brand differentiation (F1 + F2)

### AA-198 [AA-193·F1] — Brand differentiation resolver ✅ SHIPPED
**feature/aa-198-brand-resolver → PR #37 → develop (2cba714) → main (3251a51) → ECS api:303**
- Root cause: `_execute_run_tour` fallback `WHERE is_active ORDER BY version DESC LIMIT 1` picked
  cross-brand max version → Terra Family v2 won every run. 5 active brands, no intra-brand dupe → no migration.
- Backend: `_resolve_brand_rule` (id → named-active → explicit 'default'); `TourRunRequest.brand_identity_id`;
  `GET /admin/brand-rules` (id/name/version/is_active, no prompt content); forbidden_words prompt inject.
- Frontend: s1-rewrite brand-picker keyed on id, sends `brand_identity_id` (kept brand_name).
- 5 unit tests `tests/unit/test_aa198_brand_resolver.py`.

### AA-197 [AA-193·F2] — DataForSEO rebuild ✅ SHIPPED
**feature/aa-197-dataforseo-rebuild → PR #38 → develop (c4dacb3) → main (883a3cd) → ECS api:304**
- Root cause: `admin_pipeline` set destination=`"{country} tours"` → DFS client appended "tours" again
  → `"{country} tours tours"`. US location hardcoded. TenantConfigService existed but was UNWIRED in SEO path.
- New `services/seo_intelligence/seed_builder.py` (pure): `normalize_country` (COUNTRY_NORMALIZE map
  SRI-LANDKA/OKINAWA + title-case), `first_activity` (split `[,│\n]+`, U+2502 pipe), `build_seed`
  ("{activity} in {country}" / "{country} tours" / "", never double-tours), `resolve_buyer_market`
  (target_market.countries → MARKET_RANK US>UK>AU, empty→US 2840, language passthrough).
- DFS client rebuilt: methods take pre-built seed + location_code/name/language (US hardcode gone, no
  more appending). 3 calls/tour: search_volume + ONE serp/advanced (PAA + related) + real
  keywords_for_keywords ideas. `_parse_keyword_ideas` → full dicts {keyword, search_volume, competition,
  competition_index, cpc}, dedupe casefold, ≤25. fetch_all return adds related_keywords + keyword_ideas
  (additive); kept keywords.top_keywords + people_also_ask for prompts.py L61-62.
- Fallback #4: when search_volume returns no top_keywords AND ideas non-empty → promote
  `top_keywords = [i.keyword for i in ideas[:10]]` so prompt always has a keyword.
- Wiring: `process_seo` gains seed + tenant_id; resolves buyer market via TenantConfigService.get_seo_config;
  cache key now `make_key(seed, location_code)`. admin_pipeline builds seed via build_seed(country, activities).
- 20 unit tests `tests/unit/test_aa197_dfs.py`.

### Live DFS probe (field paths verified, status 20000)
- search_volume: tasks[0].result[] flat, result[i].search_volume / .keyword.
- serp advanced result[0].items[]: type="people_also_ask" → .items[].title ; type="related_searches" → .items[]=plain strings.
- keywords_for_keywords: result[] flat (~105), {keyword, search_volume, competition, competition_index, cpc, monthly_searches}; near-dups by case → dedupe casefold.
- get_dataforseo_creds() returns a TUPLE (login, password), NOT a dict.

## Deploy verification
- AA-198: ECS digest == ECR :latest, task def :303. AA-197: digest == ECR :latest sha256:a65dfcd…230b67, task def :304.

## Gotchas (carry forward)
- Brand table = `shared.tenant_brand_rules`; SEO config = `shared.tenant_seo_config` (target_market JSONB
  {language, age_range, countries[]} — no `.primary`). shared.tenants.country is ALL NULL (unused).
- raw_tours.country is dirty (SRI-LANDKA, OKINAWA); activities jsonb 25% coverage, single-elem array of one delimited string.
- "Deploy Prod" workflow is a placeholder STUB (no build/deploy). Dev ECS cluster is the live API.
- S3-mediated ECS exec for scripts importing app pkgs: run with `cd /app && PYTHONPATH=/app` (else ModuleNotFoundError 'shared').

## Next / Open
- AA-193 may have further F-items — check Linear.
- UAT on prod: s1-rewrite brand-picker lists 5 brands + non-Terra selection persists to generated_content.metadata.brand_name;
  run a tour and confirm DFS seed has no double-"tours" and buyer market reflects target_market.

## ⚠️ Cost — STOP AWS (reminder only, do NOT auto-run)
- aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1
- aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
- NAT instance i-04ebd090e97184f45 → cis-stop
