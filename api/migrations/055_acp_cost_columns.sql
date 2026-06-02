-- =============================================================================
-- Migration 055: ACP LLM cost tracking columns + acp_stage_runs table
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Ticket: AA-118 — LLM Cost Tracking End-to-End
-- =============================================================================
-- Adds total_llm_cost_usd to acp_shared.acp_runs.
-- Creates acp_shared.acp_stage_runs to record per-stage token usage.
-- UNIQUE(run_id, stage) supports idempotent upsert from record_stage_cost().
-- =============================================================================

BEGIN;

-- Total cost summary on the run (sum of all stages)
ALTER TABLE acp_shared.acp_runs
    ADD COLUMN IF NOT EXISTS total_llm_cost_usd NUMERIC(10,6) DEFAULT 0;

-- Per-stage cost + token breakdown
CREATE TABLE IF NOT EXISTS acp_shared.acp_stage_runs (
    id             UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id         UUID          NOT NULL REFERENCES acp_shared.acp_runs(run_id) ON DELETE CASCADE,
    stage          VARCHAR(30)   NOT NULL,
    llm_cost_usd   NUMERIC(10,6) NOT NULL DEFAULT 0,
    tokens_input   INTEGER       NOT NULL DEFAULT 0,
    tokens_output  INTEGER       NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_acp_stage_runs_run_id
    ON acp_shared.acp_stage_runs(run_id);

-- Safe add if table already existed without cost columns
ALTER TABLE acp_shared.acp_stage_runs
    ADD COLUMN IF NOT EXISTS llm_cost_usd   NUMERIC(10,6) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tokens_input   INTEGER       DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tokens_output  INTEGER       DEFAULT 0;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('055', NOW(), 'acp cost tracking columns [AA-118]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
