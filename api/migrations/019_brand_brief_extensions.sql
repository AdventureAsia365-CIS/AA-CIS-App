-- =============================================================================
-- Migration 019: tenant_brand_rule_versions audit table
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 19/05/2026
-- Ticket: AA-82 — Brand brief extensions
-- =============================================================================
-- All columns from the AA-82 spec (brand_type, core_idea, customer_segment,
-- customer_mindset, voice_examples, source_docx_s3_key) were already added
-- by migration 018 (AA-85). This migration only creates the versions table.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS shared.tenant_brand_rule_versions (
    version_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID        NOT NULL REFERENCES shared.tenants(tenant_id),
    snapshot            JSONB       NOT NULL,
    source_docx_s3_key  TEXT,
    source_type         TEXT        NOT NULL CHECK (source_type IN ('manual', 'docx_parse')),
    created_by          VARCHAR(50),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brand_rule_versions_tenant
    ON shared.tenant_brand_rule_versions (tenant_id, created_at DESC);

COMMIT;
