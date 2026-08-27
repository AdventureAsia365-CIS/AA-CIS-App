-- Migration 120: AA-473 — xoá Gate A hoàn toàn (tương tự Gate B ở AA-472/migration 119).
-- Tenant giờ is_active=true ngay khi tạo (create_tenant() INSERT trực tiếp true) — không còn
-- bước duyệt riêng, theo ADR-2026-038 §0.2 (AA không gate hoạt động tenant, chỉ hậu-kiểm A4).
-- Xác nhận an toàn: grep production code (api/, services/) chỉ có api/routers/admin.py đọc/ghi
-- bảng này (STEP0 AA-473, 2026-08-27) — không còn caller nào sau khi code Gate A bị xoá.

BEGIN;

DROP TABLE IF EXISTS acp_shared.tenant_onboarding;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('120', now(),
    'AA-473: DROP acp_shared.tenant_onboarding — Gate A removed, tenant is_active=true at creation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
