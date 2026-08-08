-- Migration 097: acp_shared.marketplace_portfolios (AA-330 Phần A)
--
-- Context: AA-330 STEP 0 (Linear comment, 07/08/2026) confirmed the marketplace/portfolio flow
-- runs BEFORE a tenant exists (D4 Mode A / SSP model — tenant licenses AA's platform-scoped
-- catalog, does not bring its own tours). shared.tenants has no FK-able row yet at this point, and
-- `is_active` is already ambiguous (2 unrelated meanings on the same 11 live tenants — GDPR-
-- cancelled vs. draft/test) — piling a third "prospect" meaning onto it was rejected in favor of
-- this standalone table. No FK to shared.tenants: N1 (AA-309) reads portfolio_id -> tour_ids to
-- seed tenant_atom_state AFTER the real tenant is created; the reverse direction (tenant ->
-- portfolio) is the only one that could exist, and only after N1 runs.
--
-- Phần A ships browse/filter/draft-save only (this migration + admin_marketplace.py). Phần B
-- (runway_months() formula, price_raw parser, finalize draft->finalized) is explicitly deferred —
-- STEP 0 found no existing runway-months-from-atom-count function anywhere (grep
-- runway_months/estimate_runway/months_of -> 0 hits) and price_raw is free text never surveyed the
-- way duration_raw/period were before runway.py's parsers were written. atom_snapshot therefore
-- carries only a real, live-computed total_atoms; runway_months/posts_per_week are NULL, not
-- fabricated, until Phần B lands.
--
-- No RLS: unlike acp_shared.acp_v2_runs/acp_v2_slots (094/096, both tenant_id-scoped), this table
-- has no tenant_id column at all (see above) — there is nothing to scope a tenant_isolation policy
-- on. Access control is the same x-admin-secret gate as admin_atoms.py/admin.py, not RLS.

BEGIN;

CREATE SCHEMA IF NOT EXISTS acp_shared;

CREATE TABLE IF NOT EXISTS acp_shared.marketplace_portfolios (
    portfolio_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tour_ids       UUID[] NOT NULL,
    filters_used   JSONB,
    atom_snapshot  JSONB,
    status         TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'finalized')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_at   TIMESTAMPTZ
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aa_app_user') THEN
        GRANT USAGE ON SCHEMA acp_shared TO aa_app_user;
        GRANT SELECT, INSERT, UPDATE ON acp_shared.marketplace_portfolios TO aa_app_user;
    END IF;
END $$;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('097', now(), 'AA-330 Phần A: acp_shared.marketplace_portfolios — draft portfolio storage before tenant exists')
ON CONFLICT (version) DO NOTHING;

COMMIT;
