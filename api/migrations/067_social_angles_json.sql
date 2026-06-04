-- =============================================================================
-- Migration 067 — acp_silver_s4.social_content.angles_json
-- AA-126: Store 3 angles for guided-mode retry flow
-- Shape: {"angle_1":{...},"angle_2":{...},"angle_3":{...},"selected_index":N}
-- NULL when auto mode or row pre-dates this migration
-- Applied: pending
-- =============================================================================

BEGIN;

ALTER TABLE acp_silver_s4.social_content
    ADD COLUMN IF NOT EXISTS angles_json JSONB;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('067', NOW(), 'social_content.angles_json JSONB [AA-126]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
