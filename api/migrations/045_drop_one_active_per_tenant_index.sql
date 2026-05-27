-- Drop partial unique index that blocks multiple active brands per tenant
-- Root cause of Brand Identity POST/PUT 500 errors (AA-129, 27/05/2026)
DROP INDEX IF EXISTS shared.tenant_brand_rules_one_active_per_tenant;
