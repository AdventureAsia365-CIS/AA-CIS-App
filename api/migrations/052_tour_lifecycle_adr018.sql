-- =============================================================================
-- Migration 052: CIS tour lifecycle — ADR-018 foundation
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 01/06/2026
-- Ticket: AA-154 — Migration 052 tour lifecycle (ADR-018 foundation)
-- =============================================================================
-- Introduces source versioning on raw_tours (Layer A), soft-delete + status on
-- published_tours (Layer B), and the upload_staging table for upload conflict
-- detection. Backfills existing rows so the schema lands in a consistent state.
-- =============================================================================

BEGIN;

-- 1. Enum types ----------------------------------------------------------------

CREATE TYPE silver_aa_internal.source_status_enum AS ENUM ('active', 'superseded', 'trashed');
CREATE TYPE gold_aa_internal.master_status_enum   AS ENUM ('active', 'inactive', 'trashed');
CREATE TYPE silver_aa_internal.staging_decision_enum AS ENUM ('pending', 'bypass', 'replace', 'update', 'keep_both');

-- 2. raw_tours (Layer A) -------------------------------------------------------

ALTER TABLE silver_aa_internal.raw_tours
    ADD COLUMN source_group_id uuid,
    ADD COLUMN source_version  smallint NOT NULL DEFAULT 1,
    ADD COLUMN source_status   silver_aa_internal.source_status_enum NOT NULL DEFAULT 'active',
    ADD COLUMN deleted_at      timestamptz,
    ADD COLUMN deleted_by      text;

-- 3. published_tours (Layer B) — DEFAULT 'active' covers existing rows ---------

ALTER TABLE gold_aa_internal.published_tours
    ADD COLUMN master_status gold_aa_internal.master_status_enum NOT NULL DEFAULT 'active',
    ADD COLUMN deleted_at    timestamptz,
    ADD COLUMN deleted_by    text;

-- 4. upload_staging -----------------------------------------------------------

CREATE TABLE silver_aa_internal.upload_staging (
    id                      uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id                uuid        NOT NULL,
    tenant_id               uuid        NOT NULL,
    parsed_payload          jsonb       NOT NULL DEFAULT '{}',
    matched_tour_id         uuid        REFERENCES silver_aa_internal.raw_tours(tour_id),
    matched_source_group_id uuid,
    decision                silver_aa_internal.staging_decision_enum NOT NULL DEFAULT 'pending',
    decided_by              text,
    decided_at              timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now()
);

-- 5. Backfill source_group_id — one UUID per (tenant, normalised src_name, provider) --

WITH grp AS (
    SELECT DISTINCT
        tenant_id,
        lower(trim(src_name))                AS nname,
        lower(trim(coalesce(provider, '')))  AS nprov
    FROM silver_aa_internal.raw_tours
),
grp_id AS (
    SELECT tenant_id, nname, nprov, gen_random_uuid() AS gid FROM grp
)
UPDATE silver_aa_internal.raw_tours rt
SET source_group_id = g.gid
FROM grp_id g
WHERE rt.tenant_id = g.tenant_id
  AND lower(trim(rt.src_name))               = g.nname
  AND lower(trim(coalesce(rt.provider, ''))) = g.nprov;

-- 6. Backfill source_version + source_status ----------------------------------
-- Active = row with sku (non-null) DESC, then ingest_at DESC within each group.

WITH ranked AS (
    SELECT
        tour_id,
        row_number() OVER (PARTITION BY source_group_id ORDER BY ingest_at)                                    AS vnum,
        row_number() OVER (PARTITION BY source_group_id ORDER BY (sku IS NOT NULL) DESC, ingest_at DESC)       AS active_rank
    FROM silver_aa_internal.raw_tours
)
UPDATE silver_aa_internal.raw_tours rt
SET source_version = r.vnum,
    source_status  = (CASE WHEN r.active_rank = 1 THEN 'active' ELSE 'superseded' END)::silver_aa_internal.source_status_enum
FROM ranked r
WHERE rt.tour_id = r.tour_id;

-- 7. Partial unique index — enforced AFTER backfill to avoid false conflicts ---

CREATE UNIQUE INDEX uq_raw_tours_active_per_group
    ON silver_aa_internal.raw_tours (source_group_id)
    WHERE source_status = 'active';

-- 8. Schema version -----------------------------------------------------------

INSERT INTO shared.schema_versions (version, description)
VALUES ('052', 'tour lifecycle ADR-018: source versioning, upload_staging, soft-delete [AA-154]')
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- =============================================================================
-- DOWN (run manually to revert — NOT executed automatically)
-- =============================================================================
-- DROP INDEX  IF EXISTS silver_aa_internal.uq_raw_tours_active_per_group;
-- DROP TABLE  IF EXISTS silver_aa_internal.upload_staging;
-- ALTER TABLE gold_aa_internal.published_tours
--     DROP COLUMN IF EXISTS master_status,
--     DROP COLUMN IF EXISTS deleted_at,
--     DROP COLUMN IF EXISTS deleted_by;
-- ALTER TABLE silver_aa_internal.raw_tours
--     DROP COLUMN IF EXISTS source_group_id,
--     DROP COLUMN IF EXISTS source_version,
--     DROP COLUMN IF EXISTS source_status,
--     DROP COLUMN IF EXISTS deleted_at,
--     DROP COLUMN IF EXISTS deleted_by;
-- DROP TYPE IF EXISTS silver_aa_internal.staging_decision_enum;
-- DROP TYPE IF EXISTS gold_aa_internal.master_status_enum;
-- DROP TYPE IF EXISTS silver_aa_internal.source_status_enum;
