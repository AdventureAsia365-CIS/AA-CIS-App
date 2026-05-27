-- 046_fix_duplicate_active_brands.sql
-- Deactivate all but the highest version for each brand that has multiple active rows.
-- Root cause: before migration 044/045, multiple is_active=true rows could coexist.

UPDATE shared.tenant_brand_rules t
SET is_active = false
WHERE is_active = true
  AND version < (
      SELECT MAX(version)
      FROM shared.tenant_brand_rules
      WHERE tenant_id = t.tenant_id
        AND COALESCE(brand_name, 'default') = COALESCE(t.brand_name, 'default')
  )
  AND (
      SELECT COUNT(*)
      FROM shared.tenant_brand_rules
      WHERE tenant_id = t.tenant_id
        AND COALESCE(brand_name, 'default') = COALESCE(t.brand_name, 'default')
        AND is_active = true
  ) > 1;
