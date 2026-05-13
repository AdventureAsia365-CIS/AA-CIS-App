-- =============================================================================
-- Migration 009: ACP runs table for S1 EventBridge + manifest integration
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 13/05/2026
-- Ticket: AA-42 — CIS publish EventBridge event + manifest.json
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS shared.acp_runs (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id          UUID         NOT NULL UNIQUE REFERENCES shared.pipeline_runs(batch_id),
    country           TEXT,
    tenant_id         UUID         NOT NULL,
    manifest_s3_key   TEXT,
    tour_count        INTEGER      NOT NULL DEFAULT 0,
    quality_score_avg NUMERIC(5,2),
    status            TEXT         NOT NULL DEFAULT 'pending',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_acp_runs_country ON shared.acp_runs(country);
CREATE INDEX IF NOT EXISTS idx_acp_runs_status  ON shared.acp_runs(status);

COMMENT ON TABLE shared.acp_runs IS
    'Tracks ACP S1 run state: manifest S3 path, EventBridge publish status, quality summary per batch.';

COMMIT;
