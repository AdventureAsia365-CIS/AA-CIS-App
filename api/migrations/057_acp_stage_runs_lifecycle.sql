-- =============================================================================
-- Migration 057: acp_stage_runs lifecycle columns (started_at, completed_at, error_msg)
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Ticket: AA-141 — Run-Health Dashboard + SLO/Alerting
-- =============================================================================
-- Adds per-stage timing and error tracking needed for stuck-run detection
-- and SLO duration checks in the /admin/acp/run-health endpoint.
-- =============================================================================

BEGIN;

ALTER TABLE acp_shared.acp_stage_runs
    ADD COLUMN IF NOT EXISTS started_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS error_msg     TEXT;

CREATE INDEX IF NOT EXISTS idx_acp_stage_runs_started_at
    ON acp_shared.acp_stage_runs(started_at)
    WHERE started_at IS NOT NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('057', NOW(), 'acp_stage_runs lifecycle columns [AA-141]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
