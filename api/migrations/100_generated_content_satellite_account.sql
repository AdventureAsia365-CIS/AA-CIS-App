-- Migration 100: silver_aa_internal.generated_content.satellite_account (AA-397/AA-398)
--
-- Context: AA-296 added satellite_used BOOLEAN (True when a response came from the acc1 Bedrock
-- satellite instead of acc2 native). AA-397 adds a second satellite account (acc3, made primary —
-- acc1 becomes the fallback under it) to the fallback chain (shared/llm_client/client.py,
-- T1.5a/T1.5b/T2.5a/T2.5b tiers). A single boolean can no longer say WHICH satellite account
-- actually served the response, so this migration adds satellite_account TEXT ('acc1'/'acc3'/NULL).
--
-- satellite_used is NOT dropped — kept in parallel for backward-compat with any existing
-- query/dashboard that reads it. api/routers/admin_pipeline.py's insert now writes both columns:
-- satellite_used = (satellite_account IS NOT NULL), satellite_account = the real value.
--
-- Backfill: existing rows only ever had a bool (True meant acc1 — acc3 didn't exist yet when they
-- were written), so backfill satellite_account = 'acc1' WHERE satellite_used = true, NULL otherwise.
-- This is the only historically-accurate mapping — every pre-AA-397 satellite_used=true row went
-- through acc1 (the only satellite account that existed at the time).

BEGIN;

ALTER TABLE silver_aa_internal.generated_content ADD COLUMN IF NOT EXISTS satellite_account TEXT NULL;

ALTER TABLE silver_aa_internal.generated_content
    ADD CONSTRAINT generated_content_satellite_account_valid
    CHECK (satellite_account IS NULL OR satellite_account IN ('acc1', 'acc3'));

UPDATE silver_aa_internal.generated_content
SET satellite_account = 'acc1'
WHERE satellite_used = true AND satellite_account IS NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('100', now(), 'AA-397/AA-398: silver_aa_internal.generated_content.satellite_account — acc1/acc3, satellite_used kept in parallel')
ON CONFLICT (version) DO NOTHING;

COMMIT;
