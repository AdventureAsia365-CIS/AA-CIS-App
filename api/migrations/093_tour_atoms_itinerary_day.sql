-- Migration 093: acp_contract.tour_atoms.itinerary_day (AA-352)
--
-- Context: AA-350 chốt thêm trường ngày/thứ tự vào tour_atoms, OPTIONAL ở tầng schema. AA-352
-- STEP 0 (read-only) xác nhận: itinerary_source (silver_aa_internal.raw_tours.src_itineraries,
-- qua acp_contract.v_trip_registry) là TEXT tự do, nhãn ngày không nhất quán ("DAY 01" / "Day 2:" /
-- "Day 12") -- không có structure đáng tin cậy để regex parse chắc chắn. Quyết định (Nghiep, cùng
-- phiên): LLM tự trích ngày trong cùng 1 lần invoke_claude() decompose đã có sẵn (api/routers/
-- v1_atoms.py _decompose_inline), KHÔNG thêm call riêng.
--
-- Nullable, no backfill: 300 atom / 30 tour hiện có (xác nhận live query, AA-352 STEP 0) giữ
-- itinerary_day = NULL vĩnh viễn -- chỉ atom decompose từ migration này trở đi có giá trị, và
-- ngay cả atom mới cũng có thể NULL nếu model không xác định được ngày từ itinerary_source.
--
-- SMALLINT theo cùng convention với visual_potential (migration 079) -- cột số nhỏ cùng bảng.
--
-- shared.schema_versions: xác nhận là bảng version-tracking DUY NHẤT, dùng chung cho mọi schema
-- (acp_contract via migration 090, acp_shared via migration 092) -- không có convention riêng theo
-- từng schema để lệch khỏi, nên 093 dùng đúng INSERT như các migration liền trước.

BEGIN;

ALTER TABLE acp_contract.tour_atoms
    ADD COLUMN itinerary_day SMALLINT NULL;

COMMENT ON COLUMN acp_contract.tour_atoms.itinerary_day IS
    'Ngày/thứ tự trong itinerary nguồn (AA-352, AA-350 câu 1). NULL cho atom decompose trước '
    'ngày thêm field này (300 atom / 30 tour, không backfill -- xem AA-352). LLM tự trích lúc N2 '
    'decompose, có thể NULL nếu model không xác định được từ itinerary_source (text tự do, nhãn '
    'ngày không chuẩn hoá).';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('093', now(), 'AA-352: acp_contract.tour_atoms.itinerary_day -- LLM self-extracted day/order, optional, no backfill')
ON CONFLICT (version) DO NOTHING;

COMMIT;
