## Task cho Claude Code: F1_grounding regression sau F5/F9 repair — mở rộng PieceInvariants

Mục tiêu: Fix AA-415 — F1_grounding bị fail "bất ngờ" sau vòng repair F5 (atom density) hoặc
F9 (brand/SEO audit), vì PieceInvariants (cơ chế chống cross-gate regression, có sẵn từ
PR #154 cho F3/F8) chưa được mở rộng để mang `atom_text_by_id` vào 2 vòng repair mới này.

Repo: AA-CIS-App
Branch hiện tại: main (verify bằng `git branch --show-current`)
Tạo branch mới: yes — `feature/aa-415-piece-invariants-f5-f9`
Merge vào: main

BƯỚC 0 — LÀM NGAY TRƯỚC KHI CODE (rule §2.1 skill ai-nghiep): lưu chính file task prompt
này vào repo, đúng nguyên văn, tại `docs/claude_tasks/AA-415-01-piece-invariants-f5-f9-repair.md`
— commit riêng 1 commit đầu tiên (`docs: save task prompt [AA-415]`) trước khi bắt đầu code.

Files cần đọc trước:
- `services/acp_produce/repair.py` — nơi `PieceInvariants` object được định nghĩa và dùng
  cho vòng repair F3/F8 (PR #154). Đây là cơ chế cần MỞ RỘNG, không viết mới.
- `docs/claude_audit/AA-404-n7-run6-results.md` — dữ liệu nguồn xác nhận cơ chế regression
  (N7 run #6, 16/08/2026).
- Node repair F5 (atom density, PR #162) và F9 (brand/SEO audit) trong graph pipeline N7 —
  tìm bằng `grep -r "F5_atom_density\|F9_brand_seo_audit" services/acp_produce/`.
- Prompt template dùng cho repair F5/F9 — tìm nơi build prompt gửi LLM khi repair 2 gate
  này, để thêm hướng dẫn `[R:atom_id]`/`[F:entry_id]` tag.

Context:
- Đã xác nhận qua Run History thật (`aa-cis.lumiguides.it.com/admin/produce`, tab Run
  History): F1_grounding tuần 2026-09 W2 (run mới nhất) = 5/9 pass (44% fail) — nhiều "held
  reason" ghi rõ `F1_grounding: sentence states ['400'] not present in its cited id(s)`
  kèm `F5_atom_density, F9_brand_seo_audit` trong cùng gate detail — đúng khớp cơ chế mô tả
  trong AA-415.
- Root cause: 1 piece có `initial_failing_gate_count=1` (F1 KHÔNG fail ở draft đầu) trải
  qua 2 vòng repair F9 + 1 vòng repair F5, và F1 chỉ xuất hiện lần đầu ở lần check CUỐI
  CÙNG — chưa từng có cơ hội tự repair riêng trước khi hết budget. Khi LLM sửa theo feedback
  F5 ("thêm chi tiết cụ thể vào đoạn thiếu atom") hoặc F9, nó thêm câu chữ KHÔNG có
  provenance tag hợp lệ — tạo F1 fail mới mà repair loop không biết để tránh.

Steps:
1. Đọc kỹ cách `PieceInvariants` mang `atom_text_by_id` vào vòng repair F3/F8 hiện tại —
   hiểu rõ shape/luồng dữ liệu trước khi mở rộng.
2. Mở rộng để CẢ vòng repair F5 và F9 cũng nhận được `atom_text_by_id` — dùng lại đúng cơ
   chế, không xây object/luồng mới.
3. Sửa prompt repair cho F5 và F9: thêm hướng dẫn rõ ràng — mọi câu mới thêm PHẢI có
   `[R:atom_id]` hoặc `[F:entry_id]` tag hợp lệ, dùng đúng atom đã biết trong
   `atom_text_by_id` (không bịa câu trần trụi không có provenance).
4. Không đổi logic F1_grounding, F5, F9 chính nó — chỉ đổi input mà vòng repair F5/F9 nhận
   được và hướng dẫn prompt.

Verify:
1. Chạy lại đúng piece đã fail trong N7 run #6 (hoặc test case tương tự tái hiện được cơ
   chế: piece pass F1 ở draft đầu, fail F5/F9, qua repair, rồi F1 fail) — xác nhận F1 không
   còn bị "bất ngờ" xuất hiện sau vòng repair F5/F9.
2. Chạy N7 thật 1 tuần mới (hoặc re-trigger tuần đã có) để lấy Run History thật — so sánh
   F1 pass rate với baseline (5/9 ở 2026-09 W2) — xác nhận có cải thiện thật, không chỉ unit
   test pass (bài học từ S149: unit test pass không đồng nghĩa content thật pass gate).
3. `npm run build` / backend test suite pass sạch (tuỳ ngôn ngữ repair.py — xác nhận bằng
   `pytest` nếu Python).
4. Deploy Dev qua CI, verify ECS task digest khớp `:latest`.
5. Lưu verify report (trước/sau F1 pass rate, root cause trace, run_id dùng để test) vào
   `docs/implementation-notes/AA-415-piece-invariants-f5-f9.md`.
6. KHÔNG tự đánh dấu Done — báo Nghiệp kết quả N7 run thật qua Run History trước khi coi
   là xong (không chỉ tin unit test/CI xanh).

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Tạo branch mới: yes — feature/aa-415-piece-invariants-f5-f9
- Merge vào: main
- Sau khi done: `git add . && git commit -m "fix: extend PieceInvariants atom_text_by_id to F5/F9 repair loops [AA-415]" && git push`, tự `gh pr create` (KHÔNG tự merge)

Sau khi done:
- Paste PR link + Run History screenshot (trước/sau) về Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-415 title khớp bối cảnh trước khi post
  comment. Nếu N7 run thật xác nhận F1 cải thiện rõ rệt, có thể đề xuất chuyển AA-415 sang
  Done — nhưng để Nghiệp quyết, không tự đổi status.
