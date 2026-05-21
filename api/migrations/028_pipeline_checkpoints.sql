-- =============================================================================
-- Migration 028: Pipeline checkpoints table
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 21/05/2026
-- Ticket: AA-97 — Pre-UAT Migration
-- =============================================================================
-- Tracks LangGraph node completion per run to enable resume on failure.
-- UNIQUE(run_id, stage, node_name) allows idempotent upsert per graph node.
-- NOTE: acp_shared.idempotency_keys was already applied via ECS exec before
-- this file was created — its live schema has (tenant_id, stage) vs. file 029.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS acp_shared.pipeline_checkpoints (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID         NOT NULL REFERENCES acp_shared.acp_runs(run_id) ON DELETE CASCADE,
    stage         VARCHAR(20)  NOT NULL,
    node_name     VARCHAR(100) NOT NULL,
    status        VARCHAR(20)  NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    input_hash    VARCHAR(64),
    output_data   JSONB        NOT NULL DEFAULT '{}',
    error_message TEXT,
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, stage, node_name)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_checkpoints_run_id
    ON acp_shared.pipeline_checkpoints(run_id);

CREATE INDEX IF NOT EXISTS idx_pipeline_checkpoints_status
    ON acp_shared.pipeline_checkpoints(run_id, stage, status);

COMMENT ON TABLE acp_shared.pipeline_checkpoints IS
    'LangGraph node completion tracking per ACP run. UNIQUE(run_id,stage,node_name) enables idempotent upsert.';

INSERT INTO shared.schema_versions (version, description)
VALUES ('028', 'create acp_shared.pipeline_checkpoints [AA-97]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
