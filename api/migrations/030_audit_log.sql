-- AA-59: audit_log table for ACP security hardening
CREATE TABLE IF NOT EXISTS acp_shared.audit_log (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     VARCHAR(50),
  actor         VARCHAR(64),
  action        VARCHAR(64),
  resource_type VARCHAR(32),
  resource_id   TEXT,
  details       JSONB,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_tenant
  ON acp_shared.audit_log(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_action
  ON acp_shared.audit_log(action, created_at DESC);
