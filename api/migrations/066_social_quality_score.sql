-- =============================================================================
-- Migration 066 — acp_silver_s4.social_content.quality_score
-- AA-127: Add quality_score JSONB for S4.2 pipeline output
-- Shape: {"hook_strength":N,"specificity":N,"cta_clarity":N,
--          "brand_voice":N,"audience_fit":N,"average":N,"passed":bool}
-- NULL when pipeline has not run yet (graceful empty state in UI)
-- Applied: pending
-- =============================================================================

BEGIN;

ALTER TABLE acp_silver_s4.social_content
    ADD COLUMN IF NOT EXISTS quality_score JSONB;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('066', NOW(), 'social_content.quality_score JSONB [AA-127]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
