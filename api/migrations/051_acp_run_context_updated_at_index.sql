-- =============================================================================
-- Migration 051: Add updated_at index on acp_run_context
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 01/06/2026
-- Ticket: AA-117 — acp_run_context Pydantic guard + atomic jsonb_set
-- =============================================================================
-- The atomic per-stage UPDATE pattern (AA-117) filters by run_id (already PK).
-- This migration adds a supporting index on updated_at for monitoring/audit
-- queries that need to find recently-updated context rows.
-- =============================================================================

BEGIN;

CREATE INDEX IF NOT EXISTS idx_acp_run_context_updated_at
    ON acp_shared.acp_run_context(updated_at DESC);

INSERT INTO shared.schema_versions (version, description)
VALUES ('051', 'acp_run_context updated_at index [AA-117]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
