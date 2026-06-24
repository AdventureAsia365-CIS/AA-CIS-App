-- =============================================================================
-- Migration 070 — silver_aa_internal.generated_content tier/fallback tracking
-- AA-224: Add requested_tier + fallback_used so a silent Sonnet->Haiku fallback
--         is observable on the row. requested_tier = what the caller asked for
--         (LLMRequest.model_tier), model_used (existing) = what actually ran.
--         fallback_used = True when the pipeline downgraded tiers.
-- Applied: pending
-- =============================================================================

BEGIN;

ALTER TABLE silver_aa_internal.generated_content
    ADD COLUMN IF NOT EXISTS requested_tier TEXT,
    ADD COLUMN IF NOT EXISTS fallback_used  BOOLEAN NOT NULL DEFAULT FALSE;

INSERT INTO shared.schema_versions (version, description)
    VALUES ('070', 'generated_content.requested_tier + fallback_used [AA-224]')
    ON CONFLICT DO NOTHING;

COMMIT;
