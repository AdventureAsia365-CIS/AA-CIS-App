# Task cho Claude Code: AA-351 — verify GPT-4.1 judge qua multi-round repair thật (N7)

Mục tiêu: AA-351-05 cho kết quả F9 9/9 (100%) với GPT-4.1 vs 1/9 Nova Pro — nhưng đây là
SINGLE-PASS judge (chấm 1 lần trên content đã có sẵn), không qua vòng lặp repair thật.
Không đủ để kết luận GPT-4.1 tốt hơn — có thể chỉ đang chấm dễ dãi hơn. Cần chạy 1 N7 tuần
thật với `JUDGE_MODEL=gpt41`, đi qua ĐÚNG multi-round repair loop, để trả lời câu hỏi thật:
GPT-4.1 có giải quyết được vấn đề "Nova Pro flag câu mới mỗi vòng repair, không hội tụ"
(phát hiện ở AA-382) hay không.

Repo: AA-CIS-App
Branch hiện tại: main (verify bằng `git branch --show-current`)
Tạo branch mới: no (chỉ set env var tạm thời cho 1 run test, không code)

BƯỚC 0: lưu file task prompt này vào `docs/claude_tasks/AA-351-06-gpt41-multiround-real-n7.md`.

Context:
- Code đã sẵn sàng: `JUDGE_MODEL` feature flag (`nova_pro | gpt56 | gpt41`) đã merge từ
  PR #175, mặc định vẫn `nova_pro` trong ECS task def production.
- Đây là THỬ NGHIỆM CÓ KIỂM SOÁT — set `JUDGE_MODEL=gpt41` CHỈ cho 1 lần chạy test, KHÔNG
  đổi task def production vĩnh viễn. Sau khi xong, PHẢI trả `JUDGE_MODEL` về mặc định
  (unset hoặc `nova_pro`) trước khi kết thúc task.
- Ngân sách OpenAI hiện chỉ còn ~$5.10 khả dụng (đã dùng 1 phần cho AA-351-05, 30 calls) —
  theo dõi cost sát, không chạy vượt quá 1 tuần test (dự kiến 6-12 piece, mỗi piece có thể
  gọi judge nhiều lần qua các vòng repair — ước tính tổng cost trước khi chạy, dừng nếu
  có dấu hiệu vượt ngân sách).

Steps:
1. Kiểm tra Run History, chọn 1 tuần CHƯA từng chạy (tránh trùng — có thể cần thêm Quarter
   Plan mới nếu Q4 hết slot, dùng đúng flow `/admin/quarter-plan` như đã làm cho AA-416-02).
2. Set `JUDGE_MODEL=gpt41` — qua cách phù hợp nhất với kiến trúc hiện tại (task-level env
   var override cho 1 lần chạy, hoặc tạm sửa ECS task def rồi revert ngay sau — chọn cách
   ÍT RỦI RO NHẤT, ưu tiên không đụng task def production nếu có cách khác).
3. Trigger N7 run thật cho tuần đã chọn.
4. Theo dõi xuyên suốt: với mỗi piece fail F9 ban đầu, đọc held_reason qua CÁC VÒNG repair
   liên tiếp — so sánh với hiện tượng Nova Pro đã biết (flag câu MỚI mỗi vòng dù câu cũ đã
   sửa đúng, có trường hợp câu đạt chuẩn vẫn bị flag lại).
5. Ghi lại: GPT-4.1 có hội tụ tốt hơn không (held_reason ổn định hơn, ít round hơn để pass,
   hay vẫn y hệt vấn đề cũ)? Đây là câu hỏi CHÍNH của task, quan trọng hơn pass rate thô.
6. Sau khi run xong — TRẢ `JUDGE_MODEL` về mặc định ngay (không để lại thay đổi production).

Verify:
1. Kết luận rõ ràng, có bằng chứng cụ thể (trích held_reason qua từng vòng của ít nhất 2-3
   piece): GPT-4.1 hội tụ tốt hơn Nova Pro, ngang nhau, hay vẫn có vấn đề tương tự (chỉ đổi
   dạng).
2. Ghi lại pass rate cuối cùng (sau hết vòng repair, không phải single-pass) — so sánh với
   baseline Nova Pro cùng loại (multi-round, không phải con số 1/9 single-pass cũ).
3. Cost thật của run này (số lần gọi GPT-4.1 × giá) — xác nhận không vượt ngân sách.
4. Xác nhận `JUDGE_MODEL` đã trả về mặc định sau khi xong — kiểm tra lại ECS task def.
5. Lưu report vào `docs/implementation-notes/AA-351-gpt41-multiround-real-n7.md`.

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Không code mới — chỉ commit report:
  `git pull origin main && git add docs/implementation-notes/AA-351-gpt41-multiround-real-n7.md docs/claude_tasks/AA-351-06-gpt41-multiround-real-n7.md && git commit -m "docs: AA-351 GPT-4.1 multi-round repair verify via real N7 run [AA-351]" && git push`

Sau khi done:
- Paste kết luận (hội tụ tốt hơn/ngang/vẫn có vấn đề) + bằng chứng held_reason cụ thể về
  Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-351 title khớp bối cảnh — không tự đổi
  status. Đây là dữ liệu quan trọng để Nghiệp quyết có đổi judge production hay không —
  trình bày rõ, không kết luận thay.
