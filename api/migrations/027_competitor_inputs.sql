-- =============================================================================
-- Migration 027: Competitor URL tracking table
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 19/05/2026
-- Ticket: AA-88 — Competitor URL management
-- =============================================================================
-- Creates acp_silver_s2 schema and competitor_inputs table.
-- FK: shared.tenants(tenant_id) — tenant_id is the PK, not id.
-- added_by: plain UUID, no FK (shared.users does not exist yet).
-- =============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS acp_silver_s2;

CREATE TABLE IF NOT EXISTS acp_silver_s2.competitor_inputs (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID         NOT NULL REFERENCES shared.tenants(tenant_id) ON DELETE CASCADE,
    country     VARCHAR(100) NOT NULL,
    url         TEXT         NOT NULL,
    label       VARCHAR(255),
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    added_by    UUID,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, url)
);

CREATE INDEX IF NOT EXISTS idx_competitor_inputs_tenant_country
    ON acp_silver_s2.competitor_inputs(tenant_id, country);

COMMIT;
