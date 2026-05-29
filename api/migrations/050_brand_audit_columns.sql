-- AA-133/134: Add brand audit + fix-pass columns
-- quality_scores: brand audit result columns
ALTER TABLE silver_aa_internal.quality_scores
    ADD COLUMN IF NOT EXISTS brand_audit_status  text,
    ADD COLUMN IF NOT EXISTS brand_audit_codes   jsonb DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS brand_audit_issues  jsonb DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS brand_audit_fields  jsonb DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS lessons_extracted   jsonb DEFAULT '[]'::jsonb;

-- generated_content: flag-fix pass tracking (not a new version)
ALTER TABLE silver_aa_internal.generated_content
    ADD COLUMN IF NOT EXISTS fix_pass_applied  boolean DEFAULT false,
    ADD COLUMN IF NOT EXISTS fix_pass_fields   jsonb DEFAULT '[]'::jsonb;

COMMENT ON COLUMN silver_aa_internal.quality_scores.brand_audit_status
    IS 'LLM-as-Judge result: pass | flagged | manual_check. NULL = not yet audited.';
COMMENT ON COLUMN silver_aa_internal.generated_content.fix_pass_applied
    IS 'True if brand audit flag fix was applied. Does not increment version_num.';
COMMENT ON COLUMN silver_aa_internal.generated_content.fix_pass_fields
    IS 'Fields corrected by flag fix pass e.g. ["aa_subtitle", "seo_meta"]';
