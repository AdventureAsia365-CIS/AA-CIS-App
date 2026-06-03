-- =============================================================================
-- Migration 059: S2 checkpoint metadata column
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Ticket: AA-112 — S2 AsyncPostgresSaver + Migration + Cache Tables
-- =============================================================================
-- Adds metadata JSONB to acp_stage_runs for iteration/resume tracking.
-- Cache tables (raw_keyword_cache, raw_html_cache) are NOT created here:
-- S2 tools already cache via acp_silver_s2.visibility_reports + S3 keys.
-- Prerequisite: migration 055 (creates acp_shared.acp_stage_runs).
-- =============================================================================

BEGIN;

ALTER TABLE acp_shared.acp_stage_runs
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('059', NOW(), 's2_checkpoint_metadata: acp_stage_runs.metadata [AA-112]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
