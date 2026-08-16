## Task cho Claude Code: AA-415 — verify bằng N7 run thật, đối chiếu Run History

Mục tiêu: PR #170 (AA-415 — mở rộng PieceInvariants atom_text_by_id cho mọi vòng repair)
đã merge + deploy Dev thành công, nhưng CHƯA được verify bằng dữ liệu thật. Task này CHỈ
verify — không sửa code trừ khi phát hiện bug mới trong lúc verify.

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: no (chỉ trigger run qua UI/API thật + đọc kết quả, không code)

BƯỚC 0: lưu file task prompt này vào `docs/claude_tasks/AA-415-02-verify-real-n7-run.md`
trước khi bắt đầu (commit riêng `docs: save task prompt [AA-415]` nếu có thay đổi code đi
kèm sau này; nếu task này không tạo code change nào thì chỉ cần file này tồn tại trong
repo qua commit trực tiếp lên main, không cần branch riêng).

Context:
- Baseline cần so sánh: N7 run #6 (2026-09 W2, chạy 16/08 TRƯỚC PR #170) — F1_grounding
  5/9 pass (44% fail), ghi trong `docs/claude_audit/AA-404-n7-run6-results.md` và xác nhận
  lại qua Run History thật.
- PR #170 đã deploy Dev, ECS task định nghĩa mới đang chạy (nhưng CHƯA verify digest khớp
  `:latest` do MFA — nếu vẫn không verify được, ghi rõ trong report, không bỏ qua âm thầm).

Steps:
1. Trigger 1 N7 production run MỚI qua `/admin/produce` (route `POST .../produce/run`) cho
   tenant `Adventure Asia Internal`, chọn 1 tuần CHƯA từng chạy (kiểm tra Run History trước
   để chọn đúng tuần trống, tránh trùng — có thể dùng tuần kế tiếp sau 2026-09 W2, hoặc
   tuần khác đã có Quarter Plan Gate B approved).
2. Đợi run COMPLETED (theo dõi qua `GET .../produce/run/{id}` hoặc Run History UI).
3. Đọc gate_ledger đầy đủ của run mới — so sánh F1_grounding pass rate với baseline 5/9
   (run #6). Cũng ghi lại F9_brand_seo_audit và F9_brand_seo_audit_social pass rate (dù
   không phải mục tiêu chính của AA-415, dữ liệu này hữu ích cho AA-404 đang mở song song
   — không cần sửa gì, chỉ ghi lại).
4. Nếu có piece nào fail F1 sau khi trải qua repair F5/F9 — đọc kỹ held_reason, xác nhận
   cơ chế cũ (câu không có provenance tag) có còn xảy ra không. Nếu vẫn còn, đây là bug
   mới hoặc fix chưa đủ — ghi rõ, KHÔNG tự sửa thêm trong task này, báo lại trước.
5. Đối chiếu số liệu qua Run History UI thật (`aa-cis.lumiguides.it.com/admin/produce` →
   tab Run History) — chụp screenshot làm bằng chứng, không chỉ query DB.

Verify:
1. Kết luận rõ ràng: F1 pass rate SAU PR #170 so với baseline 5/9 — cải thiện, giữ nguyên,
   hay xấu đi? Đưa số liệu cụ thể (VD "8/9 pass, cải thiện từ 44% fail xuống 11% fail").
2. Nếu F1 KHÔNG cải thiện rõ rệt — đây là tín hiệu fix chưa đủ, ghi rõ và đề xuất bước tiếp
   theo (không tự ý code thêm, chờ quyết định).
3. Lưu report đầy đủ (số liệu trước/sau, screenshot Run History, held_reason nếu còn fail)
   vào `docs/implementation-notes/AA-415-verify-real-run.md`.
4. Chỉ SAU KHI có kết quả rõ ràng này, đề xuất Nghiệp có nên đóng AA-415 (Done thật, không
   phải auto-flip) hay không — không tự đổi status.

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Không code mới — chỉ trigger run + ghi report qua commit trực tiếp (docs only) hoặc PR
  nhỏ nếu cần thiết cho report — nếu tạo PR, tự `gh pr create`, không tự merge.

Sau khi done:
- Paste kết quả (số liệu F1/F9 trước-sau + screenshot) về Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-415 title khớp bối cảnh trước khi post
  comment kết quả verify — không tự đổi status.
