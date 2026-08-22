## Task cho Claude Code: Audit A2→A3 (Admin QA Gate → Master Content Pool) — KHÔNG sửa code

Mục tiêu: Xác nhận trạng thái THẬT của handoff A2→A3 — không suy đoán, verify bằng code thật + query/gọi thử thật.

Repo: AA-CIS-App
Branch: feature/aa-438-admin-tier-audit (đã tồn tại từ AA-438-01/02 — checkout, KHÔNG tạo branch mới, KHÔNG push, KHÔNG PR ở task này).

Files cần đọc trước:
- `docs/claude_audit/AA-438-02-a1-a2-audit.md` — đọc trước. Đã xác nhận: approve ở Review Queue gọi `process_export()` đồng bộ trong cùng request (đọc code, CHƯA test live). A3 = `gold_aa_internal.published_tours` (theo AA-438-01).
- `services/export/handler.py` — CHƯA được đọc chi tiết ở 2 task trước (chỉ xem call boundary). Đây là trọng tâm task này — đọc toàn bộ `process_export()`.
- Router `v1_pipeline.py` quanh `approve_review` (đã trích 1 phần ở AA-438-02 §6, dòng ~432-498) — đọc rộng hơn để hiểu toàn bộ luồng approve → export.
- Trang "Master Content" trong sidebar admin — xác nhận route thật, dữ liệu hiển thị có phải từ `published_tours` không.

Context:
- Cả A0→A1 và A1→A2 đã xác nhận: A0 ghi `pipeline_runs`(status hardcode `'ingesting'`, không bao giờ update đúng), A1 ghi `generated_content` (status `approved`/`hitl`), A2 = review `hitl` rows qua `/admin/review`, approve gọi `process_export()`.
- ĐÃ GHI NHẬN (không xử lý trong task này, chỉ mang theo làm context):
  - `pipeline_runs.status` kẹt `'ingesting'` — xác nhận không ảnh hưởng luồng A1→A2, cần re-verify xem có ảnh hưởng A2→A3 không (VD: export có phụ thuộc `pipeline_runs.status` để quyết định gì không).
  - Reject không reset `generated_content.status` — 2 tour "mất tích" khỏi view mặc định.
  - 39 tour hitl tuổi 1-59 ngày, phần lớn pending, chưa ai xử lý.
  - Nghi vấn root-cause: A1 dùng DFS (DataForSEO) + brand rules chung (aa_internal, không phải tenant-specific) — Nghiệp nghi ngờ có tour điểm >7.0 vẫn fail do brand_audit quá nghiêm ngặt/mơ hồ, không phải do chất lượng rewrite thật sự kém. KHÔNG điều tra sâu DFS/brand trong task này (sẽ có task riêng sau) — nhưng NẾU trong lúc đọc `process_export`/`v1_pipeline.py` tình cờ thấy thông tin liên quan (VD: brand rule nào áp dụng cho aa_internal, config threshold), ghi chú lại luôn, đỡ phải đọc lại lần 2.

Steps:
1. Đọc toàn bộ `services/export/handler.py::process_export()` — luồng ghi vào `published_tours` là gì, có transform/validate gì thêm không, có phụ thuộc `pipeline_runs` để quyết định export hay không (đã có gợi ý ở AA-438-02 rằng chỉ UPDATE `pipeline_runs.status='completed'` khi batch xong, không đọc để quyết định — RE-VERIFY, đừng chỉ tin lại).
2. Xác nhận A3 (Master Content Pool) = chính xác bảng nào — `gold_aa_internal.published_tours` (đã nghi từ AA-438-01) — và cấu trúc dữ liệu ở đây khác gì so với `generated_content` (A1/A2 tier) — có transform gì đáng chú ý (VD: thêm SEO metadata, đổi format) không.
3. Trigger A2→A3: hoàn toàn tự động sau approve (đã có bằng chứng code từ AA-438-02) — verify thêm bằng cách TEST LIVE 1 lần nếu an toàn: chọn 1 tour hitl CŨ (từ 5 tour cũ nhất, đã pending 59 ngày, review_status vẫn pending, KHÔNG phải 1 trong 2 tour đã reject) → approve thật qua endpoint → xác nhận nó xuất hiện trong `published_tours` ngay sau đó. Đây là test có rủi ro thấp (đưa 1 tour thật vào Master Pool) nhưng vẫn cần xác nhận với việc này KHÔNG thể rollback dễ dàng — NẾU không chắc, chỉ đọc code, ghi rõ "không test live, theo hướng dẫn rủi ro".
4. FE: trang "Master Content" — route thật, `GET` endpoint nào, dữ liệu hiển thị đối chiếu với `published_tours` có khớp không.
5. Query dev DB: đếm `published_tours` theo trạng thái/ngày tạo gần nhất — xác nhận con số "72" từ AA-438-01 vẫn đúng (hoặc đổi nếu bước 3 có approve thật).
6. Sau khi vào A3 (Master Pool), điều gì xảy ra tiếp theo trong ADR (tenant có thể chọn tour từ Master Pool ở T1 Tour Selection) — chỉ cần xác nhận A3 output CÓ được T1 đọc vào không (grep tìm nơi tenant-facing code đọc `published_tours`), KHÔNG cần audit sâu T1 (sẽ có task riêng ở AA-439).

Verify: Không sửa code (trừ bước 3 nếu chọn test live approve — đây là thao tác qua UI/API thật, không phải sửa code, chấp nhận được theo đúng tinh thần "verify thật" đã áp dụng ở AA-436). Mọi kết luận có bằng chứng path:line hoặc query/response thật.

Sau khi done:
- Viết báo cáo vào `docs/claude_audit/AA-438-03-a2-a3-audit.md`.
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-438-03-audit-a2-a3.md`.
- git commit trên branch `feature/aa-438-admin-tier-audit` — KHÔNG push, KHÔNG PR.
- Comment tóm tắt lên Linear AA-438 (không đổi status).
- Paste nội dung báo cáo về Claude Chat.
- Nhắc rõ: "Đã commit local trên branch feature/aa-438-admin-tier-audit (nối tiếp AA-438-01, 02), chưa push."
