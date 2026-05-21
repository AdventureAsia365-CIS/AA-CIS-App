-- =============================================================================
-- Migration 019 — acp_silver_s4.social_content
-- AA-83: Social content table for S4 Social pipeline output
-- Schema: acp_silver_s4 (existing)
-- FK: acp_shared.acp_runs(run_id) — verified exists before apply
-- RLS: tenant_isolation policy using app.current_tenant setting
-- Applied: 21/05/2026
-- =============================================================================

CREATE TABLE IF NOT EXISTS acp_silver_s4.social_content (
  social_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id        UUID NOT NULL REFERENCES acp_shared.acp_runs(run_id),
  tenant_id     VARCHAR(50) NOT NULL,
  tour_id       UUID NOT NULL,
  tour_name     TEXT,
  tiktok        JSONB,
  facebook_post JSONB,
  facebook_ad   JSONB,
  strategy_notes JSONB,
  validation_status TEXT CHECK (validation_status IN
    ('pending','passed','failed_rewrite','flagged_human')),
  validation_issues TEXT[],
  rewrite_attempt   SMALLINT DEFAULT 0,
  hitl_gate_3_social_status TEXT CHECK (hitl_gate_3_social_status IN
    ('pending','approved','rejected')),
  hitl_reviewer_id  VARCHAR(50),
  hitl_decided_at   TIMESTAMPTZ,
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- RLS: TRUE second arg prevents error when app.current_tenant is not set
ALTER TABLE acp_silver_s4.social_content ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON acp_silver_s4.social_content
  USING (tenant_id = current_setting('app.current_tenant', TRUE));

CREATE INDEX IF NOT EXISTS idx_social_content_run_tenant
  ON acp_silver_s4.social_content (run_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_social_content_tour
  ON acp_silver_s4.social_content (tour_id);
CREATE INDEX IF NOT EXISTS idx_social_content_hitl_pending
  ON acp_silver_s4.social_content (hitl_gate_3_social_status)
  WHERE hitl_gate_3_social_status = 'pending';
