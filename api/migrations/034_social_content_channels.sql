-- =============================================================================
-- Migration 034 — social_content channel columns
-- AA-93: Add 8 columns for dual-mode social content engine
-- social_content previously had 16 columns (AA-83)
-- Applied: 21/05/2026
-- =============================================================================

ALTER TABLE acp_silver_s4.social_content
  ADD COLUMN IF NOT EXISTS channel VARCHAR(50)
    CHECK (channel IN ('facebook','linkedin','tiktok','instagram','email','newsletter','landing_page','ads')),
  ADD COLUMN IF NOT EXISTS content_brief  JSONB,
  ADD COLUMN IF NOT EXISTS selected_angle TEXT,
  ADD COLUMN IF NOT EXISTS formula_used   VARCHAR(50),
  ADD COLUMN IF NOT EXISTS mode           VARCHAR(10) CHECK (mode IN ('auto','guided')),
  ADD COLUMN IF NOT EXISTS quality_warnings TEXT,
  ADD COLUMN IF NOT EXISTS llm_provider   VARCHAR(20) NOT NULL DEFAULT 'bedrock',
  ADD COLUMN IF NOT EXISTS model_id       VARCHAR(100);
