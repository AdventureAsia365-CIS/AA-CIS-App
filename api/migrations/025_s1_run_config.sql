-- =============================================================================
-- Migration 025: Add run_config to acp_shared.acp_runs
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 20/05/2026
-- Ticket: AA-90 — S1 Configured Rewrite Engine
-- =============================================================================
-- acp_shared.acp_runs is the acpcore v0.4.0 schema (run_id PK).
-- shared.acp_runs is the legacy CIS pipeline table — not touched here.
-- run_config captures the operator-supplied settings snapshot per S1 run.
-- =============================================================================

BEGIN;

ALTER TABLE acp_shared.acp_runs
    ADD COLUMN IF NOT EXISTS run_config JSONB NOT NULL DEFAULT '{}';

COMMENT ON COLUMN acp_shared.acp_runs.run_config IS
    'S1 run config snapshot: {model_id, seo_mode, brand_identity_id, language, tour_ids[]}';

COMMIT;
