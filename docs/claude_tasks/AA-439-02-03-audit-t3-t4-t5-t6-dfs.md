## Task cho Claude Code: (A) Audit T3→T4, (B) Đọc tài liệu gốc aa-marketing-v2 + Audit T5→T6 với trọng tâm DFS scoring — KHÔNG sửa code

Đây là 2 việc gộp vào 1 task vì liên quan chặt (T4 là nơi tenant thấy tour trước khi sang T5, và T6 cần biết atom có được DFS-score trước khi curate hay không).

Repo: AA-CIS-App
Branch: feature/aa-439-tenant-tier-audit (đã tồn tại, đã gộp AA-438+AA-440 — checkout, KHÔNG tạo branch mới, KHÔNG push, KHÔNG PR).

---

## PHẦN A — Audit T3→T4 (Tenant QA Gate → Tenant Tour Pool) — bị bỏ sót ở AA-439-01

AA-439-01 đã xác nhận T1 trigger đúng chuỗi T2→T3→T5 (1 job), và T4 hiện badge "Extra QA pass" một phần — nhưng CHƯA audit riêng T4 như 1 trang/khái niệm độc lập (Tenant Tour Pool). Cần làm rõ:

1. Route T4 chính xác là gì — `/portal/t4-pool`? Xác nhận qua `Sidebar.tsx` (đừng giả định trùng tên AA-436 đã nhắc).
2. `CatalogTab.tsx` (đã đọc 1 phần ở AA-439-01 cho badge) — đọc TOÀN BỘ component: tenant thấy DANH SÁCH tour nào ở đây (chỉ tour của họ đã rewrite pass/auto-pass, hay cả tour raw chưa rewrite)? Filter/sort gì có sẵn?
3. Từ T4, tenant có hành động gì tiếp — click vào 1 tour để xem chi tiết? Có nút nào dẫn sang T6 (xem atom của tour đó) không, hay T6 là trang hoàn toàn tách biệt, tenant phải tự điều hướng qua sidebar?
4. Query dev DB: tenant thật (nếu có tour pass thật) nhìn thấy gì trên T4 — số tour, trạng thái.

---

## PHẦN B — Đọc tài liệu gốc `aa-marketing-v2` TRƯỚC khi audit T5→T6

**QUAN TRỌNG:** Nghiệp chỉ ra tài liệu gốc dùng để thiết kế N0-N8 (tiền thân T-series) nằm tại:
`docs/AI-gent-for automation works/aa-marketing-v2/` (lưu ý tên folder có khoảng trắng — dùng quote khi cd/ls). Đọc TOÀN BỘ tài liệu trong folder này (không chỉ 1 file) TRƯỚC khi audit code T5→T6 bên dưới.

**Điểm cụ thể cần tìm:** Nghiệp nhớ tài liệu này mô tả — sau khi atomize (T5/N2), có bước **kết hợp DFS (DataForSEO) để đánh dấu atom mức độ HIGH/MEDIUM/LOW** (liên quan/relevance scoring), giúp biết atom nào đáng ưu tiên. Nghiệp nghi ngờ **cơ chế này CHƯA được build trong code hiện tại** — nếu đúng, đây có thể là cách để tự động hóa/đẩy nhanh việc curate ở T6 (thay vì tenant phải tự lướt qua toàn bộ atom không phân loại).

Sau khi đọc tài liệu, XÁC NHẬN bằng code thật (không suy đoán):
1. Tài liệu mô tả cơ chế DFS-scoring atom (HIGH/MEDIUM/LOW) như thế nào — input, thuật toán, output mong đợi? Trích dẫn cụ thể phần liên quan.
2. Grep toàn repo tìm bất kỳ cột/field nào liên quan (`dfs_score`, `relevance`, `priority`, `atom_rank`, hoặc tên tương tự trên bảng `acp_contract.tour_atoms`) — xác nhận CÓ hay HOÀN TOÀN CHƯA CÓ trong schema/code hiện tại.
3. Nếu chưa có — xác nhận rõ đây là gap thật giữa thiết kế gốc (aa-marketing-v2) và code hiện tại, không phải đã bị lược bỏ có chủ đích ở đâu đó (kiểm tra ADR-2026-038 và các ADR liên quan xem có nhắc/loại bỏ chủ đích không — nếu không tìm thấy lý do loại bỏ, đây là gap chưa build, không phải quyết định đã chốt).

---

## PHẦN C — Audit T5→T6 (Atomize → Atom Curation), theo scope gốc + có thêm câu hỏi DFS

Files cần đọc trước (ngoài tài liệu Phần B):
- `docs/claude_audit/AA-439-01-t0-t1-audit.md` — §2a (T5 chạy vô điều kiện), §4 (data hiện có).
- `docs/claude_audit/AA-438-04-dashboard-setting-audit.md` §9 — Atom Curation admin dùng chung backend `_resolve_atom_owner_scope()` với `/portal/t6-atoms`.
- Route tenant portal `/portal/t6-atoms` — frontend + endpoint.
- `api/routers/admin_atoms.py` — CRUD atom đầy đủ.

Context ADR (như task gốc, giữ nguyên):
- ADR mục 4, T6: "Human curate/star/loại atom (tách rời, không tự động)".
- ADR mục 10.3: tenant tự thấy + curate atom của họ (AA-431).
- ADR mục 11.2 nói "T6 FE: 100% admin-only, chưa build" — CÓ THỂ đã lỗi thời (giống tình huống T0/T1 ở AA-439-01) — XÁC NHẬN bằng code, không tin theo câu chữ.

Steps (như task gốc + bổ sung câu hỏi DFS):
1. Xác nhận route `/portal/t6-atoms` tồn tại, hoạt động.
2. Đọc `_resolve_atom_owner_scope()` — xác nhận scope đúng, không có lỗ hổng tenant giả mạo thấy atom tenant khác.
3. Curate action (star/delete/edit) — tenant làm được gì, giới hạn gì.
4. **MỚI — quan trọng nhất:** Atom hiển thị trên `/portal/t6-atoms` HIỆN TẠI có bất kỳ điểm số/nhãn relevance nào không (HIGH/MEDIUM/LOW hay dạng số)? Nếu KHÔNG — tenant đang phải tự lướt qua toàn bộ atom không phân loại để chọn, xác nhận rõ trải nghiệm này (bao nhiêu atom trung bình 1 tenant có, để đánh giá mức độ cần thiết của DFS-scoring).
5. Trigger T6→T7: có nút "xong, sang lên kế hoạch" không.
6. Query dev DB: đếm atom theo `owner_scope`, xem cột nào liên quan curate (starred/deleted) đã có data chưa.

Verify: Không sửa code. Mọi kết luận có bằng chứng path:line, trích dẫn tài liệu, hoặc query/response thật.

Sau khi done:
- Viết 2 báo cáo riêng: `docs/claude_audit/AA-439-02-t3-t4-audit.md` (Phần A) và `docs/claude_audit/AA-439-03-t5-t6-dfs-scoring-audit.md` (Phần B+C).
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-439-02-03-audit-t3-t4-t5-t6-dfs.md`.
- git commit trên branch `feature/aa-439-tenant-tier-audit` — KHÔNG push, KHÔNG PR.
- Comment tóm tắt lên Linear AA-439.
- Paste nội dung cả 2 báo cáo về Claude Chat.
