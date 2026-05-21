-- =============================================================================
-- Migration 037: Add confidence_score to acp_output_rules
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 21/05/2026
-- Ticket: AA-99 — H-3 Mistake→Rule pipeline
-- =============================================================================
-- PRD v1.1 §5.3: Haiku extracts rule from rejection note.
-- confidence_score (0.0–1.0) stored alongside each auto-created rule.
-- source_type='hitl_rejection' already in CHECK constraint.
-- source_hitl_id FK already exists.
-- =============================================================================

BEGIN;

ALTER TABLE acp_shared.acp_output_rules
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,4);

COMMENT ON COLUMN acp_shared.acp_output_rules.confidence_score IS
    '0.0–1.0. H-3 auto-create threshold: >= 0.80 (PRD v1.1 §5.3)';

INSERT INTO shared.schema_versions (version, description)
VALUES ('037', 'add confidence_score to acp_output_rules [AA-99]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
