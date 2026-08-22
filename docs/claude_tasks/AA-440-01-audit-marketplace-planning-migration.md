## Task cho Claude Code: AA-440 — Chuẩn bị migrate Quarter Plan/Marketplace/Produce&Deliver sang tenant self-service (T7/Marketplace/T8-T10)

Mục tiêu: ADR-2026-038 mục 0.2 (Notion, cập nhật 22/08) vừa ĐẢO NGƯỢC quyết định cũ — Quarter Plan (Gate B) và Marketplace KHÔNG còn giữ nguyên ở admin nữa, mà chuyển thành tenant self-service, cùng nguyên lý với T1/T2/T6 đã có. Task này KHÔNG phải "xác nhận giữ nguyên đúng thiết kế" — mà là audit business logic hiện có để biết cái gì tái dùng được khi xây UI tenant, cái gì phải viết lại.

Repo: AA-CIS-App
Branch mới: feature/aa-440-marketplace-planning-migration (tạo từ main). Chỉ commit local, KHÔNG push, KHÔNG PR (chờ lệnh tổng hợp sau).

## Trích ADR-2026-038 mục 0.2 (Notion, nguồn gốc — QUYẾT ĐỊNH MỚI NHẤT, ghi đè mọi thứ liên quan Gate B ở mục 10.3/4/11 cũ)

**Nguyên lý:** "AA KHÔNG gác cổng (gate/approve) nội dung của tenant ở bất kỳ bước nào trong chuỗi T0-T11. AA chỉ kiểm soát ở 2 lớp: (1) rate limit/quota đặt lúc tạo tenant (giới hạn số lượng chạy, không phải duyệt nội dung), và (2) A4 Cross-Tenant Oversight — giám sát hậu-kiểm, có khả năng can thiệp nếu vi phạm, KHÔNG phải gate chặn trước khi publish."

**Quyết định cụ thể:**
1. Gate B (Quarter Plan, T7) → chuyển thành 1 phần của T7 tenant self-service. Tenant tự lên kế hoạch nội dung (runway/quarter/allocator) từ atom đã curate của chính họ (T6), không cần AA duyệt kế hoạch.
2. Marketplace → chuyển thành nơi tenant tự xem/chọn, tương tự T1. KHÔNG còn là nơi staff AA quản lý/curate portfolio thay tenant.
3. Kiểm soát rate limit/quota: AA đặt giới hạn (số run/tháng, số content/quý) tại thời điểm SETUP tenant (gắn với plan tier), không phải duyệt tay từng kế hoạch. Cơ chế cụ thể CHƯA có trong ADR — cần điều tra xem code đã có gì chưa.

**Produce & Deliver (N7/N8) — KHÔNG đổi hướng, vẫn theo nhận định cũ**: tiền thân T8+T9+T10 (ADR mục 6: "N7 → T8+T9+T10, tách 3 vì thêm angle-gate T8"), "rework lớn nhất còn lại" (ADR mục 11.2).

## Files cần đọc

- `api/routers/admin.py` — handler Quarter Plan/Gate B (grep `quarter`, `slot`, `allocator`, `runway`).
- `api/routers/admin_produce.py` — Produce & Deliver N7/N8, toàn bộ.
- `api/routers/admin_marketplace.py` — toàn bộ.
- `frontend/app/admin/quarter-plan/page.tsx`, `frontend/app/admin/produce/page.tsx`, `frontend/app/admin/marketplace/page.tsx`.
- Grep toàn repo: `plan_tier`, `quota`, `rate_limit` liên quan đến bảng `shared.tenants` — xác nhận cơ chế giới hạn theo tenant hiện có gì.

## Steps

1. Đọc `admin.py` (Quarter Plan) — TÁCH RÕ 2 phần: (a) thuật toán/business logic thuần (runway calculation, slot allocator) — có input/output độc lập với "ai gọi", có thể tái dùng khi tenant tự gọi; (b) phần gắn chặt với "admin xử lý TẤT CẢ tenant cùng lúc" (vòng lặp qua nhiều tenant, không filter theo 1 tenant_id cụ thể, hoặc UI hiển thị nhiều tenant trên 1 màn hình) — phần này phải viết lại thành tenant-scoped khi xây T7 UI.
2. Đọc `admin_produce.py` — như task gốc: tách phần ứng T8 (angle generation)/T9 (final write)/T10 (QA pass F1-F9), CÙNG với việc áp dụng phân tích (a)/(b) như bước 1 — phần nào tái dùng, phần nào viết lại.
3. Đọc `admin_marketplace.py` — áp dụng cùng phân tích (a)/(b). Xác nhận rõ input hiện tại (đọc atom nào — platform-scope từ Atomize N2, hay đã có khái niệm tenant?) và output (nơi admin thấy — cần đổi thành nơi TENANT thấy của chính họ).
4. Grep `plan_tier`/`quota`/`rate_limit` — liệt kê TOÀN BỘ nơi đã có cơ chế giới hạn theo tenant (nếu có), và nơi CHƯA có (nếu Quarter Plan/Produce/Marketplace hiện không có bất kỳ giới hạn nào theo tenant, ghi rõ đây là gap cần thiết kế mới, không phải bug).
5. Query dev DB: bảng Quarter Plan/Marketplace/Produce&Deliver ghi vào có cột `tenant_id` không. Nếu không có — đây là thay đổi schema cần khi tenant-scope hóa (ghi rõ, không tự thêm migration trong task này).

Verify: Không sửa code. Mọi kết luận có bằng chứng path:line hoặc query thật.

Sau khi done:
- Viết báo cáo vào `docs/claude_audit/AA-440-marketplace-planning-produce-migration-audit.md` — có bảng tổng hợp: Mục | Business logic tái dùng (path:line) | Phần phải viết lại (lý do) | Trạng thái rate-limit/quota | Có tenant_id column chưa.
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-440-01-audit-marketplace-planning-migration.md`.
- git commit trên branch `feature/aa-440-marketplace-planning-migration` — KHÔNG push, KHÔNG PR.
- Comment tóm tắt lên Linear AA-440.
- Paste nội dung báo cáo về Claude Chat.
