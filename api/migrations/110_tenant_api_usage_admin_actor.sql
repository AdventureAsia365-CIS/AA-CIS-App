-- Migration 110: AA-441 bug #1 — shared.tenant_api_usage can't record admin (/admin/*) traffic
--
-- Context (docs/claude_audit/AA-438-00-SUMMARY-admin-tier-audit.md #13,
-- AA-439-00-SUMMARY #13-generalization): rate_limit_middleware (api/middleware/rate_limit.py)
-- unconditionally skips every path that doesn't start with "/v1/" before it ever checks auth,
-- so shared.tenant_api_usage — the sole data source for the admin Dashboard's "Pipeline Health"
-- panel (admin_pipeline.py:3476) — has zero rows for any admin-driven activity, guaranteeing
-- every card reads idle regardless of real usage.
--
-- tenant_id is NOT NULL + FK'd to shared.tenants(tenant_id) — cannot hold an admin identity
-- as-is, and there is no actor-type distinction anywhere in this table today.
--
-- Nghiep's decision (AA-441 task, confirmed via AskUserQuestion rather than guessed): add
-- actor_type + admin_user_id columns, make tenant_id nullable, and wire rate_limit_middleware's
-- new /admin/* branch to read the x-admin-user-id header — already sent by the admin BFF proxy
-- (frontend/app/api/admin/[...path]/route.ts, AA-232) on every admin request, but never read by
-- any backend code until now (grep confirmed zero hits pre-this-migration). Mirrors the
-- reviewed_by/reviewed_by_legacy pattern from migration 074 (AA-232): add the new
-- properly-typed column alongside the old one rather than repurpose it.
--
-- admin_user_id is left nullable (not backfilled/required) because not every historical or
-- future admin request is guaranteed to carry a resolvable x-admin-user-id (e.g. legacy
-- ADMIN_SECRET-only fallback callers, per admin_pipeline.py:3311's own comment on that path).

BEGIN;

ALTER TABLE shared.tenant_api_usage
    ALTER COLUMN tenant_id DROP NOT NULL;

ALTER TABLE shared.tenant_api_usage
    ADD COLUMN IF NOT EXISTS actor_type VARCHAR(10) NOT NULL DEFAULT 'tenant'
        CHECK (actor_type IN ('tenant', 'admin'));

ALTER TABLE shared.tenant_api_usage
    ADD COLUMN IF NOT EXISTS admin_user_id UUID REFERENCES shared.admin_users(id);

-- A row must identify exactly one kind of actor: a tenant row keeps tenant_id set and
-- admin_user_id null; an admin row is the reverse. Prevents a future write from silently
-- leaving both/neither populated.
ALTER TABLE shared.tenant_api_usage
    ADD CONSTRAINT chk_tenant_api_usage_actor CHECK (
        (actor_type = 'tenant' AND tenant_id IS NOT NULL AND admin_user_id IS NULL) OR
        (actor_type = 'admin'  AND tenant_id IS NULL     AND admin_user_id IS NOT NULL) OR
        (actor_type = 'admin'  AND tenant_id IS NULL     AND admin_user_id IS NULL)
        -- last branch covers the legacy-ADMIN_SECRET-only-caller case noted above (no resolvable
        -- x-admin-user-id) — still logged as admin traffic, just without a per-user identity.
    );

CREATE INDEX IF NOT EXISTS idx_tenant_api_usage_actor_type ON shared.tenant_api_usage(actor_type);
CREATE INDEX IF NOT EXISTS idx_tenant_api_usage_admin_user_id ON shared.tenant_api_usage(admin_user_id);

COMMENT ON COLUMN shared.tenant_api_usage.actor_type IS
    'AA-441 migration 110: distinguishes tenant (/v1/*) vs admin (/admin/*) traffic in this shared usage log.';
COMMENT ON COLUMN shared.tenant_api_usage.admin_user_id IS
    'AA-441 migration 110: FK to shared.admin_users(id), populated from the x-admin-user-id header '
    '(AA-232, sent by the admin BFF proxy but unread by the backend until this migration). NULL '
    'when actor_type=admin but no resolvable per-user identity was present on the request '
    '(e.g. legacy ADMIN_SECRET-only callers).';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('110', NOW(), 'AA-441: shared.tenant_api_usage actor_type/admin_user_id — admin traffic tracking (bug #1)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
