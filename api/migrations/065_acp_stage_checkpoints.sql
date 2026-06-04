-- =============================================================================
-- Migration 065: acp_stage_checkpoints — per-tour resume for S4.2 [AA-107]
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 2026-06-04
-- Ticket: AA-107 — S4.2 Per-Tour Checkpoint (Resume on Spot Interruption)
-- =============================================================================
-- S4.2 batch: 45 tours x 3 platforms = 135 pieces.
-- Spot interruption at tour #20 → full restart from scratch = waste.
-- This table tracks per-item completion so the batch runner can skip already-
-- complete items on resume. item_type='social_tour' for S4.2; extensible for
-- future stages (e.g. 'blog_tour', 'seo_tour').
-- Distinct from acp_shared.pipeline_checkpoints (LangGraph node tracking, 028).
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS acp_shared.acp_stage_checkpoints (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id       UUID        NOT NULL REFERENCES acp_shared.acp_runs(run_id) ON DELETE CASCADE,
    item_type    VARCHAR(50) NOT NULL,
    item_id      TEXT        NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'complete', 'failed', 'skipped_duplicate')),
    error_msg    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, item_type, item_id)
);

CREATE INDEX IF NOT EXISTS idx_acp_stage_checkpoints_run_item
    ON acp_shared.acp_stage_checkpoints(run_id, item_type, status);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('065', NOW(), 'acp_stage_checkpoints: per-tour resume for S4.2 [AA-107]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
