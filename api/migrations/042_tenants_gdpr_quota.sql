-- =============================================================================
-- Migration 042: GDPR columns + acp_quota_ledger [AA-63]
-- Project: AA-CIS | Date: 21/05/2026
-- =============================================================================
-- M1: 3 GDPR/brand-brief columns on shared.tenants
-- M2: acp_quota_ledger — monthly run quota per tenant
-- NOTE: tenant_id is UUID in shared.tenants — quota_ledger uses UUID FK.
-- =============================================================================

BEGIN;

-- M1: GDPR + brand brief reuse columns
ALTER TABLE shared.tenants
    ADD COLUMN IF NOT EXISTS last_brand_brief_s3_key TEXT,
    ADD COLUMN IF NOT EXISTS cancelled_at            TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cancellation_reason     TEXT;

COMMENT ON COLUMN shared.tenants.last_brand_brief_s3_key IS
    'S3 key of last uploaded brand brief DOCX — auto-fill for next S0 run';
COMMENT ON COLUMN shared.tenants.cancelled_at IS
    'GDPR offboarding timestamp — set by POST /admin/tenants/{id}/offboard';

-- M2: Monthly run quota per tenant
CREATE TABLE IF NOT EXISTS acp_shared.acp_quota_ledger (
    ledger_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES shared.tenants(tenant_id) ON DELETE CASCADE,
    s2_runs_limit   INTEGER     NOT NULL DEFAULT 10,
    s3_runs_limit   INTEGER     NOT NULL DEFAULT 10,
    s4_blogs_limit  INTEGER     NOT NULL DEFAULT 50,
    s2_runs_used    INTEGER     NOT NULL DEFAULT 0,
    s3_runs_used    INTEGER     NOT NULL DEFAULT 0,
    s4_blogs_used   INTEGER     NOT NULL DEFAULT 0,
    reset_at        TIMESTAMPTZ NOT NULL DEFAULT (DATE_TRUNC('month', NOW()) + INTERVAL '1 month'),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_quota_tenant
    ON acp_shared.acp_quota_ledger(tenant_id);

COMMENT ON TABLE acp_shared.acp_quota_ledger IS
    'Monthly run quota per tenant. reset_at = first day of next month.';

-- Seed existing tenants with default quota
INSERT INTO acp_shared.acp_quota_ledger (tenant_id)
SELECT tenant_id FROM shared.tenants
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO shared.schema_versions (version, description)
VALUES ('042', 'GDPR columns + acp_quota_ledger [AA-63]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
