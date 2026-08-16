# Task cho Claude Code: AA-351 — chạy lại so sánh GPT-4.1 vs Nova Pro, credit đã nạp

Mục tiêu: OpenAI credit đã được nạp lại (xác nhận qua Billing Console: Credit Grant $10.00
mới, balance khả dụng $5.10/$15.00). Chạy lại harness so sánh (`aa351_compare.py`) với
`JUDGE_MODEL=gpt41` — lần trước (AA-351-03) 0/9 calls thành công vì hết credit, code đã
sẵn sàng (PR #175 đã merge, deployed Dev, feature-flagged, KHÔNG đổi hành vi production —
`JUDGE_MODEL` vẫn unset trong ECS task def nên N7 vẫn mặc định Nova Pro).

Repo: AA-CIS-App
Branch hiện tại: main (verify bằng `git branch --show-current`)
Tạo branch mới: no trừ khi cần sửa code (không dự kiến — chỉ chạy lại harness đã có)

**Đồng thời — quan trọng không kém — verify lại S1 production judge:**
AA-419 (Urgent, đang mở) ghi nhận `judge_node.py` (S1 brand-fit judge) đã fail âm thầm
100% do cùng nguyên nhân hết credit OpenAI. Cần xác nhận credit mới ĐÃ khôi phục S1 judge
hoạt động lại — không chỉ giả định vì balance > 0.

BƯỚC 0: lưu file task prompt này vào `docs/claude_tasks/AA-351-05-run-comparison-credits-restored.md`.

Files cần đọc trước:
- `docs/implementation-notes/AA-351-gpt41-judge-trial.md` — kết quả AA-351-03 (0/9 do hết
  credit), cấu trúc harness đã dùng.
- `docs/implementation-notes/AA-351-gpt56-judge-trial.md` — baseline Nova Pro đã có (F9
  1/9, F8 5/6, trên 9 piece thật từ run 88f094b1).
- `judge_node.py` (S1) — nơi gọi GPT-4.1 production, cần verify riêng.

Steps — Phần A: verify S1 GPT-4.1 judge đã phục hồi
1. Gọi thử `judge_node.py` với 1 request thật (hoặc trace call gần nhất trong log/DB nếu
   S1 có chạy tự nhiên gần đây) — xác nhận response THÀNH CÔNG (không phải lỗi credit).
2. Nếu có thể, điều tra khoảng thời gian credit hết trước đó (log timestamp) — ước tính
   số lượng content S1 đã publish thiếu judge trong giai đoạn đó, ghi vào report cho AA-419
   (không cần re-judge content cũ trong task này, chỉ ước tính phạm vi).

Steps — Phần B: chạy lại so sánh N7 F8/F9 (mục tiêu chính AA-351)
1. Chạy `aa351_compare.py` với `JUDGE_MODEL=gpt41` trên ĐÚNG 9 piece thật đã dùng cho Nova
   Pro baseline (run 88f094b1) — same content, so sánh công bằng.
2. Nếu vẫn fail (dù credit đã nạp) — kiểm tra kỹ: có phải lỗi khác (rate limit mới do
   $5.10 hạn mức thấp, hay lỗi code) — không giả định lại "hết credit" nếu balance đã xác
   nhận > 0.
3. Ghi lại đầy đủ: F8/F9 pass rate GPT-4.1, latency/call, cost/call thật (từ response
   usage), và đặc biệt — held_reason có nhất quán hơn Nova Pro không (vấn đề chính cần
   giải, không chỉ pass rate thô).
4. Cân nhắc: với balance chỉ $5.10 khả dụng, ước tính số lần gọi tối đa có thể test trước
   khi hết — không chạy vượt quá cần thiết cho 9 piece so sánh này.

Verify:
1. Bảng so sánh đầy đủ 3 cột: Nova Pro (đã có) | GPT-5.6 Sol (vẫn pending AWS case
   178689930800206) | GPT-4.1 (đo trong task này).
2. Cập nhật `docs/implementation-notes/AA-351-gpt41-judge-trial.md` với số liệu thật thay
   vì "0/9 do hết credit".
3. Xác nhận S1 judge phục hồi — ghi vào cả report này VÀ chuẩn bị dữ liệu cho comment
   riêng trên AA-419.
4. KHÔNG tự ý đổi Nova Pro → GPT-4.1 trong production N7 dù kết quả tốt — chỉ báo cáo.

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Chỉ commit report (không có code change dự kiến):
  `git pull origin main && git add docs/implementation-notes/AA-351-gpt41-judge-trial.md docs/claude_tasks/AA-351-05-run-comparison-credits-restored.md && git commit -m "docs: AA-351 GPT-4.1 comparison with restored credits + S1 judge recovery verify [AA-351][AA-419]" && git push`

Sau khi done:
- Paste bảng so sánh 3 model + kết quả verify S1 judge về Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh cả AA-351 VÀ AA-419 title khớp bối cảnh
  trước khi post — comment riêng cho từng issue (AA-351: kết quả so sánh; AA-419: xác nhận
  S1 judge phục hồi + ước tính phạm vi ảnh hưởng). Không tự đổi status của AA-351. Với
  AA-419, nếu S1 xác nhận hoạt động lại bình thường, đề xuất đóng — để Nghiệp quyết.
