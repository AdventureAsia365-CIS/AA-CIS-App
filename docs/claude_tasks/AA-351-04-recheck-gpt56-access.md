## Task cho Claude Code: AA-351 — recheck GPT-5.6 Sol access (subscription confirmed active)

Mục tiêu: Nghiệp vừa xác nhận qua email + AWS Console rằng subscription GPT-5.6 Sol
(Amazon Bedrock Edition) đã active trên acc3 — agreement `agmt-c7xh4ar8elze4dp2pbq9z4hpj`,
service start 2026-08-16 22:23 UTC+7, hiện trong "Active subscriptions" (Manage
Subscriptions page). Trước đó (AA-351-02) invoke vẫn trả `AccessDeniedException` sau 50+
phút polling — có thể đã hết thời gian propagate, cần thử lại NGAY.

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: no (chỉ test invoke, không code trừ khi cần bật lại code đã có từ AA-351-02)

BƯỚC 0: lưu file task prompt này vào `docs/claude_tasks/AA-351-04-recheck-gpt56-access.md`.

Steps:
1. Verify lại subscription qua CLI trên acc3 (profile `nghiep_aa365`):
   `aws bedrock list-foundation-model-agreement-offers --profile nghiep_aa365 --region us-west-1`
   — xác nhận agreement `agmt-c7xh4ar8elze4dp2pbq9z4hpj` hiện trạng thái ACTIVE.
2. Thử invoke GPT-5.6 Sol trực tiếp (1 request test đơn giản) qua đúng model ID đã dùng ở
   AA-351-02 (`invoke_judge_gpt56()` trong `shared/llm_client/judge_client.py` hoặc tên
   tương đương từ PR #173).
3. Nếu invoke THÀNH CÔNG lần này:
   a. Chạy ngay `aa351_compare.py` với `JUDGE_MODEL=gpt56` trên đúng 9 piece thật đã dùng
      cho Nova Pro baseline (từ run 88f094b1) — không cần lặp lại DRY_RUN, chạy thật luôn.
   b. Ghi lại đầy đủ: F8/F9 pass rate, latency/call, cost/call thật (không phải giá niêm
      yết — tính từ response usage thật).
   c. Cập nhật `docs/implementation-notes/AA-351-gpt56-judge-trial.md` với số liệu GPT-5.6
      Sol đầy đủ (thay chỗ "not measured" trước đó).
4. Nếu VẪN `AccessDeniedException` — ghi lại lỗi đầy đủ (request ID, timestamp, error
   message nguyên văn) để có bằng chứng cụ thể khi cần liên hệ AWS Support, và dừng lại,
   không tiếp tục poll vô hạn.

Verify:
1. Nếu invoke thành công — báo cáo đầy đủ bảng so sánh Nova Pro vs GPT-5.6 Sol (pass rate,
   cost, latency, held_reason mẫu để đánh giá độ nhất quán).
2. Nếu vẫn lỗi — báo cáo lỗi cụ thể, đề xuất bước tiếp theo (liên hệ AWS Support với
   agreement ID cụ thể).

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Chỉ commit report: `git pull origin main && git add docs/implementation-notes/AA-351-gpt56-judge-trial.md docs/claude_tasks/AA-351-04-recheck-gpt56-access.md && git commit -m "docs: AA-351 GPT-5.6 Sol access recheck + real comparison data [AA-351]" && git push`

Sau khi done:
- Paste kết quả (thành công + bảng so sánh, hoặc vẫn lỗi + chi tiết) về Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-351 title khớp bối cảnh — không tự đổi
  status, không tự quyết đổi judge production dù kết quả tốt.
