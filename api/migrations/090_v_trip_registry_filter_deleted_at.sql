-- Migration 090: acp_contract.v_trip_registry — filter rt.deleted_at IS NULL
--
-- Context: AA-343. v_trip_registry (the input contract for N4/N5/N6 planning) already filters
-- pt.deleted_at (published_tours soft-delete, since migration 083) but never filtered
-- rt.deleted_at (raw_tours soft-delete, added in migration 052/ADR-018) — a raw_tours row that has
-- been soft-deleted still surfaced through the view. Confirmed: 46 rows across 2 corrupted-mapper
-- batches (a0b806f8, 4bdd9b22, see AA-343 mapper fix in the same PR) were soft-deleted but still
-- counted in v_trip_registry's row set.
--
-- Verified via read-only ad-hoc query against the live view SQL (not by running this migration):
-- 809 -> 763 rows, exactly the 46 deleted_at-tagged rows drop out, no collateral (all 46 removed
-- rows have deleted_at NOT NULL; every other currently-visible row is untouched).
--
-- Safety: purely additive WHERE condition, same shape as migration 083's existing
-- `rt.source_status ... != 'trashed'` guard. Sole consumer (api/routers/v1_atoms.py) uses
-- named-column SELECTs, unaffected by row-set narrowing other than intentionally excluding
-- soft-deleted rows. All 20 columns kept in the same name+order as migration 087.

BEGIN;

CREATE OR REPLACE VIEW acp_contract.v_trip_registry AS
SELECT
    rt.tour_id              AS id,
    rt.sku                  AS sku,
    rt.src_name              AS name,
    pt.aa_name               AS aa_name,
    rt.duration               AS duration_raw,
    rt.period                  AS period,
    rt.price_raw               AS price_raw,
    rt.country                 AS destination,
    rt.src_itineraries        AS itinerary_source,
    pt.aa_itineraries         AS itinerary_brand,
    pt.aa_summary, pt.aa_highlights,
    pt.seo_title, pt.seo_meta, pt.seo_keywords_used,
    pt.quality_score,
    pt.content_embedding,
    ttp.url                    AS trip_url,
    ttp.url_alive,
    rt.inclusions               AS inclusions,
    rt.exclusions               AS exclusions,
    rt.tenant_id                AS tenant_id,
    rt.lifecycle_stage          AS lifecycle_stage
FROM silver_aa_internal.raw_tours rt
LEFT JOIN gold_aa_internal.published_tours pt
    ON pt.tour_id = rt.tour_id
   AND pt.master_status = 'active'
   AND pt.deleted_at IS NULL
LEFT JOIN acp_deliver.tenant_tour_pages ttp ON ttp.tour_id = rt.tour_id
WHERE (rt.source_status IS NULL OR rt.source_status::text != 'trashed')
  AND rt.deleted_at IS NULL
  AND rt.src_itineraries IS NOT NULL AND trim(rt.src_itineraries) != '';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('090', now(), 'AA-343: v_trip_registry filters rt.deleted_at IS NULL — excludes soft-deleted raw_tours rows (46-row mapper-collision cleanup)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
