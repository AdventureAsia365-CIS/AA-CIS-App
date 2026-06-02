-- =============================================================================
-- Migration 054: Add country column to shared.tenants
-- Ticket: AA-159 — tenant page rebuild + count/country fixes
-- Date: 02/06/2026
-- =============================================================================

BEGIN;

ALTER TABLE shared.tenants ADD COLUMN IF NOT EXISTS country TEXT;

-- Seed known tenant countries
UPDATE shared.tenants SET country = 'Thailand' WHERE slug = 'bluepoppy' AND country IS NULL;

INSERT INTO shared.schema_versions (version, description)
VALUES ('054', 'tenants.country column [AA-159]')
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- DOWN
-- ALTER TABLE shared.tenants DROP COLUMN IF EXISTS country;
