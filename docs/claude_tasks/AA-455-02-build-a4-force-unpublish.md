# AA-455 bước 1 — BUILD THẬT: publish_log migration + A4 force-unpublish + tenant self-unpublish

(Task prompt as given, saved verbatim per repo convention — docs/claude_tasks/ records the prompt,
docs/implementation-notes/ records the decisions made while executing it.)

Đã qua đủ 2 vòng STEP0 (AA-455-00 T11 investigate, AA-455-01 A4 force-unpublish investigate),
quyết định kiến trúc đã chốt trong Linear issue AA-455 — đọc mô tả đầy đủ trước khi bắt đầu.

Kiểm tra trước khi bắt đầu: xác nhận không có session Claude Code khác đang chạy trên cùng working
tree chính. Nếu có, tạo worktree riêng theo bài học AA-444.

## STEP 0 — Đọc trước khi code

1. Linear issue AA-455 — toàn bộ mô tả + 2 lần update, đặc biệt phần "STEP0 bước 1 hoàn tất" (4
   phát hiện đổi kế hoạch build).
2. docs/claude_audit/AA-455-01-step0-a4-force-unpublish.md — đọc kỹ §4 (middleware), §7 (UI), §8
   (sequencing), §9 (schema hedge).
3. api/routers/admin_a4.py — pattern 2 endpoint hiện có, để giữ nhất quán khi thêm endpoint mới.
4. frontend/app/admin/a4-oversight/page.tsx — pattern 2 section hiện có.
5. api/routers/v1_competitors.py dòng ~187 — tiền lệ DELETE tenant-JWT-gated, dùng làm mẫu cho
   endpoint tenant self-unpublish.

## Việc cần build — 1 PR duy nhất (theo đúng kết luận sequencing §8)

1. Migration mới: tạo bảng `acp_shared.publish_log` (các cột như đã chốt — `publish_id`,
   `piece_id` FK `content_piece`, `tenant_id` FK `shared.tenants`, `channel`, `status CHECK IN
   ('published','unpublished','failed')`, `external_id`, `external_url`, `published_at`,
   `unpublished_at`, `unpublished_by`, `last_error`, `created_at`). Additive thuần. Verify migration
   chạy sạch trên DB dev thật.
2. Backend — AA force-unpublish (`admin_a4.py`): `POST
   /admin/a4/publish-log/{publish_id}/unpublish` (admin-secret-gated), `GET
   /admin/a4/publish-log` (list).
3. Backend — tenant self-unpublish: `DELETE /v1/publish-log/{publish_id}` (tenant-JWT-gated,
   ownership check học bài học AA-445-02/AA-431 IDOR).
4. Frontend — section thứ 3 trên `/admin/a4-oversight` (KHÔNG route mới).

## Verify trước khi coi Done (live, không chỉ đọc code)

Migration áp dụng sạch trên DB dev; insert 1 row test thủ công; AA force-unpublish qua HTTP thật
(200 → 404 double-action); tenant self-unpublish qua HTTP thật, cross-tenant isolation (404, không
rò rỉ); FE hoạt động qua UI thật; middleware xác nhận không cần sửa.

Theo đúng quy trình mới (từ S157): gộp PR, `gh pr create` ngay sau push không hỏi lại, CI green đủ
để merge kể cả có migration. Lưu implementation notes vào docs/claude_audit/, lưu task prompt vào
docs/claude_tasks/.

KHÔNG build T11 bước 2 (blog-only publish) trong task này.
