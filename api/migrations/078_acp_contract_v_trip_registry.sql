-- Migration 078: AA-302 — acp_contract.v_trip_registry
--
-- Context: AA-302 (EPIC AA-297, ACP v2, milestone "Contract + Atom (N0-N2)").
-- v_trip_registry is the input contract for ACP v2 — a read-only VIEW joining
-- silver_aa_internal.raw_tours (source/editorial fields) with
-- gold_aa_internal.published_tours (brand-approved output fields).
--
-- id column: rt.tour_id (UUID PK), NOT rt.sku — STEP 0 verification found
-- sku is not reliably unique/non-null (2 approved rows in dev, 1 with sku
-- NULL). sku is kept as a separate column so business-code info isn't lost.
--
-- acp_deliver.tenant_tour_pages is a new empty table (per-tenant published
-- URL tracking) LEFT JOINed so trip_url/url_alive are NULL until populated
-- by a later ACP v2 step — not in scope for this migration.

BEGIN;

CREATE SCHEMA IF NOT EXISTS acp_contract;
CREATE SCHEMA IF NOT EXISTS acp_deliver;

CREATE TABLE IF NOT EXISTS acp_deliver.tenant_tour_pages (
    tenant_id        TEXT,
    tour_id          UUID,
    url              TEXT NOT NULL,
    published_at     TIMESTAMPTZ,
    url_alive        BOOLEAN DEFAULT true,
    last_checked_at  TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, tour_id)
);

CREATE VIEW acp_contract.v_trip_registry AS
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
    ttp.url_alive
FROM silver_aa_internal.raw_tours rt
JOIN gold_aa_internal.published_tours pt ON pt.tour_id = rt.tour_id
LEFT JOIN acp_deliver.tenant_tour_pages ttp ON ttp.tour_id = rt.tour_id
WHERE rt.review_status = 'approved'
  AND pt.master_status = 'active'
  AND pt.deleted_at IS NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('078', now(), 'AA-302: acp_contract.v_trip_registry (silver+gold JOIN) + acp_deliver.tenant_tour_pages')
ON CONFLICT (version) DO NOTHING;

COMMIT;
