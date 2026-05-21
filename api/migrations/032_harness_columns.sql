-- =============================================================================
-- Migration 032 — Harness H-1/H-2 Columns
-- AA-49: Isolated Evaluator + Post-Processor infrastructure
-- Applied: 21/05/2026 (columns already existed in live DB before file creation)
-- =============================================================================

-- blog_drafts: evaluator score + hash + rule tracking
ALTER TABLE acp_silver_s4.blog_drafts
  ADD COLUMN IF NOT EXISTS evaluator_score        NUMERIC(3,1),
  ADD COLUMN IF NOT EXISTS evaluator_input_hash   VARCHAR(64),
  ADD COLUMN IF NOT EXISTS review_flags           JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS rules_applied          JSONB NOT NULL DEFAULT '[]'::jsonb;

-- acp_hitl_requests: structured rejection + rule feedback loop
ALTER TABLE acp_shared.acp_hitl_requests
  ADD COLUMN IF NOT EXISTS rejection_note_structured  JSONB,
  ADD COLUMN IF NOT EXISTS rule_created_id            UUID REFERENCES acp_shared.acp_output_rules(rule_id);
