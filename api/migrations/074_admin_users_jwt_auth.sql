-- Migration 074: AA-232 — Per-user admin JWT auth (shared.admin_users)
--
-- Context: BFF admin proxy (/api/admin/*, /api/pipeline/*) currently auths
-- with a single shared ADMIN_SECRET — no per-user identity. Backend
-- (verify_tenant_api_key in auth.py) maps every valid-secret request onto a
-- fixed sentinel AA_INTERNAL_ADMIN_SUB. generated_content.reviewed_by is a
-- free-text varchar populated by an unverified x-reviewer-id header (AA-241
-- shim, "temporary until AA-232").
--
-- This migration creates shared.admin_users (mirrors shared.tenants shape:
-- UUID PK w/ gen_random_uuid(), is_active BOOLEAN, created_at/updated_at
-- TIMESTAMPTZ DEFAULT NOW(), unique natural key). Auth uses bcrypt
-- password_hash (human username+password login — NOT the sha256
-- api_key_hash pattern tenants use, a deliberate deviation approved
-- ADR-2026-017 S86: admins need real login UX, not an API key).
--
-- Table is created EMPTY. No seed users — Nghiep inserts real users by hand
-- after this migration lands (bcrypt hash generated out-of-band).
--
-- reviewed_by FK wiring (ADR-2026-017, final S86 decision — supersedes the
-- ADR's original free-text-only plan):
--   - raw_tours.reviewed_by (UUID, 0 rows, migration 024) — FK added
--     directly, no backfill needed (table empty on this column).
--   - generated_content.reviewed_by (varchar(128), 1 live row = "nghiep",
--     migration 072 AA-241 shim) — DO NOT touch this column's type or data
--     in this migration. Renamed to reviewed_by_legacy (kept, not dropped)
--     and a new nullable reviewed_by UUID FK column added alongside it.
--     Backfill (UPDATE generated_content SET reviewed_by = <admin_users.id
--     for username='nghiep'>) is a manual follow-up step AFTER Nghiep
--     inserts the "nghiep" admin_users row — doing it automatically here
--     risks silently losing the row if the username doesn't match.
--
-- Enum shared.admin_role mirrors plan_tier_enum's pattern, created via the
-- idempotent DO $$ IF NOT EXISTS $$ guard (copied from migration 021) —
-- CREATE TYPE must NOT run inside a transaction block.
--
-- Single shared DB — apply once against the shared Dev+Prod DB per project
-- convention (single-env architecture, see aa-cis-schema skill).

-- ── Enum (outside transaction — ALTER TYPE / CREATE TYPE gotcha) ───────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typname = 'admin_role' AND n.nspname = 'shared'
    ) THEN
        CREATE TYPE shared.admin_role AS ENUM ('admin', 'reviewer');
    END IF;
END $$;

-- ── Table + FK wiring (transactional) ───────────────────────────────────────
BEGIN;

CREATE TABLE IF NOT EXISTS shared.admin_users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          shared.admin_role NOT NULL DEFAULT 'reviewer',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE shared.admin_users IS
    'AA-232: per-user admin/reviewer accounts for JWT login (/auth/admin-login). '
    'Table created empty by migration 074 — Nghiep inserts real rows by hand.';

-- raw_tours.reviewed_by: UUID column already exists (migration 024), 0 rows
-- populated — safe to FK directly, no backfill required.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_raw_tours_reviewed_by_admin_users'
          AND table_schema = 'silver_aa_internal'
    ) THEN
        ALTER TABLE silver_aa_internal.raw_tours
            ADD CONSTRAINT fk_raw_tours_reviewed_by_admin_users
            FOREIGN KEY (reviewed_by) REFERENCES shared.admin_users(id);
    END IF;
END $$;

-- generated_content.reviewed_by: varchar(128), 1 live row ("nghiep",
-- migration 072). DO NOT alter/drop — rename to _legacy and add a fresh
-- nullable UUID FK column. Backfill is a manual follow-up after real
-- admin_users rows exist.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'silver_aa_internal'
          AND table_name = 'generated_content'
          AND column_name = 'reviewed_by'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'silver_aa_internal'
          AND table_name = 'generated_content'
          AND column_name = 'reviewed_by_legacy'
    ) THEN
        ALTER TABLE silver_aa_internal.generated_content
            RENAME COLUMN reviewed_by TO reviewed_by_legacy;
    END IF;
END $$;

ALTER TABLE silver_aa_internal.generated_content
    ADD COLUMN IF NOT EXISTS reviewed_by UUID REFERENCES shared.admin_users(id);

COMMENT ON COLUMN silver_aa_internal.generated_content.reviewed_by_legacy IS
    'AA-232 migration 074: pre-JWT free-text reviewer handle (was reviewed_by). '
    'Kept for audit history — do not write to this column going forward.';
COMMENT ON COLUMN silver_aa_internal.generated_content.reviewed_by IS
    'AA-232 migration 074: FK to shared.admin_users(id), populated from verified JWT claim. '
    'NULL until manual backfill after real admin_users rows exist (see migration header).';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('074', NOW(), 'AA-232: shared.admin_users + reviewed_by FK wiring (raw_tours direct, generated_content legacy+new column)')
ON CONFLICT (version) DO NOTHING;

COMMIT;