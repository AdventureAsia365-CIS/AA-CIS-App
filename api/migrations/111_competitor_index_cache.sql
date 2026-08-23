-- Migration 111: acp_shared.competitor_index_cache
-- Project: AA-CIS (AA-445-02 — B4 CompetitorIndex / score_distinctiveness())
-- Date: 23/08/2026
--
-- Context (docs/claude_audit/AA-445-01-dfs-distinctiveness-step0-audit.md Q4): nothing in this
-- schema persists fetched competitor homepage text anywhere — acp_silver_s2.competitor_inputs
-- (AA-88) stores only the tenant-declared input URLs, and S2's Apify path never reads its own
-- crawl output back. score_distinctiveness()'s CompetitorIndex.phrases corpus needs somewhere
-- to live so a T5 atomize call doesn't re-fetch every competitor homepage from scratch on every
-- tour (real latency inside the synchronous T2->T3->T5 chain, needless outbound traffic).
--
-- Grain: (tenant_id, country) — matches acp_silver_s2.competitor_inputs' own grain, not per-
-- domain, since score_distinctiveness() compares against the WHOLE pooled phrase corpus across
-- a tenant's declared competitors for that country, not one domain at a time.
--
-- phrases: the flat list score_distinctiveness() actually scores against (CompetitorIndex.phrases).
-- competitors: {domain: [phrases]} breakdown, kept for future debugging/UI ("which competitor
-- contributed this overlap") — not read by score_distinctiveness() itself.
--
-- fetched_at + a 24h application-level TTL (services/acp_shared/competitor_index.py, not a DB
-- expires_at column — same style seo_context's Redis cache layer uses, simpler than adding a
-- second timestamp column here for a single fixed TTL).

BEGIN;

CREATE SCHEMA IF NOT EXISTS acp_shared;

CREATE TABLE IF NOT EXISTS acp_shared.competitor_index_cache (
    tenant_id    UUID         NOT NULL REFERENCES shared.tenants(tenant_id) ON DELETE CASCADE,
    country      VARCHAR(100) NOT NULL,
    phrases      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    competitors  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, country)
);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('111', NOW(), 'AA-445-02: acp_shared.competitor_index_cache — B4 CompetitorIndex phrase corpus cache')
ON CONFLICT (version) DO NOTHING;

COMMIT;
