-- Migration 087: acp_contract.v_trip_registry — expose rt.tenant_id
--
-- Context: AA-301 (N4/N5/N6). Multi-tenant is required for the planning
-- cascade (Nghiep decision — runway/quarter/allocator run per-tenant, atoms
-- stay platform-scoped per D3). raw_tours.tenant_id already exists live
-- (UUID, FK -> shared.tenants, verified: 793/793 current rows = aa_internal
-- 00000000-0000-0000-0000-000000000001; 7 other active tenants registered
-- in shared.tenants but own zero raw_tours rows today). v_trip_registry —
-- the only data source N4/N5/N6 read from — does not currently surface this
-- column at all (confirmed by grep across migrations 078/080/083: the only
-- "tenant_id" hits are on the unrelated acp_deliver.tenant_tour_pages
-- table). Without this, tenant-scoped filtering through the view is not
-- possible.
--
-- Safety: purely additive column appended to the end of the SELECT list.
-- Sole consumer of this view (grep-confirmed, api/routers/v1_atoms.py) uses
-- named-column SELECTs (`vtr.id, vtr.name, vtr.aa_summary, ...`), never
-- `SELECT *` — appending a column cannot break it. All 19 existing columns
-- kept in the same name+order as migration 083.

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
  AND rt.src_itineraries IS NOT NULL AND trim(rt.src_itineraries) != '';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('087', now(), 'AA-301: v_trip_registry exposes rt.tenant_id + rt.lifecycle_stage for N4/N5/N6 tenant scoping')
ON CONFLICT (version) DO NOTHING;

COMMIT;
