-- =============================================================================
-- Migration 062: gate3_context column on blog_drafts [AA-116]
-- Project: AA-CIS | Date: 2026-06-04
-- Ticket: AA-116 — Gate 3 retry context (circuit breaker history)
-- =============================================================================
-- Stores per-attempt evaluator score history when S4.1 circuit breaker fires.
-- NULL when first attempt passes (no retries). Non-null means retries occurred.
-- =============================================================================

BEGIN;

ALTER TABLE acp_silver_s4.blog_drafts
    ADD COLUMN IF NOT EXISTS gate3_context JSONB;

COMMENT ON COLUMN acp_silver_s4.blog_drafts.gate3_context IS
    'Retry history when evaluator circuit breaker fired: attempts, best_score, score progression. NULL when first attempt passed.';

INSERT INTO shared.schema_versions (version, description)
VALUES ('062', 'add gate3_context JSONB to blog_drafts [AA-116]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
