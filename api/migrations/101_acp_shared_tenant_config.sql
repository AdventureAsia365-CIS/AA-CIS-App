-- Migration 101: acp_shared.tenant_config (AA-323 Gap 3)
--
-- Context: N4 (runway_map)/N5 (plan_quarter)/N6 (allocate_month) all take markets/channels as
-- caller-supplied parameters with no tenant-config table backing them -- every real caller
-- (api/routers/admin_atoms.py's preview-slotgrid) hardcodes markets=["US"], channels=["blog"].
-- That gap was flagged from day one in AA-301's own implementation notes and resurfaces in
-- AA-323's STEP 0 (docs/implementation-notes/AA-323.md).
--
-- Deliberately does NOT include capacity_posts_per_week: shared.tenants.posts_per_week
-- (migration 099, AA-384) already IS that value ("free tenant choice", read live by Mirror) --
-- duplicating it into a second table would create two sources of truth for the same number.
-- N6 callers read markets/channels from this table and capacity from shared.tenants.posts_per_week
-- via a single joined fetch (services/acp_planning/tenant_config.py::fetch_tenant_planning_config).
--
-- markets/channels are TEXT[], not a single value -- confirmed via STEP 0 read of
-- services/acp_planning/runway.py (RunwayCell has a `market` column per cell, runway_map() loops
-- `for mk in markets`) and allocator.py (`channels[slot_n % len(channels)]`, a round-robin across
-- multiple channels) -- both already designed as multi-value per tenant, not a single scalar.
--
-- No versioning/history table (unlike acp_shared.quarter_plan_version's deliberate full-versioning,
-- migration 092): quarter_plan_version versions because Gate B approval is a workflow with an
-- audit trail requirement. markets/channels is operational config with no such approval workflow
-- attached (like shared.tenants.posts_per_week itself, which is also a single mutable column, no
-- history) -- a future seasonal-override feature is out of scope here and would be its own ticket.
--
-- One row per tenant (tenant_id PK, not a UNIQUE constraint on a separate id) -- there is exactly
-- one "current" config per tenant, matching the shared.tenants.posts_per_week single-column shape.
-- Missing row = tenant never configured -- callers fall back to defaults (["US"], ["blog"]), same
-- values as the hardcoded demo constants they replace, so no behavior changes for a tenant that
-- hasn't been touched by the new UI yet.

BEGIN;

CREATE SCHEMA IF NOT EXISTS acp_shared;

CREATE TABLE IF NOT EXISTS acp_shared.tenant_config (
    tenant_id   UUID PRIMARY KEY REFERENCES shared.tenants(tenant_id),
    markets     TEXT[] NOT NULL DEFAULT ARRAY['US'],
    channels    TEXT[] NOT NULL DEFAULT ARRAY['blog'],
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tenant_config_markets_not_empty CHECK (array_length(markets, 1) > 0),
    CONSTRAINT tenant_config_channels_not_empty CHECK (array_length(channels, 1) > 0),
    CONSTRAINT tenant_config_channels_valid CHECK (
        channels <@ ARRAY['blog', 'facebook', 'tiktok', 'email']::text[]
    )
);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('101', now(), 'AA-323 Gap 3: acp_shared.tenant_config -- per-tenant markets/channels for N4-N6, capacity stays on shared.tenants.posts_per_week')
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- NOT covered by this migration (deliberately out of scope for AA-323):
-- - No backfill row per existing tenant -- fetch_tenant_planning_config() falls back to
--   (["US"], ["blog"]) for a tenant with no row, which is byte-for-byte the same default the
--   hardcoded demo constants used, so every existing tenant's Preview output is unchanged until
--   someone explicitly sets config via the new Tenants > Planning tab.
-- - No seasonal/quarterly override history -- see note above; a future ticket if needed.
