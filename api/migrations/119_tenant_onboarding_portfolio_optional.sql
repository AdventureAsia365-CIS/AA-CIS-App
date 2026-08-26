-- Migration 119: AA-472 — acp_shared.tenant_onboarding.portfolio_id no longer NOT NULL.
--
-- Context: Hướng B (ADR-2026-038) removes the mandatory pre-tenant Marketplace-portfolio seeding
-- step entirely — a new tenant's tour/atom selection is now made live by the tenant itself via
-- GET /v1/marketplace (AA-444), not curated in advance by staff via a finalized
-- acp_shared.marketplace_portfolios row. This migration is the DB-side half of that: it removes
-- the constraint that forced every create_tenant() to go through the now-deleted
-- POST /admin/tenants/{id}/seed-atoms (seed_tenant_atoms(), api/routers/admin.py) before Gate A
-- could ever approve a tenant (that endpoint 404'd without a tenant_onboarding row).
--
-- FK deliberately KEPT, only NOT NULL dropped (STEP0, AA-472 confirmed via pg_constraint on real
-- RDS 26/08/2026 — real name tenant_onboarding_portfolio_id_fkey, not guessed): a handful of
-- already-onboarded tenants have a real, non-NULL portfolio_id row referencing a real finalized
-- marketplace_portfolios row (from before this change) — that history stays valid and queryable.
-- No new tenant will ever populate this column again (create_tenant() now inserts
-- tenant_onboarding with portfolio_id=NULL directly, no seed-atoms step exists to set it), so the
-- FK becomes permanently dormant going forward, not actively exercised — but dropping it would
-- serve no purpose (nothing else to simplify) while removing it would foreclose ever re-deriving
-- which legacy tenants came from which portfolio.

BEGIN;

ALTER TABLE acp_shared.tenant_onboarding
    ALTER COLUMN portfolio_id DROP NOT NULL;

COMMENT ON COLUMN acp_shared.tenant_onboarding.portfolio_id IS
    'AA-472: nullable as of migration 119 — pre-tenant Marketplace-portfolio seeding was removed '
    '(Hướng B, ADR-2026-038); create_tenant() now inserts this row with portfolio_id=NULL always. '
    'FK to acp_shared.marketplace_portfolios kept only for legacy tenants onboarded before this '
    'change, not actively written going forward.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('119', now(),
    'AA-472: tenant_onboarding.portfolio_id DROP NOT NULL — mandatory Marketplace-portfolio '
    'seeding removed, create_tenant() self-seeds with portfolio_id=NULL, FK kept for legacy rows')
ON CONFLICT (version) DO NOTHING;

COMMIT;
