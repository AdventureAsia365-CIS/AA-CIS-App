-- =============================================================================
-- Migration 056: acp_stage_runs event_id idempotency key
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Ticket: AA-106 — EventBridge Source Fix + Consumer Idempotency
-- =============================================================================
-- Adds event_id (EventBridge event.id) to acp_stage_runs so duplicate/retried
-- events from EventBridge can be detected and skipped at-most-once.
-- =============================================================================

BEGIN;

ALTER TABLE acp_shared.acp_stage_runs
    ADD COLUMN IF NOT EXISTS event_id           TEXT,
    ADD COLUMN IF NOT EXISTS event_received_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS status             VARCHAR(20) DEFAULT 'completed';

CREATE UNIQUE INDEX IF NOT EXISTS idx_acp_stage_runs_event_id
    ON acp_shared.acp_stage_runs (event_id)
    WHERE event_id IS NOT NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('056', NOW(), 'acp_stage_runs event_id idempotency key [AA-106]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
