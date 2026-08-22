## Task cho Claude Code: Audit T7→T8 (Content Planning → Angle Gate) — KHÔNG sửa code

Mục tiêu: Task tiếp theo của nhịp Tenant (AA-439), sau khi T0-T6 đã audit xong. T7 (Content Planning/Quarter Plan) vừa được quyết định đổi hướng lớn ở AA-440 (Gate B admin-only → tenant self-service, ADR mục 0.2). T8 (Angle Gate) được ADR xác nhận là "rework lớn nhất còn lại", hiện "admin-only chặt nhất hệ thống". Task này audit handoff T7→T8 với các quyết định MỚI NHẤT đã có, không audit lại từ đầu những gì AA-440 đã làm.

Repo: AA-CIS-App
Branch: feature/aa-439-tenant-tier-audit (đã tồn tại, đã gộp AA-438+AA-440 — checkout, KHÔNG tạo branch mới, KHÔNG push, KHÔNG PR).

Files cần đọc trước:
- `docs/claude_audit/AA-440-marketplace-planning-produce-migration-audit.md` — đã audit business logic Quarter Plan (T7) tái dùng được, Gate B checks cần gỡ (`allocator.py:128-130`, `:279-301`), bug `fetch_atoms_by_trip()` (owner_scope sai). ĐỌC KỸ, KHÔNG audit lại phần này.
- `docs/claude_audit/AA-439-03-t5-t6-dfs-scoring-audit.md` §C7 — xác nhận T6→T7 CHƯA có nút chuyển tiếp (vì T7 chưa self-service).
- `api/routers/admin_produce.py` (Produce & Deliver N7/N8) — ĐÃ audit sơ bộ ở AA-440 (xác nhận sẵn sàng nhất trong 3, đã có tenant_id+RLS ở 4 bảng). Task này cần đọc SÂU hơn phần T8 cụ thể (angle generation) — AA-440 chỉ xác nhận cấu trúc bảng, chưa audit chi tiết luồng "sinh 3 angle → recommend → người chọn" theo ADR mục 4.

Context — trích ADR-2026-038 mục 4, dòng T8 (nguồn gốc, chưa từng audit chi tiết):
"Input=Kế hoạch T7 (channel+goal), Xử lý=1) Goal list (`writing_formulars.xlsx`) → 2) brand audience → 3) formula theo goal → 4) sinh 3 angle → 5) recommend → 6) người chọn (dual-mode, mục 5), Output=1 angle duyệt, Map code cũ=Khớp D6 (PRD v1.3 archived) + Gate C trust-ramp (ADR-2026-026/036)".

Mục 10.3 (21/08): T8 đổi từ "Trang review + veto 48h (Gate C)" sang "Tenant tự duyệt hoàn toàn — không còn Trang/AA duyệt hộ trước publish".

AA-440 đã phát hiện: `trust_ramp.py` (Gate C) có mô hình 3 trạng thái, trạng thái cuối `veto_window_auto` có thể đã là hình dạng đúng cho A4 oversight — CHƯA quyết định, cần task này cân nhắc thêm khi audit chi tiết T8.

## Steps

1. Xác nhận T7 (Quarter Plan) → T8 handoff: sau khi tenant có kế hoạch quý (Quarter Plan, dù hiện tại vẫn qua Gate B admin — theo dữ liệu thật, chưa sửa code), điều gì trigger T8 (sinh angle)? Tìm trong `admin_produce.py`/`services/acp_produce/` — có function nào tên `generate_angles`/`angle_generation` tương ứng ADR mục 4 bước 1-5 không.
2. Đọc kỹ luồng sinh angle: `writing_formulars.xlsx` — file này có tồn tại trong repo/S3 không, được đọc bởi code nào? "Goal list" → "brand audience" → "formula theo goal" → "sinh 3 angle" — xác nhận từng bước có code thật tương ứng, hay chỉ 1 phần được build.
3. `admin_produce.py`'s Gate C review queue (`GET /admin/produce/packets`, đã trích ở AA-440 §3b) — đọc kỹ luồng "recommend → người chọn" — hiện tại là AI recommend rồi ADMIN chọn (dual-mode theo ADR mục 5) hay đã có cơ chế nào khác?
4. `trust_ramp.py` — đọc TOÀN BỘ (không chỉ đoạn đã trích ở AA-440), xác nhận: 3 trạng thái (`propose_only`, `approve_to_publish`, `veto_window_auto`) chuyển đổi theo điều kiện gì (track record, thời gian, số lần đúng?), tenant hiện tại đang ở trạng thái nào (query dev DB), có tenant nào đã đạt `veto_window_auto` chưa.
5. Đánh giá (không quyết định, chỉ trình bày dữ kiện): nếu áp dụng nguyên lý ADR mục 0.2 ("AA không gác cổng nội dung tenant") cho T8 — có nghĩa mọi tenant nên ở trạng thái tương đương `veto_window_auto` ngay từ đầu (không cần "ramp" dần), hay `trust_ramp` vẫn có giá trị như 1 cơ chế an toàn ban đầu cho tenant mới? Trình bày cả 2 góc nhìn, không tự quyết.
6. Query dev DB: đếm packet/piece theo trạng thái, xem có dữ liệu thật nào đã qua T8 chưa (kể cả qua đường admin cũ).

Verify: Không sửa code. Mọi kết luận có bằng chứng path:line hoặc query thật.

Sau khi done:
- Viết báo cáo vào `docs/claude_audit/AA-439-06-t7-t8-audit.md`.
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-439-06-audit-t7-t8.md`.
- git commit trên branch `feature/aa-439-tenant-tier-audit` — KHÔNG push, KHÔNG PR.
- Comment tóm tắt lên Linear AA-439.
- Paste nội dung báo cáo về Claude Chat.
