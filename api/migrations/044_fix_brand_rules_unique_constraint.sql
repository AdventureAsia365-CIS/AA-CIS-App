-- AA-129: drop UNIQUE(tenant_id, is_active) — prevents multi-brand per tenant
-- Replace with UNIQUE(tenant_id, brand_name, version) to allow multiple active brands.
-- Also ensures brand_name column exists (idempotent with 043).

BEGIN;

ALTER TABLE shared.tenant_brand_rules
    ADD COLUMN IF NOT EXISTS brand_name TEXT;

-- Drop old single-active-per-tenant constraint
ALTER TABLE shared.tenant_brand_rules
    DROP CONSTRAINT IF EXISTS tenant_brand_rules_tenant_id_is_active_key;

-- NULL brand_name → 'default' so the new UNIQUE constraint can function
UPDATE shared.tenant_brand_rules
    SET brand_name = 'default'
    WHERE brand_name IS NULL;

-- New constraint: (tenant, brand_name, version) must be unique
ALTER TABLE shared.tenant_brand_rules
    ADD CONSTRAINT uq_brand_rules_tenant_brand_version
    UNIQUE (tenant_id, brand_name, version);

CREATE INDEX IF NOT EXISTS idx_brand_rules_tenant_brand
    ON shared.tenant_brand_rules (tenant_id, brand_name);

COMMIT;
