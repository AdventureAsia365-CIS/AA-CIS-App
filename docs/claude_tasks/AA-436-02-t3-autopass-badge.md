## Task cho Claude Code: T3 đổi hành vi sang auto-pass sau 2 vòng fail + badge nhẹ T4

Mục tiêu: T3 QA Gate không còn escalate-chặn tenant nữa. Sau `TENANT_QA_MAX_REPAIRS=2` vòng self-repair vẫn fail, hệ thống tự gắn cờ `qa_auto_passed=true` và tiếp tục chuỗi T4→T5 bình thường (không dừng lại chờ tenant). Tenant chỉ thấy 1 badge nhẹ trên tour đó ở T4 pool, không thấy chi tiết lỗi.

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: yes — feature/aa-436-t3-autopass
Merge vào: main (trunk-based, CI required check: 5 job Lint/Security/Unit/Integration/Docker)

Files cần đọc trước:
- `services/acp_produce/tenant_pipeline.py` — hàm `escalate_t3_failure()` (dòng ~156-190 theo audit STEP0) và nơi gọi nó (`api/routers/v1_tours.py:378`, background task rewrite)
- `docs/claude_audit/AA-436-t3-ui-step0-audit.md` — báo cáo STEP0 đầy đủ, đọc trước khi đổi bất cứ gì (đặc biệt mục 2a: shape thật của `escalate_detail`, mục 3: 11 row T3 thật hiện có trong dev DB, tenant `Test Agency` is_active=false)
- `frontend/app/(tenant)/portal/_components/CatalogTab.tsx` (711 dòng, T4) — nơi thêm badge, đọc kỹ cấu trúc list item hiện có trước khi chèn
- `api/migrations/` — xem migration gần nhất (107 đã nhắc trong audit) để đặt số migration mới đúng thứ tự

Context:
- Quyết định kiến trúc: ADR-2026-038 mục 0.1 (Notion `3c3b8a41-ec5d-8123-911f-e0c308841e79`), amend mục 10.3 — đảo ngược hướng self-service T3 đã chốt 21/08. Lý do: tenant tự sửa câu chữ khi QA fail là trải nghiệm tệ, và escalate-chặn phá vỡ chuỗi tự động T2→T3→T5 chạy 1 job.
- Linear: AA-436 (issue này) — đã đổi tiêu đề/mô tả 22/08, KHÔNG còn là "T3 tenant-facing UI riêng" như task STEP0 trước đó đã investigate.
- `review_queue` INSERT (write path AA-425) KHÔNG đổi — vẫn ghi đúng như hiện tại, chỉ đổi ý nghĩa: không còn là hàng chờ chặn tenant, mà là log cho A4 đọc sau này (AA-437, issue riêng, KHÔNG thuộc task này).
- 2 endpoint đọc `review_queue` hiện có (`admin_pipeline.py`, `v1_pipeline.py`) — KHÔNG đụng vào, chúng phục vụ flow N0-N6 admin khác, ngoài phạm vi task này.
- Badge text tiếng Anh — đề xuất "Extra QA pass" nhưng CHƯA chốt chính thức, xác nhận lại với Nghiệp trước khi hardcode nếu thấy cách diễn đạt khác rõ hơn (tránh gây hiểu lầm là "lỗi", nên nghiêng về trung tính/tích cực).

Steps:
1. Migration mới: thêm cột `qa_auto_passed BOOLEAN NOT NULL DEFAULT false` vào `gold_aa_internal.tenant_tour_versions`. Additive thuần, không cần backfill (giá trị mặc định false là đúng cho mọi row cũ).
2. Trong `tenant_pipeline.py`, tìm đúng điểm mà self-repair đã hết `TENANT_QA_MAX_REPAIRS=2` vòng và (theo code hiện tại) gọi `escalate_t3_failure()` rồi dừng chuỗi. Đổi hành vi:
   - Vẫn gọi `escalate_t3_failure()` như cũ (ghi `review_queue`, KHÔNG đổi hàm này) — giữ log cho A4.
   - Thêm: set `qa_auto_passed=true` trên `tenant_tour_versions` row tương ứng.
   - Tiếp tục chuỗi sang T4 (ghi vào pool) + trigger T5 atomize — dùng đúng code path hiện có cho trường hợp "pass thật", không tạo nhánh song song.
3. Xử lý rõ: điều gì xảy ra nếu chính T5 atomize fail sau khi auto-pass (edge case, cần verify code hiện tại xử lý fail T5 ra sao, áp dụng y hệt cho cả 2 trường hợp pass thật và auto-pass — không cần logic mới).
4. FE: `CatalogTab.tsx` — thêm badge nhỏ (dùng `Badge` component có sẵn từ `ui.tsx`, theo đúng convention T4/T6 đã audit) hiện khi tour có `qa_auto_passed=true`. Không click được, không mở modal/detail nào. Đặt cạnh trạng thái tour hiện có, không che thông tin khác.
5. Cần thêm field `qa_auto_passed` vào response của endpoint T4 đang serve `CatalogTab.tsx` (kiểm tra endpoint nào, có thể đã có sẵn SELECT * hoặc cần thêm cột tường minh).

Verify:
- Migration chạy sạch trên DB dev thật (không chỉ dry-run).
- Trigger 1 tenant rewrite thật với input cố tình gây fail 2 vòng (ví dụ dùng brand rule có forbidden word xung đột) — xác nhận: (a) tour vẫn xuất hiện trong T4 pool, (b) `tour_atoms` có atom mới (T5 chạy), (c) `qa_auto_passed=true` trong DB, (d) `review_queue` vẫn có row escalate như trước, (e) badge hiện đúng trên UI thật (screenshot).
- Xác nhận tour KHÔNG qua auto-pass (pass bình thường ở vòng 1 hoặc 2) thì `qa_auto_passed=false`, không hiện badge.
- pytest suite xanh, CI 5 job xanh.

Sau khi done:
- Viết implementation notes vào `docs/implementation-notes/AA-436-t3-autopass.md` — theo convention hiện có, gồm bằng chứng verify thật (query kết quả, screenshot).
- Copy CHÍNH task prompt này (nguyên văn) vào `docs/claude_tasks/AA-436-02-t3-autopass-badge.md` trước khi báo done.
- git commit -m "feat: AA-436 T3 auto-pass after 2 repair rounds + badge on T4" && git push
- Tạo PR, đợi Nghiệp review/merge tay (không tự merge — thay đổi hành vi pipeline thật, không phải docs-only).
- Paste kết quả verify (bằng chứng thật, không chỉ tóm tắt) về Claude Chat.
- Linear: AA-436 → comment tóm tắt kết quả, KHÔNG tự chuyển Done (theo ADR-2026-037, chờ Nghiệp xác nhận qua PR merge + verify thật).
