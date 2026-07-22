-- Migration 086: silver_aa_internal.raw_tours — lifecycle_stage (AA-301 N4 phasing_out)
--
-- Context: AA-301 (N4 Runway Map recompute trigger). N4 needs to distinguish
-- a tour that is still fully bookable ('active') from one winding down
-- ('phasing_out' — sell through the current season, no new content) from one
-- fully stopped ('retired' — excluded from runway entirely).
--
-- Placement decision (STEP 0 recon, prior session): silver_aa_internal.raw_tours,
-- NOT a new table — no precedent in this repo for a separate tour-lifecycle
-- table (migration 057's "lifecycle" name is stage_runs, unrelated), and
-- v_trip_registry SELECTs directly off rt.* with no extra JOIN needed for an
-- additive column (same pattern as migration 080's inclusions/exclusions).
--
-- Type decision: a NEW dedicated ENUM type, not reuse of source_status_enum
-- (migration 052) and not VARCHAR+CHECK (migration 024's review_status
-- pattern — confirmed dead per AA-316, dropped from v_trip_registry's WHERE
-- in migration 083). source_status is a data-versioning axis (active=latest
-- row/superseded=older duplicate/trashed=deleted); lifecycle_stage is a
-- separate, orthogonal "is this tour still sold" axis — a tour can be
-- source_status='active' (current data row) while lifecycle_stage=
-- 'phasing_out' (still current, but sales winding down) at the same time.
--
-- NOTE: this migration was already applied live to the dev DB in a prior
-- session via a one-off script (S3-mediated ECS exec), BEFORE this .sql
-- file was committed to the repo. Written here now for migration-history
-- completeness. Guarded with IF NOT EXISTS / exception-safe DO blocks so
-- re-running it (locally, in a fresh env, or in CI) is a no-op against a DB
-- that already has it, and a real apply against one that doesn't.

BEGIN;

DO $$
BEGIN
    CREATE TYPE silver_aa_internal.tour_lifecycle_stage_enum
        AS ENUM ('active', 'phasing_out', 'retired');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE silver_aa_internal.raw_tours
    ADD COLUMN IF NOT EXISTS lifecycle_stage silver_aa_internal.tour_lifecycle_stage_enum
        NOT NULL DEFAULT 'active';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('086', now(), 'AA-301: raw_tours.lifecycle_stage (active|phasing_out|retired) for N4 recompute trigger')
ON CONFLICT (version) DO NOTHING;

COMMIT;
