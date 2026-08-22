## Task cho Claude Code: Audit A0→A1 (Raw Ingest → Generic Rewrite with DFS) — KHÔNG sửa code

Mục tiêu: Xác nhận trạng thái THẬT của handoff A0→A1 — không suy đoán từ ADR, verify bằng cách đọc code thật + gọi thử/query thật.

Repo: AA-CIS-App
Branch: feature/aa-438-admin-tier-audit — đây là task ĐẦU TIÊN trong chuỗi audit AA-438 (A0→A1, A1→A2, A2→A3, Dashboard/Setting sẽ nối tiếp trên CÙNG branch này qua nhiều task sau).

**QUAN TRỌNG — không push/PR ở task này:**
- Nếu branch `feature/aa-438-admin-tier-audit` chưa tồn tại, tạo mới từ main.
- Nếu đã tồn tại (từ task con trước), checkout và tiếp tục trên đó — KHÔNG tạo branch mới.
- Commit 2 file docs của task này vào branch, nhưng **KHÔNG push, KHÔNG tạo PR** — chỉ commit local. Việc push + tạo PR sẽ làm 1 lần duy nhất sau khi TẤT CẢ task con của AA-438 xong (sẽ có task riêng "tổng hợp + push" báo khi nào tới lượt).
- Nếu CLAUDE.md của repo có rule khác mâu thuẫn với "không push", dừng lại hỏi Nghiệp qua Claude Chat trước khi tự quyết, đừng tự chọn.

Files cần đọc trước (không giả định tên, grep để xác nhận):
- Router/service xử lý ingest (sidebar admin có "Upload (S0)" — tìm endpoint thật đứng sau nó)
- Router/service xử lý "S1 Rewrite" (sidebar admin có mục này — đây có thể chính là A1, hoặc là thứ khác — XÁC NHẬN, đừng giả định)
- Bất kỳ Lambda/Step Functions definition nào liên quan ingest (Terraform hoặc AWS console nếu cần) — Dashboard hiện có ô "Ingestion Lambda" trạng thái "Idle"

Context:
- ADR-2026-038 định nghĩa A0=Raw Ingest, A1=Generic Rewrite with DFS (DFS = chưa rõ viết tắt gì trong context này — xác nhận nếu tìm thấy định nghĩa trong ADR hoặc code, đừng đoán).
- Admin dashboard hiện tại (`aa-cis.lumiguides.it.com/admin/dashboard`) hiển thị "Total Content: 94 (71 master + 23 tenant rewrites)", "Pass Rate: 0%", "Pipeline Activity (7D): No pipeline activity in the last 7 days" — trong khi AA-436 vừa chạy nhiều pipeline run thật hôm nay. Nghi ngờ dashboard dùng data cũ/cache/query sai — XÁC NHẬN có đúng không, nếu đúng thì query nào đang lỗi.
- Sidebar admin hiện có các mục: Dashboard, Tenants, Marketplace, Quarter Plan (Gate B), Produce & Deliver (N7/N8), Run Health, Atomize (N2), Atom Curation, Upload (S0), S1 Rewrite, Review Queue, Brand Identity, Master Content, Settings. Một số tên dùng ký hiệu cũ (N2, N7/N8, S0/S1) khác với ký hiệu A0-A3/T0-T11 trong ADR-2026-038 — cần map rõ tên cũ ↔ tên mới, đừng giả định trùng khớp.

Steps:
1. Xác nhận A0 (Raw Ingest) tương ứng route/mục sidebar nào (nghi là "Upload (S0)") — đọc code thật, tìm endpoint upload xử lý ra sao, ghi vào bảng `raw_tours` hay bảng nào khác.
2. Xác nhận A1 (Generic Rewrite with DFS) tương ứng mục nào (nghi là "S1 Rewrite") — đọc code, xác nhận DFS là gì trong context code thật (biến/comment/tên hàm), input từ A0 lấy từ đâu.
3. Trigger giữa A0→A1: sau khi upload xong (A0), điều gì khiến A1 chạy — tay bấm admin, hay tự động? Đọc code xác nhận, không đoán.
4. Query dev DB thật: đếm số row trong bảng chứa A0 output, số row đã qua A1 (có cột đánh dấu status không), paste kết quả query thật.
5. Kiểm tra vì sao Dashboard hiện "No pipeline activity 7D" — tìm query đứng sau ô đó, so với dữ liệu thật vừa query ở bước 4, xác định có phải bug (sai filter ngày, sai bảng, hardcode) hay đúng là do A0/A1 không chạy qua job orchestration nên "pipeline activity" không tính admin-tier stages.
6. FE: "Upload (S0)" và "S1 Rewrite" trong sidebar — click thử (nếu có Playwright/test env) hoặc đọc route component — xác nhận trang có hoạt động thật (gọi API thật) hay là placeholder/mock.

Verify: Không sửa code. Mọi kết luận phải có bằng chứng — snippet code với path:line, hoặc kết quả query thật, hoặc response API thật. Không dùng "có vẻ", "chắc là" — nếu không xác nhận được, ghi rõ "chưa xác nhận được, cần thêm access X".

Sau khi done:
- Viết báo cáo vào `docs/claude_audit/AA-438-01-a0-a1-audit.md` — theo đúng 5 mục (Trigger/Backend/Frontend/Data/Gap).
- Copy CHÍNH task prompt này (nguyên văn) vào `docs/claude_tasks/AA-438-01-audit-a0-a1.md`.
- git commit -m "docs: AA-438-01 audit A0->A1 handoff" trên branch `feature/aa-438-admin-tier-audit` — **KHÔNG git push, KHÔNG tạo PR.**
- Comment tóm tắt lên Linear AA-438 (không phải issue mới, không đổi status).
- Paste nội dung báo cáo (hoặc link file) về Claude Chat.
- Nhắc rõ trong output: "Đã commit local trên branch feature/aa-438-admin-tier-audit, chưa push — chờ task con tiếp theo hoặc lệnh tổng hợp push cuối."
