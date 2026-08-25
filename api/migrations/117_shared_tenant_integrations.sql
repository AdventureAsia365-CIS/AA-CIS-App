-- Migration 117: AA-457 [T11 PR1] — shared.tenant_integrations, the credentials-layer table for
-- per-tenant third-party integrations (WordPress first). STEP0 (AA-456's report, §7) confirmed
-- this needed to be a NEW table — grepped the whole repo for "tenant_integrations", zero hits,
-- and shared.tenants itself has no credential-shaped columns to repurpose.
--
-- Shape follows shared.tenant_seo_config's real precedent (migration 003): one row per
-- (tenant, thing), JSONB for the non-secret config, UNIQUE constraint preventing duplicates.
-- Generalized to (tenant_id, integration_type) instead of tenant_seo_config's bare
-- UNIQUE(tenant_id) — this table is meant to hold more than just WordPress later (webflow/ghost/
-- other CMS types, matching acp_cms_publish_queue.cms_type's existing enum shape), so a single
-- tenant needs one row PER integration type, not one row total.
--
-- secret_key stores ONLY the Secrets Manager SecretId string (e.g. "acp/cms/{tenant_id}") — the
-- real WordPress application password NEVER touches this table or any other DB column, matching
-- the DB-never-holds-plaintext-credentials principle already applied everywhere else in this
-- codebase (RDS creds, DataForSEO creds, Anthropic key — all Secrets Manager, never a DB column).
--
-- Reuses the exact "acp/cms/{tenant_id}" naming convention v1_s4_blog.py already invented
-- (never actually used — confirmed live, 0 secrets existed under acp/ before this task) rather
-- than inventing a new prefix — see AA-456 STEP0 §4.

BEGIN;

CREATE TABLE IF NOT EXISTS shared.tenant_integrations (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES shared.tenants(tenant_id) ON DELETE CASCADE,
    integration_type   TEXT NOT NULL,
    config             JSONB NOT NULL DEFAULT '{}',
    secret_key         TEXT,
    connected_at       TIMESTAMPTZ,
    last_verified_at   TIMESTAMPTZ,
    last_verify_error  TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, integration_type)
);

COMMENT ON TABLE shared.tenant_integrations IS
    'AA-457 — per-tenant third-party integration credentials/config. config holds non-secret '
    'fields only (e.g. {"site_url": "..."}). secret_key points to a Secrets Manager SecretId '
    '(e.g. "acp/cms/{tenant_id}" for wordpress) — the real credential value lives ONLY in '
    'Secrets Manager, never in this table.';

CREATE INDEX IF NOT EXISTS idx_tenant_integrations_tenant
    ON shared.tenant_integrations(tenant_id);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('117', now(),
    'AA-457: shared.tenant_integrations — per-tenant WordPress (T11) credentials layer, '
    'secret_key points to Secrets Manager only, no plaintext credential columns')
ON CONFLICT (version) DO NOTHING;

COMMIT;
