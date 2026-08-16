## Task cho Claude Code: AA-351 tiếp — thử GPT-4.1 (ngoài AWS) làm judge F8/F9

Mục tiêu: GPT-5.6 Sol (AA-351-02) bị chặn ở tầng AWS quota (50+ phút không cấp, chưa rõ
nguyên nhân) — tạm dừng chờ AWS. Trong lúc chờ, thử GPT-4.1 — model đã có sẵn hạ tầng thật
(đang dùng làm T3 last-resort cho S1, gọi trực tiếp OpenAI API ngoài AWS, theo
ADR-2026-031) — làm judge thay thế Nova Pro cho F8/F9. Không cần chờ AWS, có thể chạy
ngay.

Repo: AA-CIS-App
Branch hiện tại: main (verify bằng `git branch --show-current`)
Tạo branch mới: yes — `feature/aa-351-gpt41-judge-trial`
Merge vào: main

**LƯU Ý — có thể chạy song song với AA-416-02 (verify N7 run thật cho event-loop fix).**
AA-416-02 KHÔNG code, chỉ trigger run + đọc kết quả — rủi ro đụng file gần như 0. Vẫn nên
`git pull origin main` trước khi push, vì AA-351-02 (PR #173, GPT-5.6) đã merge trước đó —
code của bạn cần build TRÊN NỀN đó, không ghi đè.

BƯỚC 0: lưu file task prompt này vào `docs/claude_tasks/AA-351-03-gpt41-judge-f8-f9.md`
commit riêng đầu tiên trước khi code.

Files cần đọc trước:
- `docs/implementation-notes/AA-351-gpt56-judge-trial.md` — kết quả AA-351-02: đã có
  `invoke_judge_gpt56()` + `JUDGE_MODEL` feature flag (nova_pro | gpt56), harness so sánh
  `aa351_compare.py` đã verify đúng với Nova Pro (baseline F9 1/9, F8 5/6 trên 9 piece
  thật từ run 88f094b1).
- Node judge S1 hiện tại (`judge_node.py` hoặc tương đương) — nơi ĐÃ gọi GPT-4.1 qua OpenAI
  API trực tiếp (ngoài AWS) cho pipeline S1 — đây là client/pattern cần TÁI SỬ DỤNG, không
  viết mới. Tìm biến môi trường `OPENAI_API_KEY` và cách client được khởi tạo.
- `shared/llm_client/judge_client.py` (hoặc tên tương đương chứa `invoke_judge_gpt56()`
  vừa thêm ở AA-351-02) — thêm nhánh GPT-4.1 theo đúng cấu trúc feature-flag đã có.

Context:
- Đã có 2 nhánh judge: `nova_pro` (mặc định, production) và `gpt56` (mới, đang chờ AWS
  quota). Thêm nhánh thứ 3: `gpt41` — gọi thẳng OpenAI API (không qua Bedrock/AWS), dùng
  lại pattern/key đã có cho S1.
- Rubric gửi cho GPT-4.1 PHẢI giữ nguyên y hệt rubric Nova Pro/GPT-5.6 đã dùng (F8
  FRAMEWORK_RUBRICS, F9 brand/SEO rubric + good/bad anchor) — so sánh công bằng.
- Cost GPT-4.1 khác Bedrock — cần tra giá thật OpenAI API hiện hành (không đoán, search
  nếu cần) để so sánh cùng bảng với Nova Pro/GPT-5.6.

Steps:
1. Xác nhận client GPT-4.1 hiện dùng cho S1 — copy đúng pattern auth/retry/error-handling,
   không viết lại từ đầu.
2. Thêm `invoke_judge_gpt41()` vào cùng file chứa `invoke_judge_gpt56()` — cùng interface
   (nhận rubric + content, trả về structured judge response giống Nova Pro/GPT-5.6).
3. Mở rộng `JUDGE_MODEL` feature flag: `nova_pro | gpt56 | gpt41`. Default vẫn `nova_pro`
   — không đổi hành vi production.
4. Chạy `aa351_compare.py` (harness đã có, không viết lại) với `JUDGE_MODEL=gpt41` trên
   CÙNG 9 piece thật đã dùng cho Nova Pro baseline (từ run 88f094b1) — đảm bảo so sánh công
   bằng, cùng dữ liệu.
5. Ghi lại: F8/F9 pass rate, latency/call, cost/call (giá OpenAI thật), và đặc biệt —
   held_reason có nhất quán hơn giữa các vòng không (đây là vấn đề chính cần giải, không
   chỉ pass rate).

Verify:
1. `pytest` pass sạch, không phá test hiện có (kể cả test mới từ AA-351-02).
2. Bảng so sánh đầy đủ 3 cột: Nova Pro (đã có từ AA-351-02) | GPT-5.6 Sol (chưa đo, để
   trống/note "pending AWS quota") | GPT-4.1 (đo trong task này).
3. Deploy Dev qua CI (feature-flagged, an toàn vì default vẫn nova_pro).
4. Lưu report vào `docs/implementation-notes/AA-351-gpt41-judge-trial.md` — CẬP NHẬT vào
   cùng file `AA-351-gpt56-judge-trial.md` nếu hợp lý hơn (gộp bảng so sánh 3 model 1 chỗ),
   tự quyết theo cấu trúc nào rõ ràng hơn.
5. KHÔNG tự ý đổi Nova Pro → GPT-4.1 trong production dù kết quả tốt — chỉ báo cáo, để
   Nghiệp quyết.

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Tạo branch mới: yes — feature/aa-351-gpt41-judge-trial
- Merge vào: main
- Sau khi done: `git pull origin main` trước, resolve nếu cần, rồi
  `git add . && git commit -m "feat: add GPT-4.1 as alternative judge for F8/F9, feature-flagged [AA-351]" && git push`,
  tự `gh pr create` (KHÔNG tự merge)

Sau khi done:
- Paste PR link + bảng so sánh 3 model (Nova Pro/GPT-5.6-pending/GPT-4.1) về Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-351 title khớp bối cảnh trước khi post
  kết quả — không tự đổi status, không tự quyết đổi judge production.
