-- Migration 123: AA-476 — register the raw_sources.file_hash unique index in git.
--
-- This index has existed on the live DB for a long time (TD-2, process_file()'s dedup check —
-- services/ingestion/handler.py — depends on it) but was applied by hand via ALTER/CREATE INDEX
-- outside of any committed migration file. STEP0 for AA-476 found no migration anywhere in
-- api/migrations/ creating it — confirmed via read-only pg_indexes query against the live DB
-- (aa-cis-dev-db, 28/08/2026):
--
--   CREATE UNIQUE INDEX idx_raw_sources_file_hash ON silver_aa_internal.raw_sources
--       USING btree (file_hash) WHERE (file_hash IS NOT NULL)
--
-- Partial index (WHERE file_hash IS NOT NULL), not a plain UNIQUE constraint — a NULL file_hash
-- row (should not happen in practice, but the column has no NOT NULL) does not collide with
-- another NULL. This migration reproduces that exact definition so a fresh DB (staging, or a
-- disaster-recovery restore) gets the same dedup guarantee. CREATE UNIQUE INDEX IF NOT EXISTS is
-- a safe no-op on the current DB (index already present) and creates the real thing on a DB that
-- doesn't have it yet.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_sources_file_hash
    ON silver_aa_internal.raw_sources USING btree (file_hash)
    WHERE (file_hash IS NOT NULL);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('123', now(),
    'AA-476: register raw_sources.file_hash partial unique index (already live via manual DDL) '
    'in git — no schema change, IF NOT EXISTS no-op on current DB')
ON CONFLICT (version) DO NOTHING;

COMMIT;
