# AA-457 (T11 PR1) — BUILD THẬT: tenant_integrations + save/test-connection WordPress + UI inline 3+2

(Task prompt as given, saved verbatim per repo convention.)

Đã qua đủ 2 vòng STEP0 (AA-455-00, AA-456 STEP0 report). Đọc Linear issue AA-457 đầy đủ trước khi
bắt đầu — mô tả đã có sẵn schema sketch, endpoint shape, quyết định UI Option 3+2.

## Việc cần build

1. Migration: `shared.tenant_integrations` — `id`, `tenant_id` FK, `integration_type`, `config`
   JSONB, `secret_key`, `connected_at`, `last_verified_at`, `last_verify_error`, `created_at`,
   `updated_at`, `UNIQUE(tenant_id, integration_type)`. Verify migration chạy sạch trên DB dev
   thật.
2. `POST /v1/integrations/wordpress` (tenant-JWT-gated, `get_tenant()`) — body
   `{wp_url, username, app_password}`. Validate `wp_url` (https, không localhost/private IP —
   SSRF cơ bản). Ghi credential vào Secrets Manager tại `acp/cms/{tenant_id}` (create-or-update).
   Upsert `tenant_integrations` row.
3. `POST /v1/integrations/wordpress/test` (tenant-JWT-gated) — gọi thật
   `GET {wp_url}/wp-json/wp/v2/users/me` với Basic Auth, timeout 5-10s. 200 → `last_verified_at`
   cập nhật. Lỗi → phân loại rõ (401/timeout-DNS/404), ghi `last_verify_error`, GIỮ NGUYÊN
   `last_verified_at` cũ.
4. Frontend — route `/portal/t11-publish` (form kết nối, khung cho AA-458), trang "Manage
   connection" riêng, KHÔNG thêm Sidebar entry trong task này.

Bảo mật bắt buộc: KHÔNG lưu application password plaintext trong Postgres — chỉ Secrets Manager.

## Verify — chia 2 nhóm rõ ràng (Nghiệp chưa có WordPress site thật phiên này)

**Nhóm 1 (verify được NGAY, bắt buộc trước khi coi PR sẵn sàng merge):** migration sạch, save với
URL giả hợp lệ → Secrets Manager có secret đúng key, DB không plaintext; test-connection với URL
không tồn tại thật → DNS/timeout fail thật, message đúng; validate chặn localhost/private IP;
cross-tenant 404/403; FE hoạt động qua UI thật với URL giả.

**Nhóm 2 (CHƯA verify được, cần Nghiệp cung cấp WordPress site thật sau khi PR merge, PHẢI verify
trước khi bắt đầu AA-458):** test-connection với site thật + creds đúng → 200 thật; site thật +
sai password → verify message 401 case; site thật + REST API tắt → verify message 404 case.

Theo đúng quy trình mới: 1 branch, 1 PR gộp toàn bộ, `gh pr create` ngay sau push, CI green đủ để
merge. Lưu implementation notes vào `docs/claude_audit/AA-457-implementation-notes.md`, task
prompt vào `docs/claude_tasks/`.

KHÔNG build AA-458 (list endpoint, publish thật, adapter draft→publish, sidebar entry hoàn chỉnh)
trong task này.
