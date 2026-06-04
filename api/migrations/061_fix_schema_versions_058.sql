-- =============================================================================
-- Migration 061: Backfill schema_versions row for migration 058
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Ticket: AA-169 — S2 auto crash-recovery
-- =============================================================================
-- Migration 058 (canary_tenant_flag) was applied but its schema_versions INSERT
-- was skipped. This migration backfills the missing row.
-- ON CONFLICT DO NOTHING makes it safe to apply regardless.
-- =============================================================================

BEGIN;

INSERT INTO shared.schema_versions (version, description)
VALUES ('058', 'canary skeleton: is_canary + skip_hitl on shared.tenants')
ON CONFLICT (version) DO NOTHING;

INSERT INTO shared.schema_versions (version, description)
VALUES ('061', 'backfill schema_versions row for migration 058 [AA-169]')
ON CONFLICT (version) DO NOTHING;

COMMIT;
