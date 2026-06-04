-- =============================================================================
-- Migration 064: acp_runs — independent S4.1/S4.2 status columns [AA-114]
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 2026-06-04
-- Ticket: AA-114 — S4.1/S4.2 Failure Independence
-- =============================================================================
-- S4.1 (blog) and S4.2 (social) run in parallel after Gate 2.
-- A single shared status field caused one stage's failure to overwrite the
-- other's status. These two independent columns fix that.
-- acp_runs.status (old column) is kept for backward compat; API layer derives
-- a composite value from the two new columns.
-- =============================================================================

BEGIN;

ALTER TABLE acp_shared.acp_runs
    ADD COLUMN IF NOT EXISTS s4_blog_status   TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS s4_social_status TEXT NOT NULL DEFAULT 'pending';

INSERT INTO shared.schema_versions (version, description)
VALUES ('064', 'acp_runs: s4_blog_status + s4_social_status independent columns [AA-114]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
