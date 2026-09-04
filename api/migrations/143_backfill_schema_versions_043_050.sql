-- =============================================================================
-- Migration 143: Backfill shared.schema_versions rows for migrations 043-050
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Ticket: AA-282 (schema_versions gap đợt 2 — 043-050 not logged; AA-102 only backfilled
-- 027, 029-034; migration 061 backfilled 058 the same way)
-- =============================================================================
-- STEP0 (AA-282, 04/09/2026) confirmed live against shared.schema_versions:
--   * 043-050 were genuinely absent from the log (all 8 migration files DO exist in the
--     repo, and all 8 were applied to the tracking-era-predates convention -- none of
--     them contain a self-registering INSERT, unlike every migration from ~061 onward).
--   * Their real effects ARE live in the schema (not "missing entirely", the harder
--     problem the issue itself called out as a possibility) -- confirmed via
--     information_schema for every column/table/index each file adds:
--       043 -> shared.tenant_brand_rules.brand_name              (present)
--       044 -> uq_tenant_brand_name_version constraint             (present)
--       045 -> one_active_per_tenant index dropped, not re-created (absent, as intended)
--       046 -> data-only migration (dedup duplicate active brands, no schema object)
--       047 -> shared.tenant_brand_rules.good_examples            (present)
--       048 -> silver_aa_internal.generated_content.metadata      (present)
--       049 -> shared.pipeline_lessons table                      (present)
--       050 -> quality_scores.brand_audit_status/generated_content.fix_pass_applied (present)
--   * git history attribution (git log --diff-filter=A per file):
--       043-047 -> AA-129 (brand identity v2 + master content versions)
--       048     -> AA-130 (metadata JSONB snapshot on generated_content)
--       049     -> AA-131 (pipeline_lessons table + seed 29 lessons)
--       050     -> AA-133/AA-134/AA-132/AA-135 (brand audit + flag fix nodes)
-- ON CONFLICT DO NOTHING makes this safe to re-apply, same as 061.
-- =============================================================================

BEGIN;

INSERT INTO shared.schema_versions (version, description) VALUES
    ('043', 'AA-129: shared.tenant_brand_rules.brand_name -- named multi-brand identities'),
    ('044', 'AA-129: fix shared.tenant_brand_rules unique constraint (per tenant+brand_name+version)'),
    ('045', 'AA-129: drop one_active_per_tenant index on shared.tenant_brand_rules'),
    ('046', 'AA-129: data fix -- dedup duplicate active brand rows'),
    ('047', 'AA-129: shared.tenant_brand_rules.good_examples column'),
    ('048', 'AA-130: silver_aa_internal.generated_content.metadata JSONB snapshot (brand_rule_id/seo_mode/model/cost at generation time)'),
    ('049', 'AA-131: shared.pipeline_lessons table + seed 29 lessons, injected into S1 prompt'),
    ('050', 'AA-133/AA-134/AA-132/AA-135: quality_scores brand_audit_* columns + generated_content fix_pass_applied/fix_pass_fields')
ON CONFLICT (version) DO NOTHING;

INSERT INTO shared.schema_versions (version, description) VALUES
    ('143', 'backfill shared.schema_versions rows for migrations 043-050 [AA-282]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
