## Task cho Claude Code: Build A4 Cross-Tenant Oversight v1

Mục tiêu: build A4 v1 — 2 use case đã xác nhận (review_queue T3 log + Trust Ramp state), CHỈ ĐỌC, không action (flag/suspend/force-unpublish để dành sau). Nối tiếp STEP0 (`docs/claude_audit/AA-437-01-a4-step0-audit.md`) — đọc lại report đó trước khi bắt tay, đừng điều tra lại từ đầu.

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: yes: feature/aa-437-02-a4-oversight-build
Merge vào: main (trunk-based)

Files cần đọc trước:
- `docs/claude_audit/AA-437-01-a4-step0-audit.md` — toàn bộ findings STEP0, không lặp lại investigate
- `docs/claude_audit/AA-436-t3-ui-step0-audit.md` — schema `review_queue`/`escalate_detail` thật
- Trust Ramp module đã đọc ở AA-439-06/07 — cấu trúc `packets`, ramp state field thật
- 1 route `/admin/*` hiện có làm mẫu style/pattern (VD `/admin/run-health` — AA-259 đã chỉ ra đây là template UI phù hợp nhất để tham khảo)

Context — 5 quyết định đã chốt (23/08/2026, xem đầy đủ lý do ở comment Linear AA-437):
1. Build CẢ 2 use case cùng lúc. Trust Ramp v1 CHỈ hiển thị state hiện có — KHÔNG tự động hóa `suggest_ramp_transition()` (không thiết kế công thức `engagement_ok`/`weeks_active` trong task này).
2. Cần seed 1 row T3 test mới (qua QA fail 2 vòng thật) trước khi build, để có ví dụ sống `qa_auto_passed=true`.
3. "Tenant ở mức nào" (Trust Ramp) — KHÔNG gom 1 con số/tenant. Hiển thị TẤT CẢ packet + level riêng từng packet.
4. Route: `/admin/a4-oversight`.
5. Endpoint: 2 endpoint riêng — `/admin/a4/review-log` và `/admin/a4/trust-ramp`.

Steps:

**0. Seed data (làm trước, quyết định #2)**
- Tạo 1 tour test mới, đẩy qua T2→T3 thật, cố tình khiến QA fail 2 vòng liên tiếp (VD dùng forbidden word cố ý) để trigger `qa_auto_passed=true` qua đúng code path AA-436 đã build.
- Verify: row mới trong `tenant_tour_versions` có `qa_auto_passed=true`, `review_queue` có row tương ứng với `tenant_tour_version_id` đúng.
- Dùng tenant test riêng (không đụng data thật của tenant khác), xóa sau khi verify xong nếu không cần giữ lại làm fixture lâu dài (tùy bạn quyết, không quan trọng).

**1. Endpoint `/admin/a4/review-log`**
- Query `silver_aa_internal.review_queue WHERE tenant_tour_version_id IS NOT NULL` (T3-style rows, phân biệt N0-N6 admin HITL dùng `generated_content_id`).
- Trả về: list rows kèm `tenant_id`, `check_id` (hoặc field tương đương trong `escalate_detail`), `escalate_detail` đầy đủ, timestamp.
- Thêm 1 param filter `tenant_id` (optional) và endpoint/query hỗ trợ group-by `check_id` để lộ pattern lặp lại (có thể trả raw rows + để FE tự group, hoặc trả đã group sẵn — chọn cách đơn giản hơn, ít logic hơn ở BE).
- KHÔNG dùng chung endpoint `/admin/review-queue` cũ (đang phục vụ flow khác với action approve/reject không áp dụng ở đây).

**2. Endpoint `/admin/a4/trust-ramp`**
- Query toàn bộ packet + ramp state hiện tại (bảng đã xác nhận ở STEP0), trả về theo tenant, mỗi packet với level riêng (không gộp).
- Không cần logic tính toán gì thêm — thuần đọc + trả state hiện có.

**3. FE `/admin/a4-oversight`**
- 1 trang admin đơn giản, 2 section: Review Log (bảng review_queue T3, filter theo tenant) + Trust Ramp (bảng packet + level, group theo tenant để dễ đọc).
- Tham khảo style/pattern trang `/admin/run-health` hiện có.
- Không cần action button nào (chỉ đọc).

Verify tổng:
- Gọi cả 2 endpoint thật qua admin JWT, xác nhận trả đúng data (bao gồm row seed mới ở bước 0).
- Confirm route `/admin/a4-oversight` render đúng, không lỗi console.
- pytest suite hiện có: không regression.

Sau khi done:
- Lưu CHÍNH file task prompt này vào `docs/claude_tasks/AA-437-02-build-a4-oversight.md` trước khi bắt tay code.
- Lưu báo cáo thực thi vào `docs/implementation-notes/AA-437-02-a4-oversight-build.md`.
- git commit + push, tạo PR, KHÔNG tự merge.
- Paste kết quả verify về Claude Chat.
- Linear AA-437: giữ nguyên status, Claude Chat verify qua comment trước khi đổi Done (ADR-2026-037).
