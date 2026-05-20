-- =============================================================================
-- Migration 029: S2 idempotency_keys (new) + visibility_reports column additions
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 20/05/2026
-- Ticket: AA-43 — S2 LangGraph Research Agent
-- =============================================================================
-- Numbered 029 because 028 (idempotency_keys) was applied via ECS exec before
-- this file was created. IF NOT EXISTS / IF EXISTS guards make this safe to re-run.
--
-- acp_silver_s2.visibility_reports already exists with columns:
--   report_id, run_id, tenant_id, country, keyword_gaps, competitor_data,
--   google_trends, reddit_insights, gsc_data, top_opportunities, created_at
-- This migration adds the 4 columns needed by the S2 synthesize node.
--
-- acp_shared.idempotency_keys: new table for S2 run dedup.
-- NOTE: acp_silver_s2 schema created in migration 027.
-- =============================================================================

BEGIN;

-- Add missing columns to existing visibility_reports table
ALTER TABLE acp_silver_s2.visibility_reports
    ADD COLUMN IF NOT EXISTS fetched_at       TIMESTAMPTZ  DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS expires_at       TIMESTAMPTZ  DEFAULT NOW() + INTERVAL '7 days',
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS primary_keywords JSONB        DEFAULT '[]';

CREATE INDEX IF NOT EXISTS idx_visibility_reports_fetched_at
    ON acp_silver_s2.visibility_reports(fetched_at DESC);

-- Idempotency dedup table for S2 run triggers
CREATE TABLE IF NOT EXISTS acp_shared.idempotency_keys (
    key        TEXT         PRIMARY KEY,
    run_id     UUID         NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ  NOT NULL DEFAULT NOW() + INTERVAL '24 hours'
);

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_expires_at
    ON acp_shared.idempotency_keys(expires_at);

COMMIT;
