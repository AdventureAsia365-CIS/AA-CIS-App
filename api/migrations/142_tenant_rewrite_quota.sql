-- Migration 142: AA-489 -- shared.tenant_rewrite_usage (per-tenant, per-calendar-month
-- rewrite quota, enforced for real for the first time)
--
-- STEP0 (AA-489) confirmed nothing currently limits a tenant's rewrite calls:
-- PLAN_LIMITS.tours_per_month (admin.py) is defined but only ever displayed in the admin
-- tenant-detail response, never enforced; raw_tours.rewrite_count (migration 033) is a dead
-- column with 0 callers; rate_limit_middleware throttles requests/minute across ALL /v1/*
-- paths, not a monthly rewrite count. Deliberately NOT reusing acp_quota_ledger -- that is
-- ACPv1 S2/S3/S4 quota, an architecture officially dead since 13/07/2026 (ADRs).
--
-- Business decisions (Nghiệp not available mid-chain to confirm live -- conservative defaults
-- per the chain's own build prompt, flagged for review, not silently treated as final):
--   * Limit = PLAN_LIMITS[plan_tier].tours_per_month as it already exists in admin.py, no new
--     number invented (starter=100, growth=500, business=2000, internal=999999).
--   * Reset = calendar month (year_month = to_char(now(), 'YYYY-MM')), not rolling 30d.
--   * Hard-block over quota (429), not soft-warning -- issue's own stated purpose is LLM cost
--     control, which a warn-only gate doesn't actually provide.
--
-- One row per (tenant_id, year_month), incremented atomically at the point a rewrite request
-- is ACCEPTED (trigger_rewrite(), before the LLM call) -- consistent with "quota consumed by
-- requesting", the same semantics PLAN_LIMITS.rate_limit_rpm already uses via
-- rate_limit_middleware. A rewrite that fails downstream (LLM error, validation) still counts
-- against quota, same as a rate-limited request still counts toward RPM.

BEGIN;

CREATE TABLE IF NOT EXISTS shared.tenant_rewrite_usage (
    tenant_id     UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    year_month    TEXT NOT NULL,  -- 'YYYY-MM', calendar month, e.g. '2026-09'
    rewrite_count INT  NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, year_month)
);

COMMENT ON TABLE shared.tenant_rewrite_usage IS
    'AA-489 -- real per-tenant, per-calendar-month rewrite count, enforced (hard-block) in
    v1_tours.py::trigger_rewrite() against PLAN_LIMITS[plan_tier].tours_per_month. NOT
    acp_quota_ledger (that is dead ACPv1 S2/S3/S4 quota). One row per (tenant_id, year_month),
    created on first rewrite of the month, incremented on every accepted rewrite request
    (accepted = passed the quota check, regardless of downstream LLM outcome).';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('142', now(),
    'AA-489: shared.tenant_rewrite_usage -- real per-tenant/month rewrite quota, first-ever
    enforcement (was defined in PLAN_LIMITS but never checked)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
