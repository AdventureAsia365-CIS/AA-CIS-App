-- AA-129: add brand_name column to support named multi-brand identities
ALTER TABLE shared.tenant_brand_rules ADD COLUMN IF NOT EXISTS brand_name TEXT;
CREATE INDEX IF NOT EXISTS idx_brand_rules_tenant_brand ON shared.tenant_brand_rules(tenant_id, brand_name);
