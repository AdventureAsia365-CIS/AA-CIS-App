## Task cho Claude Code: Audit A1→A2 (Generic Rewrite → Admin QA Gate) — KHÔNG sửa code

Mục tiêu: Xác nhận trạng thái THẬT của handoff A1→A2 — không suy đoán, verify bằng code thật + query/gọi thử thật.

Repo: AA-CIS-App
Branch: feature/aa-438-admin-tier-audit (đã tồn tại từ task AA-438-01 — checkout, KHÔNG tạo branch mới, KHÔNG push, KHÔNG PR ở task này — giữ nguyên nguyên tắc đã áp dụng ở AA-438-01).

Files cần đọc trước (không giả định tên, dựa trên phát hiện của AA-438-01):
- `docs/claude_audit/AA-438-01-a0-a1-audit.md` — đọc trước, đây là điểm nối tiếp trực tiếp: A1 ghi vào `silver_aa_internal.generated_content`, với 39 row hiện tại ở `status='hitl'` — đây rất có thể CHÍNH LÀ A2 (Admin QA Gate), cần xác nhận.
- `services/content_generation/graph.py` (`build_graph`) — 7 node LangGraph đã nhắc ở audit trước (`generate → validate → llm_judge → brand_audit → flag_fix → revalidate`) — node nào chính là "QA Gate", `status='hitl'` được set ở đâu trong graph này.
- Router xử lý HITL review (tìm bằng grep `hitl`, `review`, `generated_content.*status` trong `api/routers/`) — đây có khả năng là "Review Queue" trong sidebar admin — XÁC NHẬN, đừng giả định trùng khớp tên.
- FE: trang "Review Queue" trong sidebar (`frontend/app/admin/`, tìm route thật) — xác nhận có hiển thị 39 tour hitl thật không, admin thao tác gì ở đây (approve/reject/edit).

Context:
- ADR-2026-038: **KHÔNG có trong repo code** (xác nhận từ AA-438-01) — Claude Chat sẽ tự đối chiếu với bản Notion sau khi nhận báo cáo. KHÔNG cố tìm/đoán nội dung ADR trong task này, chỉ audit code thật.
- A1 (S1 Rewrite) ghi kết quả vào `silver_aa_internal.generated_content`. Trạng thái `status='hitl'` xuất hiện khi rewrite cần người duyệt — nghi đây chính là A2 (Admin QA Gate), nhưng CẦN XÁC NHẬN qua code, không giả định.
- 39 tour hiện đang kẹt ở `status='hitl'` (theo AA-438-01, query 22/08). Cần hiểu: (a) vì sao chúng vào hitl (điều kiện gì trong graph khiến rẽ nhánh này), (b) có UI nào cho admin xử lý 39 tour đó không, (c) nếu admin xử lý xong (approve), điều gì xảy ra tiếp — có tự động sang A3 (Master Content Pool) không hay vẫn cần thao tác tay tiếp.
- Lỗi `pipeline_runs.status` kẹt `'ingesting'` mãi mãi khi có tour hitl trong batch (đã xác nhận ở AA-438-01) — không sửa trong task này, chỉ cần XÁC NHẬN xem điều này có ảnh hưởng gì đến luồng A1→A2 hay chỉ ảnh hưởng dashboard (đã xác nhận ở AA-438-01 là chỉ ảnh hưởng dashboard, nhưng double-check nếu thấy bằng chứng khác).

Steps:
1. Đọc `graph.py::build_graph` — xác nhận node/điều kiện nào set `generated_content.status='hitl'` (khác với node nào set `status='published'` hay trạng thái khác).
2. Xác nhận A2 (Admin QA Gate) là gì trong code thật — có phải chính là các tour rơi vào `status='hitl'`, cần admin review qua 1 trang cụ thể? Hay A2 là một bước tách biệt khác (VD 1 endpoint riêng "QA check" chạy sau A1 mà chưa nối UI)?
3. Trigger A1→A2: rẽ nhánh trong graph tự động (dựa trên `llm_judge`/`brand_audit` score) hay cần thao tác tay?
4. FE: route/trang admin cho việc xử lý 39 tour hitl — path cụ thể, hành động thật (approve/reject/edit) gọi endpoint nào, xác nhận hoạt động thật (không mock).
5. Query dev DB: đếm `generated_content` theo từng `status` (không chỉ hitl — tất cả trạng thái có), để có bức tranh đầy đủ trạng thái A1 output. Xem 39 tour hitl đã kẹt bao lâu (created_at/updated_at) — có tour nào kẹt hàng tuần/tháng không.
6. Sau khi admin approve 1 tour hitl (nếu có thể test thật, không phá dữ liệu — nếu rủi ro, chỉ đọc code để suy ra hành vi, ghi rõ "không test thật, suy từ code"), điều gì xảy ra tiếp — có tự vào A3 (`published_tours`) không.

Verify: Không sửa code. Mọi kết luận có bằng chứng path:line hoặc query thật. Ghi rõ "chưa xác nhận được" nếu không chắc.

Sau khi done:
- Viết báo cáo vào `docs/claude_audit/AA-438-02-a1-a2-audit.md`.
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-438-02-audit-a1-a2.md`.
- git commit trên branch `feature/aa-438-admin-tier-audit` — KHÔNG push, KHÔNG PR.
- Comment tóm tắt lên Linear AA-438 (không đổi status, vẫn In Progress).
- Paste nội dung báo cáo (hoặc link file) về Claude Chat.
- Nhắc rõ: "Đã commit local trên branch feature/aa-438-admin-tier-audit (nối tiếp AA-438-01), chưa push."
