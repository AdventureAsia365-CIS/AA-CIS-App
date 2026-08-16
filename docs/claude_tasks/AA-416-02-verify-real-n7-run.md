## Task cho Claude Code: AA-416 — verify bằng N7 run thật, xác nhận hết ALB timeout

Mục tiêu: PR #174 (AA-416 — bọc Bedrock call bằng asyncio.to_thread) đã merge + deploy Dev
thành công, unit test + digest verify pass. Task này CHỈ verify bằng N7 run thật — xác
nhận health-check KHÔNG còn bị timeout xuyên suốt (khác 4 lần tái diễn trước đó).

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: no (chỉ trigger run + theo dõi + ghi report, không code)

BƯỚC 0: lưu file task prompt này vào `docs/claude_tasks/AA-416-02-verify-real-n7-run.md`.

Context:
- 4 lần ALB health-check timeout đã xảy ra trước fix (AA-416), lần gần nhất quan sát trực
  tiếp `/health` tự trả 504 ngay trước khi ECS đánh dấu task unhealthy.
- Fix đã deploy: ECS task def :105, digest khớp merge commit 3331dae.
- Test tải trong PR #174 đã chứng minh `/health` phản hồi ổn định khi giả lập N7 chạy —
  nhưng đây là task VERIFY THẬT bằng traffic Bedrock thật, không phải giả lập.

Steps:
1. Kiểm tra Run History trước, chọn 1 tuần CHƯA từng chạy (tránh trùng).
2. Trigger N7 production run thật qua `/admin/produce` cho tenant Adventure Asia Internal.
3. Trong SUỐT thời gian run (dự kiến 30-40 phút), theo dõi liên tục:
   a. `GET .../health` từ bên ngoài — ghi lại response time mỗi vài phút, xác nhận không
      timeout, không trả 504.
   b. `aws ecs describe-tasks` — xác nhận task KHÔNG bị replace/kill giữa chừng (so với 4
      lần trước đều bị kill).
   c. Trạng thái run qua `GET .../produce/run/{id}` — xác nhận hoàn thành liên tục, không
      bị gián đoạn cần re-POST như 4 lần trước.
4. Nếu health-check VẪN timeout hoặc task VẪN bị kill — đây là dấu hiệu fix chưa đủ (có
   thể còn điểm gọi Bedrock đồng bộ khác chưa được bọc `asyncio.to_thread`) — ghi rõ chi
   tiết (thời điểm, log), KHÔNG tự sửa thêm trong task này, báo lại trước.
5. Đọc gate_ledger của run — ghi lại F1/F8/F9 pass rate (tham khảo, không phải mục tiêu
   chính của task này, nhưng dữ liệu hữu ích cho AA-404/AA-382 đang mở song song).

Verify:
1. Kết luận rõ ràng: 0/1 hay N/1 lần ALB timeout xảy ra trong run này — so với 4/4 lần
   trước đó luôn xảy ra.
2. Nếu 0/1 — đây là xác nhận mạnh nhất fix đã hoạt động đúng, đề xuất đóng AA-416 (không
   tự đổi status).
3. Lưu report đầy đủ (timeline health-check, task status xuyên suốt, kết luận) vào
   `docs/implementation-notes/AA-416-verify-real-run.md`.

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Không tạo branch/PR code — chỉ commit report qua
  `git pull origin main && git add docs/implementation-notes/AA-416-verify-real-run.md docs/claude_tasks/AA-416-02-verify-real-n7-run.md && git commit -m "docs: AA-416 real N7 run verification [AA-416]" && git push`

Sau khi done:
- Paste kết luận (0/1 hay N/1 timeout) + timeline về Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-416 title khớp bối cảnh trước khi post
  kết quả — không tự đổi status (đã Done qua auto-flip, chỉ xác nhận thêm bằng comment).
