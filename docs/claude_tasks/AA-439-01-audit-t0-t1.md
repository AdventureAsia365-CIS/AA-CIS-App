## Task cho Claude Code: Audit T0→T1 (Brand Identity Setup → Tour Selection) — KHÔNG sửa code

Mục tiêu: Task đầu tiên của nhịp Tenant (AA-439). Xác nhận trạng thái THẬT của handoff T0→T1 — không suy đoán từ ADR, verify bằng code thật + query/gọi thử thật.

Repo: AA-CIS-App
Branch mới: feature/aa-439-tenant-tier-audit (tạo từ main — đây là branch CHUNG cho toàn bộ AA-439, các task con sau sẽ nối tiếp trên CÙNG branch này, giống cách AA-438 đã làm). Chỉ commit local, KHÔNG push, KHÔNG PR ở task này — chờ lệnh tổng hợp sau khi toàn bộ AA-439 xong.

Files cần đọc trước:
- `docs/claude_audit/AA-438-*.md` (cả 4 file, Admin tier audit) — đọc nhanh để có context, KHÔNG audit lại phần Admin.
- `docs/claude_audit/AA-440-marketplace-planning-produce-migration-audit.md` — đọc trước, có liên quan gián tiếp (Atomize/atom owner_scope pattern).
- Trang tenant portal thật — tìm route `/portal/t0-brand` (đã xác nhận tồn tại từ AA-430) và tìm route T1 (tên CHƯA XÁC ĐỊNH — có thể là `/portal/t1-rewrite` theo pattern đã thấy ở AA-436, nhưng ĐỪNG giả định, đọc `Sidebar.tsx`/routing config thật của tenant portal để xác nhận tên chính xác).
- `api/routers/admin_pipeline.py` dòng liên quan `/api/admin/brand-identity` (đã biết có bug hardcode `tenant_id` — xem context ADR bên dưới, cần re-verify còn đúng không).

Context — trích ADR-2026-038 (đã biết trước, cần XÁC NHẬN lại bằng code, không audit mù):
- **Mục 10.1/10.4 (STEP0 investigation 21/08, AA-423/424):** T0 (Brand Identity) UI đã có (`BrandTab`), nhưng từng phát hiện bug: gọi `/api/admin/brand-identity` → `admin_pipeline.py:4086,4138` **hardcode `tenant_id = "0000...0001"`** + chỉ auth bằng secret tĩnh, không JWT. Bảng gốc `tenant_brand_rules` đã tenant-scoped sẵn. ADR nói: **AA-424 đã fix bug này** ("Fix T0 hardcode tenant_id — verify 2 tenant JWT thật, tách biệt đúng"). **CẦN XÁC NHẬN: fix này còn đúng sau các thay đổi gần đây (AA-436, AA-440) không, và đã test qua UI thật chưa** — ADR ghi rõ ở mục 11.2: "T0: Backend ✅ Fixed (AA-424), Frontend ⚠️ Chưa test qua UI thật, chỉ test API. Việc còn lại: Verify UI thật."
- **Mục 10.4/11.2:** T1 (Tour Selection): nút "Rewrite" hiện tại (thời điểm ADR viết, 21/08) xác nhận 100% là **Lane A/S1 cũ** (`PoolTab.tsx:98 → v1_tours.py:179 → v1_pipeline.py:82 → content_generation/graph.py`) — hoàn toàn tách biệt N7/atom pipeline, ghi vào `gold_aa_internal.tenant_tour_versions`. ADR nói: "Không tái dùng được — T1 mới phải là endpoint hoàn toàn mới, trigger job T2→T3→T4→T5." Nhưng ADR mục 11.1/11.2 CŨNG nói AA-425 đã **"Done — nối thẳng vào `_rewrite_tour()`/PoolTab, không cần endpoint mới"** và **"T1 (FE): 🟡 Chưa polish — label vẫn 'Rewrite', chưa hiện kết quả T3/T5 cho tenant"**. Đây là 2 phát biểu có vẻ MÂU THUẪN nhau trong chính ADR (endpoint mới vs nối vào cũ) — **CẦN ĐỌC CODE THẬT để biết cái nào đúng, không suy đoán, không cố hòa giải 2 câu — báo cáo rõ nếu vẫn mâu thuẫn sau khi đọc code.**
- Bối cảnh mới nhất (22/08, ADR mục 0.2): Quarter Plan/Marketplace vừa đổi hướng sang tenant self-service — không trực tiếp liên quan T0/T1 nhưng cùng tinh thần "AA không gác cổng nội dung tenant".

Steps:
1. Xác nhận route T0 thật (`/portal/t0-brand` hay tên khác) — vào code, xác nhận `BrandTab` gọi endpoint nào, có còn hardcode tenant_id không (re-verify AA-424's fix), auth pattern hiện tại (JWT `get_tenant()` hay vẫn secret tĩnh).
2. Xác nhận route T1 thật — tên chính xác, gọi endpoint nào. Đọc kỹ để giải quyết mâu thuẫn ADR nêu trên: nút "Viết"/"Rewrite" hiện tại trigger job GÌ — job cũ (Lane A/S1, chỉ ghi `tenant_tour_versions` không qua T3/T5) hay job mới (T2→T3→T4→T5 đầy đủ, đã xác nhận hoạt động thật từ AA-425/AA-436)? Đây là câu hỏi quan trọng nhất của task này.
3. Nếu vẫn có 2 luồng riêng biệt (nút cũ trỏ Lane A, nút/endpoint mới trỏ T2-T5) — xác nhận tenant portal UI hiện tại đang dùng luồng NÀO khi người dùng thật bấm nút trên UI (không phải chỉ gọi API tay).
4. FE: trang T0 và T1 — hiển thị gì cho tenant sau khi rewrite xong? ADR nói "chưa hiện kết quả T3/T5 cho tenant" — xác nhận còn đúng không, hay đã có badge/kết quả gì đó (liên hệ AA-436's badge "Extra QA pass" trên `CatalogTab.tsx` — đó là T4, khác route T1, xác nhận rõ 2 trang này khác nhau ra sao từ góc nhìn tenant).
5. Query dev DB: đếm `tenant_brand_rules` (bao nhiêu tenant đã setup brand), đếm `tenant_tour_versions` theo nguồn gốc (nếu phân biệt được lane cũ/mới qua cột nào).
6. Trigger thật: nếu an toàn, tự chọn 1 tenant test (không phải tenant thật đang hoạt động — dùng tenant test đã biết từ AA-438 SUMMARY: `test-agency`, `lumitest`, hoặc tương tự) để bấm thử nút T1 trên UI thật, xác nhận job nào chạy — ghi rõ nếu không làm được (không có quyền browser/Playwright) thì đọc code suy luận, nêu rõ.

Verify: Không sửa code. Mọi kết luận có bằng chứng path:line hoặc query/response thật. Đặc biệt: nếu tìm thấy điều gì mâu thuẫn với ADR, ghi RÕ RÀNG là mâu thuẫn, không tự âm thầm chọn 1 bên.

Sau khi done:
- Viết báo cáo vào `docs/claude_audit/AA-439-01-t0-t1-audit.md`.
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-439-01-audit-t0-t1.md`.
- git commit trên branch `feature/aa-439-tenant-tier-audit` — KHÔNG push, KHÔNG PR.
- Comment tóm tắt lên Linear AA-439 (không đổi status, vẫn In Progress).
- Paste nội dung báo cáo về Claude Chat.
- Nhắc rõ: "Đã commit local trên branch feature/aa-439-tenant-tier-audit, chưa push."
