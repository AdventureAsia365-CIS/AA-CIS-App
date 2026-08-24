## Task cho Claude Code: AA-454 — 4 việc nhỏ gộp 1 PR (dead code, Settings chip, retry_count dead field, nav T4↔T6)

Mục tiêu: sửa 4 việc nhỏ, rủi ro thấp, đã điều tra kỹ ở AA-446-02-followup-investigation-s158.md — gộp 1 PR vì không file nào overlap, tổng effort <1.5h. Verify từng việc riêng, thật (không chỉ đọc code) trước khi coi Done.

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: yes — pqnghiep1354/aa-454-4-small-fixes
Merge vào: main (trunk-based)

Files cần đọc trước:
- `docs/claude_audit/AA-446-02-followup-investigation-s158.md` phần "Việc 2 — Đề xuất việc nhỏ" — chi tiết code path từng mục.
- Linear issue AA-454 — mô tả đầy đủ, có link ngược AA-438/AA-439/AA-446.

4 việc cần làm:

**1. AA-438 #9 — Xoá dead code `ExportService.publish_tour()`**
File: `shared/services/export_service.py`. Grep `import shared.services.export_service`/`from shared.services.export_service`/`ExportService` toàn repo trước khi xoá, xác nhận 0 caller thật (production code). Nếu cả file chỉ tồn tại để phục vụ 1 test file riêng testing chính module chết đó, xoá luôn test file đó (không để lại test import module không tồn tại) — kiểm tra test file có patch schema riêng trong conftest.py hay không, và chỉ xoá phần conftest.py patch KHÔNG dùng chung với test khác.

**2. AA-438 #16 — Sửa Settings "Pipeline Flow" chip thiếu node**
File: `api/routers/admin_settings.py` (constant `PIPELINE_GATES["pipeline_flow"]`). Đọc `services/content_generation/graph.py::build_graph()` để xác nhận đúng thứ tự edge thật (generate→validate→llm_judge→brand_audit→flag_fix→revalidate), sửa list cho khớp.

**3. AA-438 #17 — Xoá `retry_count: 0` hardcode dead**
File: `api/routers/acp_health.py` (response dict) + `frontend/app/admin/run-health/page.tsx` (TS interface). Xác nhận field không render ở JSX cùng file trước khi xoá cả 2 phía.

**4. AA-439 #3 — Thêm nav 2 chiều T4 (CatalogTab) ↔ T6 (AtomsTab)**
File: `frontend/app/(tenant)/portal/_components/{CatalogTab,AtomsTab}.tsx`. Đọc `portal/page.tsx`/route structure trước — portal đã đổi từ tab-switch nội bộ sang route riêng cho mỗi T-stage (AA-430), không còn setActiveTab. Kiểm tra backend `GET /admin/atoms` đã hỗ trợ filter `tour_id` chưa trước khi quyết định cần sửa backend hay không.

Verify trước khi coi Done (không chỉ đọc code, verify thật):
- #9: chạy full unit test suite (`pytest tests/unit/`, đúng scope CI dùng), không lỗi import, không fail mới.
- #16: gọi thật hàm `get_settings()` (hoặc API thật nếu deploy được), xác nhận `pipeline_flow` trả về đúng thứ tự graph thật.
- #17: response BE không còn field `retry_count`; `next build` (frontend) chạy sạch, không lỗi TS.
- #3: verify live 2 chiều — vào CatalogTab bấm nav sang AtomsTab thấy đúng atom của rewrite đó, và ngược lại. Nếu backend đổi cần deploy mới verify HTTP thật được, verify bằng cách chạy đúng SQL/data path thật trên RDS thật (S3-mediated ECS exec pattern) thay thế, ghi rõ giới hạn (chưa click-through browser thật) trong implementation notes.

Theo quy trình mới (từ S157): 1 branch, gộp toàn bộ 4 việc, không tạo PR riêng cho docs STEP0/investigate — gộp vào PR build luôn. `gh pr create` ngay sau khi push, không hỏi lại Nghiệp có muốn PR không. CI green là đủ để merge (không có migration trong task này).

Không thuộc scope:
- KHÔNG xoá `services/acp_s4_social/` (việc bonus riêng, effort lớn hơn).
- KHÔNG đụng AA-438 #1/#2 (state machine `pipeline_runs.status`) — cần thiết kế riêng.

Lưu implementation notes vào `docs/claude_audit/` theo convention hiện có, lưu task prompt này vào `docs/claude_tasks/`.
