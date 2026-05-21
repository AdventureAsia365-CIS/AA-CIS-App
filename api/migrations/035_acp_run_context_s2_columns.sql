-- =============================================================================
-- Migration 035: Add S2 output columns to acp_run_context
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 21/05/2026
-- Ticket: AA-98 — S2 LangGraph compliance
-- =============================================================================
-- PRD v1.3 §3.3 requires S2 to write keyword_clusters, competitor/AA tour
-- matches, market_preference, and confidence_score to acp_run_context for
-- downstream S3 anti-cannibalization and Gate 1 auto-approve.
-- =============================================================================

BEGIN;

ALTER TABLE acp_shared.acp_run_context
    ADD COLUMN IF NOT EXISTS s2_keyword_clusters  JSONB,
    ADD COLUMN IF NOT EXISTS s2_market_preference JSONB,
    ADD COLUMN IF NOT EXISTS s2_aa_tour_matches   JSONB,
    ADD COLUMN IF NOT EXISTS s2_confidence_score  NUMERIC(5,4);

COMMENT ON COLUMN acp_shared.acp_run_context.s2_confidence_score IS
    '0.0–1.0 scale (normalized from synthesize 0-100). Gate 1 auto-approve threshold: 0.85';
COMMENT ON COLUMN acp_shared.acp_run_context.s2_keyword_clusters IS
    'Keyword clusters from synthesize node: [{cluster_name, keywords[], intent}]';
COMMENT ON COLUMN acp_shared.acp_run_context.s2_market_preference IS
    'Market positioning summary from synthesize: {dominant_duration, dominant_style, price_band}';
COMMENT ON COLUMN acp_shared.acp_run_context.s2_aa_tour_matches IS
    'AA tour match suggestions: [{keyword, tour_suggestion, match_reason}]';

INSERT INTO shared.schema_versions (version, description)
VALUES ('035', 'add s2 output columns to acp_run_context [AA-98]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
