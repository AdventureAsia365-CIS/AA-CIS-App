## Task cho Claude Code: AA-415 — dành ngân sách repair riêng cho gate xuất hiện muộn

Mục tiêu: Hoàn tất AA-415. Verify N7 thật (run 363f22c9, 2026-09 W3) xác nhận PR #170 cải
thiện thật (F1 55.6%→75% pass) nhưng CHƯA hết — 1/3 piece fail F1 vẫn đúng cơ chế gốc:
F1 không fail ban đầu, xuất hiện sau 2 vòng repair F9, chỉ còn 1 vòng để tự sửa, hết ngân
sách trước khi kịp. Root cause còn lại: `compute_repair_budget()` không dành riêng slot
cho gate xuất hiện muộn trong quá trình repair.

Repo: AA-CIS-App
Branch hiện tại: main (verify bằng `git branch --show-current`)
Tạo branch mới: yes — `feature/aa-415-repair-budget-late-gate`
Merge vào: main

BƯỚC 0: lưu file task prompt này vào `docs/claude_tasks/AA-415-03-repair-budget-late-gate.md`
commit riêng đầu tiên trước khi code.

Files cần đọc trước:
- `services/acp_produce/repair.py` — hàm `compute_repair_budget()` và toàn bộ vòng lặp
  repair (đã sửa 2 lần ở PR #154, #170 — đọc kỹ lịch sử để không phá 2 fix trước).
- `docs/implementation-notes/AA-415-verify-real-run.md` — báo cáo verify vừa xong, có
  piece ID cụ thể tái hiện được bug (từ run 363f22c9).
- `docs/implementation-notes/AA-415-piece-invariants-f5-f9.md` — kết quả PR #170.

Context:
- Cơ chế cụ thể: piece có `initial_failing_gate_count` thấp (F1 pass ở draft đầu) trải
  qua nhiều vòng repair cho gate KHÁC (F9 lần này) — mỗi vòng repair có thể vô tình làm
  F1 fail (dù PR #170 đã giảm đáng kể khả năng này qua atom_text_by_id). Khi F1 fail xuất
  hiện ở vòng gần cuối, budget còn lại không đủ để tự sửa riêng — piece bị HELD.
- Không phải regression mới — là giới hạn thiết kế của cơ chế cấp budget hiện tại: budget
  tính theo `initial_failing_gate_count`, không tính tới khả năng gate MỚI xuất hiện giữa
  chừng do side-effect của repair gate khác.

Steps:
1. Đọc `compute_repair_budget()` — hiểu công thức hiện tại tính budget dựa trên số gate
   fail BAN ĐẦU thế nào.
2. Thiết kế lại: khi 1 gate MỚI xuất hiện (không có trong `initial_failing_gate_count`)
   giữa vòng repair, đảm bảo nó nhận được ÍT NHẤT 1 vòng repair riêng trước khi hết tổng
   budget — có thể là: (a) tăng tổng budget khi phát hiện gate mới xuất hiện (trade-off:
   tốn thêm LLM call/cost — cân nhắc giới hạn trần hợp lý), hoặc (b) dành riêng 1 slot dự
   phòng trong budget hiện có cho trường hợp này (trade-off: có thể làm gate fail-từ-đầu
   ít vòng sửa hơn).
3. Chọn phương án ít thay đổi nhất, ưu tiên (b) trước nếu khả thi — không tăng cost nếu
   tránh được. Nếu chọn (a), ghi rõ trade-off cost trong report (liên quan AA-418 cost
   tracking — không cần code cost tracking ở đây, chỉ ước tính bằng lời).
4. Verify bằng chính piece đã fail trong run 363f22c9 (dùng slot ID từ implementation
   notes) — tái hiện lại tình huống, xác nhận gate muộn giờ có budget để tự sửa.

Verify:
1. Unit test mới cho `compute_repair_budget()` với case gate xuất hiện muộn.
2. Chạy N7 thật 1 tuần MỚI (chưa từng chạy) — đối chiếu F1 pass rate với 2 baseline đã có
   (run #6: 55.6%, run 363f22c9: 75%) — kỳ vọng cải thiện thêm, không kỳ vọng 100% (vẫn
   còn 2/3 fail-từ-đầu không liên quan cơ chế này).
3. Xác nhận piece "Ride 99" (nghi F1 flag nhầm số trong tên riêng) — đọc kỹ held_reason,
   xác nhận có đúng là false positive không. Nếu đúng, đây là bug F1_grounding logic khác,
   KHÔNG sửa trong task này — ghi lại rõ ràng, đề xuất tách issue riêng NẾU xác nhận là
   bug thật (không tách nếu chưa chắc).
4. Deploy Dev qua CI, verify ECS digest khớp `:latest` (đã resolve MFA gap ở lần verify
   trước — dùng lại cách đã làm).
5. Lưu report vào `docs/implementation-notes/AA-415-repair-budget-late-gate.md`.

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Tạo branch mới: yes — feature/aa-415-repair-budget-late-gate
- Merge vào: main
- Sau khi done: `git add . && git commit -m "fix: reserve repair budget slot for late-appearing gates [AA-415]" && git push`, tự `gh pr create` (KHÔNG tự merge)

Sau khi done:
- Paste PR link + kết quả verify N7 thật (F1 pass rate mới) về Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-415 title khớp bối cảnh. Nếu F1 pass
  rate không còn fail theo cơ chế budget-hết (dù vẫn còn fail-từ-đầu không liên quan), đề
  xuất Nghiệp đóng AA-415 — không tự đổi status.
