# Task cho Claude Code: AA-404 — phân tích định lượng nguyên nhân F9 fail, chuẩn bị thảo luận rubric với Ms. Thư

Mục tiêu: F9 (brand/SEO audit) gần như không bao giờ pass qua toàn bộ lịch sử N7 run
(nhiều tuần, tích luỹ 15+ piece qua AA-351-05/06). Đã thử 2 hướng kỹ thuật không đổi được
kết quả: (1) AA-382 thêm rubric context đầy đủ vào repair prompt — không cải thiện pass
rate; (2) AA-351 đổi hẳn judge model (Nova Pro → GPT-4.1) — GPT-4.1 lại gần như luôn pass,
nghi đang chấm dễ dãi hơn là đúng hơn. Cả 2 kết quả cùng gợi ý vấn đề nằm ở CHÍNH RUBRIC F9,
không phải judge hay writer prompt. Task này KHÔNG sửa code — phân tích định lượng dữ liệu
đã có để chuẩn bị thảo luận cụ thể với Ms. Thư (tác giả gốc rubric).

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: no (phân tích, không code)

BƯỚC 0: lưu file task prompt này vào `docs/claude_tasks/AA-404-01-f9-failure-pattern-analysis.md`.

Files/dữ liệu cần đọc:
- Toàn bộ held_reason F9 thật đã tích luỹ qua các N7 run — query trực tiếp DB (ECS Exec,
  S3-mediated pattern, xem skill `aa-cis-schema`) từ `acp_deliver.pieces` hoặc bảng gate
  ledger tương ứng — LẤY DỮ LIỆU THẬT, không dùng lại số liệu tóm tắt trong các report cũ
  (`docs/implementation-notes/AA-382-repair-rubric-context.md`,
  `docs/implementation-notes/AA-351-gpt41-judge-trial.md`,
  `docs/implementation-notes/AA-351-gpt41-multiround-real-n7.md`,
  `docs/claude_audit/AA-404-n7-run6-results.md`) — các report này có thể chỉ trích mẫu,
  cần full dataset.
- Rubric F9 gốc (`FRAMEWORK_RUBRICS` hoặc constant tương đương cho F9 brand/SEO, cả bản
  blog và social) — đọc kỹ định nghĩa từng tiêu chí.
- Nếu có, bản gốc rubric của Ms. Thư trước khi port sang code (tìm trong
  `docs/`, hoặc tham chiếu `aa-marketing-v2/aamc/` nếu còn trong repo) để so sánh xem tiêu
  chí nào là NGUYÊN BẢN Ms. Thư viết, tiêu chí nào là bổ sung sau này (AA-372, code mới,
  "chưa từng có data thật để hiệu chỉnh").

Steps:
1. Tổng hợp TOÀN BỘ piece đã fail F9 qua lịch sử (không chỉ 15 piece gần nhất) — với mỗi
   piece: failure_codes (VD GENERIC_AI_WORDING, SUMMARY_OFF_BRAND, BODY_EXPERIENCE_DETAILS_
   TOO_GENERIC...), flagged_phrases cụ thể, channel (blog/facebook/tiktok).
2. Đếm tần suất từng failure_code — xác định 2-3 tiêu chí gây fail NHIỀU NHẤT (không phải
   liệt kê hết, tập trung vào cái chiếm tỷ trọng lớn).
3. Với tiêu chí gây fail nhiều nhất — đọc kỹ 5-10 flagged_phrases THẬT bị gắn cờ, đánh giá
   khách quan: các câu này có thực sự "generic/off-brand" theo cách người đọc thường sẽ
   đồng ý, hay đây là judgment call mơ hồ mà người khác đọc có thể không đồng ý? (Claude Code
   tự đưa quan điểm, không chỉ báo cáo trung lập — nhưng phải trích dẫn câu thật để Nghiệp
   tự đánh giá lại).
4. So sánh: tiêu chí nào là bản gốc Ms. Thư viết (từ trước AA-372) vs tiêu chí social/mới
   bổ sung sau (chưa có data thật để hiệu chỉnh khi viết, theo ghi chú trong AA-404 gốc) —
   giả thuyết: tiêu chí MỚI có khả năng mơ hồ/quá khắt khe hơn vì chưa được hiệu chỉnh qua
   dữ liệu thật, cần XÁC NHẬN hay BÁC BỎ giả thuyết này bằng số liệu.
5. Tính tỷ lệ fail theo channel (blog vs facebook vs tiktok) — xem có channel nào bị nặng
   hơn hẳn không, đây có thể là gợi ý rubric social cần tách biệt rõ hơn khỏi rubric blog.
6. KHÔNG đề xuất sửa rubric trong task này — chỉ phân tích, trình bày dữ liệu khách quan +
   quan sát để Nghiệp mang ra thảo luận với Ms. Thư.

Verify:
1. Số liệu phải TRÍCH XUẤT THẬT từ DB, không suy diễn từ report cũ.
2. Report cuối phải có: (a) bảng tần suất failure_code, (b) 5-10 ví dụ flagged_phrases thật
   kèm nhận định, (c) so sánh gốc vs mới, (d) tỷ lệ theo channel, (e) 2-3 câu hỏi CỤ THỂ nên
   hỏi Ms. Thư (không phải "rubric có ổn không" chung chung — VD "tiêu chí X có ý định thật
   là Y hay chỉ là ví dụ minh hoạ, không phải rule cứng?").
3. Lưu report vào `docs/claude_audit/AA-404-f9-rubric-failure-analysis.md`.

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Chỉ commit report:
  `git pull origin main && git add docs/claude_audit/AA-404-f9-rubric-failure-analysis.md docs/claude_tasks/AA-404-01-f9-failure-pattern-analysis.md && git commit -m "docs: AA-404 F9 rubric failure pattern analysis, quantitative [AA-404]" && git push`

Sau khi done:
- Paste báo cáo đầy đủ (bảng tần suất + ví dụ cụ thể + câu hỏi đề xuất cho Ms. Thư) về
  Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-404 title khớp bối cảnh — không tự đổi
  status, đây là phân tích chuẩn bị, không phải fix.
