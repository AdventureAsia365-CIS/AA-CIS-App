## Task cho Claude Code: STEP0 Investigate T3 tenant-facing UI (KHÔNG sửa code)

Mục tiêu: Audit route/endpoint/response-shape/UI-pattern thật cho T3 (Tenant QA Gate) trước khi build UI. Đây là bước investigate thuần — không tạo/sửa code sản phẩm.

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: no (STEP0 investigate, không commit code — chỉ commit 2 file docs cuối task)
Merge vào: main (trunk-based, không còn develop)

Files cần đọc trước:
- `frontend/app/(internal)/admin/` hoặc tương đương tenant portal — xác nhận cấu trúc `/portal/*` sau route migration AA-430
- `Sidebar.tsx` (hoặc file routing tương đương đã đổi ở AA-430) — xem đã chừa sẵn `t3-review` chưa, tên chính xác là gì
- Router backend chứa `review_queue` (grep toàn repo, không giả định tên file)
- UI component của T4 (`/portal/t4-pool`) và T6 (`/portal/t6-atoms`, AA-431) — để biết pattern data-fetching + JWT auth + layout đã dùng

Context:
- ADR-2026-038 (Notion `3c3b8a41-ec5d-8123-911f-e0c308841e79`, mục 4+5+10.4): T3 = Tenant QA Gate. Backend AA-425 đã ghi escalation vào `review_queue` kèm `tenant_id`, payload structured `{check_id, field, description, source_span, suggested_fix}`. Self-repair tối đa 2 vòng trước khi escalate.
- AA-430 đã chuyển toàn bộ tenant portal từ tab-state (`/portal` single route) sang route thật (`/portal/t0-brand`, `/portal/t1-rewrite`, `/portal/t4-pool`, `/portal/t6-atoms`, ...). T3 route được cho là đã "chừa sẵn" theo convention nhưng CHƯA build UI — cần verify tên chính xác, KHÔNG giả định là `t3-review` (bài học AA-430: đã từng đoán nhầm catalog=T3 khi thực ra là T4).
- T6 (AA-431) là ví dụ gần nhất cho self-service tenant-facing UI mới build — có backend auth fix (`_resolve_atom_owner_scope()`) đi kèm UI. T3 có thể rơi vào tình huống tương tự (backend endpoint hiện có thể chưa filter đúng `tenant_id`/JWT) — cần verify, không giả định đã sẵn sàng 100%.
- Auth chuẩn tenant hiện tại: `get_tenant()` JWT pattern (xem AA-424, AA-431). KHÔNG dùng static-secret/hardcode tenant_id (đây từng là bug ở T0 trước AA-424).

Steps:
1. Đọc lại Sidebar/routing config thật sau AA-430 — liệt kê toàn bộ route `/portal/*` hiện có, xác nhận route dành cho T3 (tên chính xác, có tồn tại placeholder chưa hay hoàn toàn chưa có).
2. Grep `review_queue` toàn repo (backend) — liệt kê router/endpoint nào đọc/ghi bảng này, endpoint nào (nếu có) đã filter theo `tenant_id` qua JWT, endpoint nào chỉ admin-only.
3. Gọi thử endpoint đó (nếu có) qua ECS exec / ECS query hoặc curl với JWT tenant test (không tạo data giả, dùng data thật nếu có review_queue rows sẵn) — paste 1 ví dụ response JSON thật vào báo cáo.
4. Đọc code T4 (`/portal/t4-pool`) và T6 (`/portal/t6-atoms`) phía FE — ghi rõ file path, pattern data-fetching (React hook/SWR/fetch trực tiếp), pattern hiển thị list/detail, có component nào generic đủ để tái dùng cho T3 không.
5. Kết luận rõ: build task tiếp theo là "chỉ FE" (nếu backend đã đủ) hay "FE + 1 backend filter nhỏ" (nếu endpoint chưa filter tenant_id đúng) — giống hình mẫu quyết định gộp ở AA-431.

Verify: Không cần verify vận hành (không đổi code sản phẩm). Chỉ cần xác nhận đã đọc đúng file thật (dẫn chứng bằng path + snippet), không suy đoán.

Sau khi done:
- Viết báo cáo audit vào `docs/claude_audit/AA-436-t3-ui-step0-audit.md` (theo đúng §2.1 skill ai-nghiep — audit report, không phải task prompt) — gồm: route chính xác, endpoint(s) + response shape thật, component tái dùng từ T4/T6 (path cụ thể), gap backend nếu có, đề xuất rõ hướng build tiếp theo.
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-436-01-step0-investigate-t3-ui.md` (lưu nguyên văn, không tóm tắt) — bước này áp dụng từ S154, đừng bỏ sót.
- git commit -m "docs: AA-436 STEP0 audit T3 tenant UI investigation" && git push (KHÔNG cần PR review vì chỉ docs, có thể merge thẳng nếu CI xanh)
- Paste nội dung báo cáo (hoặc link file) về Claude Chat
- Linear: AA-436 → cập nhật comment với tóm tắt kết luận, KHÔNG tự chuyển Done (Claude Chat sẽ xác nhận qua báo cáo trước khi đổi trạng thái, theo ADR-2026-037: merge không tự chuyển Done)
