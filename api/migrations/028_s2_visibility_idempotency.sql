-- =============================================================================
-- Migration 028: S2 visibility_reports + idempotency_keys
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 20/05/2026
-- Ticket: AA-43 — S2 LangGraph Research Agent
-- =============================================================================
-- acp_silver_s2.visibility_reports: one row per S2 run, stores visibility
--   report JSONB + S3 pointers for each data source. TTL guarded via fetched_at.
-- acp_shared.idempotency_keys: dedup table keyed on tenant_id:country.
--   expires_at defaults 24h to prevent stale locks.
-- NOTE: acp_silver_s2 schema created in migration 027.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS acp_silver_s2.visibility_reports (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                UUID         UNIQUE,
    tenant_id             UUID         NOT NULL,
    country               VARCHAR(100) NOT NULL,
    visibility_report     JSONB,
    confidence_score      NUMERIC(5,2),
    keyword_count         INTEGER      NOT NULL DEFAULT 0,
    existing_content_risk BOOLEAN      NOT NULL DEFAULT FALSE,
    keywords_s3_key       TEXT,
    competitors_s3_key    TEXT,
    trends_s3_key         TEXT,
    reddit_s3_key         TEXT,
    gsc_s3_key            TEXT,
    fetched_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_visibility_reports_tenant_country
    ON acp_silver_s2.visibility_reports(tenant_id, country);

CREATE INDEX IF NOT EXISTS idx_visibility_reports_fetched_at
    ON acp_silver_s2.visibility_reports(fetched_at DESC);

CREATE TABLE IF NOT EXISTS acp_shared.idempotency_keys (
    key        TEXT         PRIMARY KEY,
    run_id     UUID         NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ  NOT NULL DEFAULT NOW() + INTERVAL '24 hours'
);

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_expires_at
    ON acp_shared.idempotency_keys(expires_at);

COMMIT;
