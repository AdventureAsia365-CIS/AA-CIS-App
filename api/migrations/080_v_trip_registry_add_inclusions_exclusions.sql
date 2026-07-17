-- Migration 080: AA-302 — v_trip_registry thêm inclusions/exclusions
--
-- Context: v_trip_registry (migration 078) thiếu rt.inclusions/rt.exclusions
-- — gap phát hiện khi build endpoint POST /v1/atoms/decompose (AA-302 Phần A
-- Bước 10/11a). Đây là input contract cho toàn bộ ACP v2 nên sửa VIEW trực
-- tiếp, không để caller tự JOIN vá riêng lẻ.
--
-- CREATE OR REPLACE VIEW: 19 cột cũ giữ nguyên tên + thứ tự (đối chiếu
-- nguyên văn với 078_acp_contract_v_trip_registry.sql trước khi viết file
-- này), chỉ thêm 2 cột mới ở cuối danh sách SELECT.

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
    rt.exclusions               AS exclusions
FROM silver_aa_internal.raw_tours rt
JOIN gold_aa_internal.published_tours pt ON pt.tour_id = rt.tour_id
LEFT JOIN acp_deliver.tenant_tour_pages ttp ON ttp.tour_id = rt.tour_id
WHERE rt.review_status = 'approved'
  AND pt.master_status = 'active'
  AND pt.deleted_at IS NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('080', now(), 'AA-302: v_trip_registry thêm inclusions/exclusions (gap phát hiện khi build decompose_atoms endpoint)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
