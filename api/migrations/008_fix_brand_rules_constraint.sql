-- Migration 008: Fix tenant_brand_rules unique constraint
-- Allow multiple inactive versions per tenant (for version history)
-- Keep only 1 active version per tenant via partial unique index

BEGIN;

ALTER TABLE shared.tenant_brand_rules 
DROP CONSTRAINT IF EXISTS tenant_brand_rules_tenant_id_is_active_key;

DROP INDEX IF EXISTS shared.tenant_brand_rules_active_idx;

CREATE UNIQUE INDEX IF NOT EXISTS tenant_brand_rules_one_active_per_tenant
ON shared.tenant_brand_rules (tenant_id)
WHERE is_active = true;

COMMIT;
