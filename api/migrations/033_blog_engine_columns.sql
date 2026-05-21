-- =============================================================================
-- Migration 033 — blog_drafts S4 Blog Engine columns
-- AA-46: Add validation + SEO + HITL + pipeline tracking columns
-- Applied: 21/05/2026 | blog_drafts previously had 22 columns
-- =============================================================================

ALTER TABLE acp_silver_s4.blog_drafts
  ADD COLUMN IF NOT EXISTS validation_passed   BOOLEAN,
  ADD COLUMN IF NOT EXISTS validation_score    NUMERIC(4,2),
  ADD COLUMN IF NOT EXISTS failing_checks      JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS repair_targets      JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS seo_score           NUMERIC(4,2),
  ADD COLUMN IF NOT EXISTS seo_issues          JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS translated_content  JSONB,
  ADD COLUMN IF NOT EXISTS hitl_gate3_status   TEXT CHECK (hitl_gate3_status IN ('pending','approved','rejected')),
  ADD COLUMN IF NOT EXISTS hitl_reviewer_id    VARCHAR(50),
  ADD COLUMN IF NOT EXISTS hitl_decided_at     TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS rewrite_count       SMALLINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS pipeline_version    VARCHAR(10) NOT NULL DEFAULT 'v1';
