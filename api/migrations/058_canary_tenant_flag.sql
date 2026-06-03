-- =============================================================================
-- Migration 058: Canary tenant flags
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Ticket: AA-143 — Synthetic Canary S0→S1
-- =============================================================================
-- Adds is_canary and skip_hitl flags to shared.tenants.
-- is_canary: tenant is excluded from billing aggregates + quota enforcement.
-- skip_hitl: HITL gates are auto-approved for this tenant (canary bypass).
-- =============================================================================

BEGIN;

ALTER TABLE shared.tenants
    ADD COLUMN IF NOT EXISTS is_canary  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS skip_hitl  BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN shared.tenants.is_canary IS
    'TRUE for synthetic canary tenant — excluded from billing and quota checks';
COMMENT ON COLUMN shared.tenants.skip_hitl IS
    'TRUE to auto-approve all HITL gates (used by canary and test tenants)';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('058', NOW(), 'canary tenant flags [AA-143]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
