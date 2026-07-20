-- Migration 083: AA-316 — v_trip_registry: bỏ review_status='approved' chết,
-- floor tự động trên raw_tours + LEFT JOIN published_tours
--
-- Context: review_status là cột chết — không UI nào set nó (endpoint
-- POST /v1/s0/approve tồn tại nhưng không được gọi). 791/793 raw_tours ở
-- 'pending_review' mặc định, view cũ chỉ trả về 1 dòng.
--
-- AA-299 atom decompose chạy GIỮA S0 và S1 (D2, PRD ACP v2), trên tour thô
-- (rt.src_itineraries) — KHÔNG chờ tour publish. Vì vậy đổi JOIN
-- published_tours (bắt buộc đã publish) → LEFT JOIN (điều kiện master_status/
-- deleted_at dời vào ON, không phải WHERE) để tour chưa publish vẫn lọt qua,
-- pt.* trả NULL cho các tour đó.
--
-- Consumer duy nhất trong toàn workspace: api/routers/v1_atoms.py (grep xác
-- nhận, không có consumer nào khác ở AA-ACP-App/AA-CIS-Infra/AA-ACP-Core).
-- Query đó SELECT aa_summary/aa_highlights (2 cột pt.* duy nhất được dùng) và
-- đọc bằng row.get(...) — NULL degrade êm, không lỗi.
--
-- Floor tự động: source_status != 'trashed' + src_itineraries non-empty.
-- price_raw CỐ Ý không đưa vào WHERE — 33% raw_tours NULL price_raw trên diện
-- rộng nhiều quốc gia (AA-247), không phải lỗi mà là vấn đề data nguồn.
--
-- Verified live (2026-07-20, Giai đoạn 1c): floor = 763 dòng (793 - 30 rỗng
-- itinerary; trashed=0 hiện tại). 40/763 có published_tours match, 723 raw
-- thuần. published_tours.tour_id có UNIQUE constraint (published_tours_
-- tour_id_key) — fan-out qua LEFT JOIN không thể xảy ra kể cả tương lai.
-- 19 cột giữ nguyên tên + thứ tự so với migration 080 — chỉ đổi FROM/JOIN/WHERE.

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
LEFT JOIN gold_aa_internal.published_tours pt
    ON pt.tour_id = rt.tour_id
   AND pt.master_status = 'active'
   AND pt.deleted_at IS NULL
LEFT JOIN acp_deliver.tenant_tour_pages ttp ON ttp.tour_id = rt.tour_id
WHERE (rt.source_status IS NULL OR rt.source_status::text != 'trashed')
  AND rt.src_itineraries IS NOT NULL AND trim(rt.src_itineraries) != '';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('083', now(), 'AA-316: v_trip_registry raw-tour floor (LEFT JOIN published_tours, drop dead review_status gate)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
