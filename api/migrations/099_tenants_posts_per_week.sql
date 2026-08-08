-- Migration 099: shared.tenants.posts_per_week (AA-384)
--
-- Context: AA-309/AA-330 Phần B shipped with posts_per_week FIXED per plan_tier (starter=1/
-- growth=3/business=5/enterprise=7/internal=7, services/acp_shared/marketplace_estimates.py's
-- POSTS_PER_WEEK_BY_PLAN_TIER). AA-384 (Nghiep, product-direction change, 08/08/2026): in this
-- pre-paying-customer stage with a >700-tour catalog, that tier-based ceiling models a commercial
-- concern (upsell) that doesn't reflect reality yet — tenants now choose their own posting cadence
-- freely at onboarding, not implied by which plan they're on. This column is that free value.
--
-- NOT a plan_tier replacement: plan_tier still exists and still drives PLAN_LIMITS (rpm/quota,
-- api/routers/admin.py) — a real billing concern, untouched by this migration.
--
-- Backfill: every EXISTING tenant gets the value it was already implicitly using (Mirror derived
-- it live from POSTS_PER_WEEK_BY_PLAN_TIER, never stored) — so this migration changes nothing
-- about any existing tenant's Mirror output, only makes the value an explicit, editable column
-- going forward. New tenants (api/routers/admin.py create_tenant(), same PR) must supply a value
-- explicitly — no column default — enforced at the Pydantic layer (1-14, matches AA-384's own
-- caller-facing validation range).

BEGIN;

ALTER TABLE shared.tenants ADD COLUMN IF NOT EXISTS posts_per_week INTEGER;

UPDATE shared.tenants
SET posts_per_week = CASE plan_tier::text
    WHEN 'starter'    THEN 1
    WHEN 'growth'      THEN 3
    WHEN 'business'    THEN 5
    WHEN 'enterprise'  THEN 7
    WHEN 'internal'    THEN 7
    ELSE 1  -- no plan_tier value outside the enum's known set exists live (schema CHECK), this
            -- branch only guards a future enum addition landing before this migration is re-read
END
WHERE posts_per_week IS NULL;

ALTER TABLE shared.tenants ALTER COLUMN posts_per_week SET NOT NULL;

ALTER TABLE shared.tenants
    ADD CONSTRAINT tenants_posts_per_week_range CHECK (posts_per_week BETWEEN 1 AND 14);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('099', now(), 'AA-384: shared.tenants.posts_per_week — free tenant-chosen cadence, replaces plan_tier-fixed map')
ON CONFLICT (version) DO NOTHING;

COMMIT;
