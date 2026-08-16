# Task prompt: AA-382 — repair_fn cần đủ rubric context cho gate LLM-judged (F8/F9)

(Saved verbatim per Step 0, before any code changes.)

## Mục tiêu
Khi F8/F9 (LLM-judge) fail, `repair_fn` hiện chỉ nhận violation string ngắn (VD
"tone không đúng brand") để sửa — không đủ context để LLM sửa đúng hướng, dẫn tới hiện
tượng nhiều vòng repair flag cụm từ khác nhau, không hội tụ (ghi nhận trong AA-404, N7 run
thật). Mở rộng để repair_fn nhận đủ RUBRIC ĐẦY ĐỦ (không chỉ câu vi phạm ngắn) khi sửa
theo F8/F9.

## Repo / Branch
- Repo: AA-CIS-App
- Branch hiện tại: main
- Tạo branch mới: yes — `feature/aa-382-repair-rubric-context`
- Merge vào: main

## LƯU Ý QUAN TRỌNG — chạy song song với 2 task khác cùng lúc (AA-415-03, AA-351)
Nghiệp đang chạy AA-415-03 (`fix: reserve repair budget slot...`) và AA-351 (khảo sát GPT
trên Bedrock) trên các Claude Code session KHÁC, cùng lúc với task này. Cả 3 không đụng
chung file (AA-415-03 sửa `compute_repair_budget()`, task này sửa cách build prompt repair
cho F8/F9, AA-351 chỉ khảo sát không code) — nhưng PHẢI tự `git pull origin main` trước khi
tạo branch VÀ trước khi push, vì main có thể đã nhận PR #170-series mới trong lúc bạn làm.
Nếu phát hiện conflict thật khi rebase/merge, DỪNG lại, báo rõ cho Nghiệp thay vì tự ý giải
quyết bằng cách ghi đè.

## BƯỚC 0
Lưu file task prompt này vào `docs/claude_tasks/AA-382-01-repair-rubric-context.md` commit
riêng đầu tiên trước khi code. (this file)

## Files cần đọc trước
- `services/acp_produce/repair.py` — hàm `repair_fn` (hoặc tên tương đương xử lý repair
  loop), đặc biệt cách build prompt gửi LLM khi sửa theo F8/F9. Đọc kỹ để không phá các
  fix gần đây từ AA-415 (PieceInvariants, atom_text_by_id) — có thể đang chạy song song.
- Rubric F8 (framework — hook/CTA/emotion) và F9 (brand/SEO audit) — tìm định nghĩa đầy đủ
  rubric ở đâu (constant, config file, hay prompt template riêng) — đây chính là phần cần
  đưa vào repair prompt, không chỉ trích 1 câu violation.
- `docs/claude_audit/AA-404-n7-run6-results.md` — bằng chứng cụ thể "3 vòng repair flag
  cụm từ khác nhau, không hội tụ" cho F9_brand_seo_audit_social.

## Context
- Đã xác nhận qua Run History thật: F9 gần như không bao giờ pass (0/3-0/6 across nhiều
  tuần) — không phải regression, là gap chưa từng giải quyết dứt điểm.
- Giả thuyết root cause (chưa chứng minh 100%, cần verify trong lúc code): khi F8/F9 fail,
  hệ thống hiện chỉ trích xuất 1 câu/violation string ngắn (VD từ JSON response của judge:
  `"failure_codes": ["GENERIC_AI_WORDING"]` kèm 1-2 câu note) để đưa vào prompt repair —
  KHÔNG kèm theo toàn bộ rubric gốc (định nghĩa đầy đủ brand voice, tiêu chí chấm) mà judge
  dùng để chấm. LLM sửa dựa trên câu note ngắn dễ đoán sai hướng, sửa xong lại phạm lỗi
  khác trong cùng rubric mà nó không biết tới.

## Steps
1. Xác nhận đúng giả thuyết trên bằng cách đọc code thật — nếu sai, ghi lại phát hiện thật
   và điều chỉnh hướng fix cho phù hợp (không cố ép theo giả thuyết nếu code cho thấy khác).
2. Sửa để prompt repair cho F8/F9 luôn kèm: (a) toàn bộ rubric gốc (không chỉ đoạn liên
   quan tới violation), (b) violation cụ thể bị flag lần này, (c) nếu có, ví dụ good/bad
   cụ thể từ rubric (tương tự cách F9 blog đã có "concrete good/bad anchor" từ PR #155 —
   kiểm tra xem F9_social và F8 có thiếu phần này không).
3. Không đổi logic judge F8/F9 (cách chấm điểm) — chỉ đổi INPUT mà repair prompt nhận được.
4. Cân nhắc token cost tăng thêm khi rubric đầy đủ dài hơn nhiều so với violation string
   ngắn — ước tính mức tăng, ghi vào report (liên quan AA-418 cost tracking, không cần
   code đo cost ở đây, chỉ ước tính bằng lời qua số token trước/sau).

## Verify
1. Chạy N7 thật 1 tuần MỚI (chưa từng chạy, kiểm tra Run History trước để tránh trùng) —
   so sánh F8/F9 pass rate với baseline gần nhất (0/3-0/6 tuỳ tuần).
2. Đọc held_reason của piece còn fail sau fix — xác nhận có còn hiện tượng "flag cụm từ
   khác nhau mỗi vòng, không hội tụ" không, hay giờ đã hội tụ về đúng 1 vấn đề cụ thể.
3. `pytest` / unit test liên quan pass sạch.
4. Deploy Dev qua CI, verify ECS digest khớp `:latest`.
5. Lưu report vào `docs/implementation-notes/AA-382-repair-rubric-context.md` — bao gồm
   số liệu trước/sau, ước tính token cost tăng thêm.

## Git context
- Repo: AA-CIS-App
- Current branch: main
- Tạo branch mới: yes — feature/aa-382-repair-rubric-context
- Merge vào: main
- Sau khi done: `git pull origin main` trước, resolve nếu cần, rồi
  `git add . && git commit -m "fix: pass full rubric context to F8/F9 repair prompt [AA-382]" && git push`,
  tự `gh pr create` (KHÔNG tự merge)

## Sau khi done
- Paste PR link + kết quả verify (F8/F9 pass rate trước/sau) về Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-382 title khớp bối cảnh trước khi post
  comment — không tự đổi status.
