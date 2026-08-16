# Task cho Claude Code: AA-416 — fix event loop blocking bằng asyncio.to_thread

Mục tiêu: ECS task chạy N7 bị ALB health-check timeout (4 lần tái diễn, quan sát trực tiếp
`/health` tự trả 504) vì Bedrock call đồng bộ (`boto3`) chặn event loop dùng chung với API
serving. Fix bằng cách bọc các lệnh gọi Bedrock đồng bộ trong thread pool riêng
(`asyncio.to_thread`), KHÔNG tách hạ tầng ECS (đã quyết định hướng nhanh/ít rủi ro trước).

Repo: AA-CIS-App
Branch hiện tại: main (verify bằng `git branch --show-current`)
Tạo branch mới: yes — `feature/aa-416-async-to-thread-bedrock`
Merge vào: main

**LƯU Ý — có thể chạy song song với AA-351-02 (thử GPT-5.6 làm judge) trên session Claude
Code khác.** 2 task có khả năng ĐỤNG CHUNG file `invoke_judge()`/`invoke_claude()` trong
`shared/llm_client/` — PHẢI `git pull origin main` trước khi tạo branch và trước khi push.
Nếu AA-351-02 đã merge trước và đổi cùng hàm, rebase cẩn thận, không ghi đè logic đổi model
của AA-351-02. Nếu conflict thật sự phức tạp, DỪNG và báo Nghiệp — không tự quyết ưu tiên
bên nào.

BƯỚC 0: lưu file task prompt này vào `docs/claude_tasks/AA-416-01-fix-event-loop-blocking.md`
commit riêng đầu tiên trước khi code.

Files cần đọc trước:
- `docs/claude_audit/AA-418-parallel-cost-investigation.md` — bằng chứng đo được: 1 lệnh
  repair thật chặn event loop 13.8 giây, xác nhận `invoke_claude()`/`invoke_judge()` dùng
  boto3 đồng bộ thật.
- `shared/llm_client/client.py` và `shared/llm_client/bedrock_satellite.py` — nơi định
  nghĩa các hàm gọi Bedrock (`invoke_claude`, `invoke_judge`).
- `services/acp_produce/repair.py` và node generate/repair trong graph N7 — nơi các hàm
  trên được gọi trong vòng lặp repair.
- Health check endpoint (`/health`) — xác nhận route nào, chạy trên cùng event loop nào
  với N7 BackgroundTask.

Context:
- ECS chỉ chạy 1 task duy nhất, chia sẻ event loop giữa API serving (bao gồm `/health`) và
  N7 BackgroundTask (chạy generate/repair). Khi Bedrock call đồng bộ block thread chính,
  ALB health probe bị xếp hàng chờ, timeout, ECS kill+replace task giữa chừng — 4 lần tái
  diễn đã quan sát (gần nhất: `/health` tự trả 504 ngay trước khi ECS đánh dấu unhealthy).
- Cost KHÔNG đổi khi bọc bằng to_thread (cost theo token, không theo cách gọi) — chỉ đổi
  cách execute, không đổi model/request.

Steps:
1. Xác định TẤT CẢ điểm gọi Bedrock đồng bộ trong luồng N7 (generate, repair F1-F9, judge
   F8/F9) — liệt kê đầy đủ trước khi sửa, không bỏ sót điểm nào.
2. Bọc mỗi lệnh gọi boto3 đồng bộ bằng `asyncio.to_thread(sync_fn, *args)` (Python 3.9+) —
   giữ nguyên logic bên trong, chỉ đổi cách execute từ "gọi trực tiếp trong event loop
   chính" sang "chạy trong thread pool riêng, không chặn event loop chính".
3. Kiểm tra xem có shared state nào (VD connection, session boto3 client) không thread-safe
   khi nhiều call chạy đồng thời trong thread pool không — nếu vòng lặp vẫn tuần tự (không
   đổi sang concurrent), rủi ro này thấp nhưng vẫn cần xác nhận rõ.
4. Không đổi logic retry/timeout hiện có của các hàm Bedrock — chỉ đổi cách gọi.
5. Xác nhận `/health` endpoint có phải cũng là async route không — nếu đúng, xác nhận nó
   giờ trả lời được ngay cả khi N7 đang chạy repair loop dài.

Verify:
1. Unit test hiện có pass sạch (`pytest`).
2. Test tải: khi N7 đang chạy 1 repair loop dài (giả lập hoặc dùng piece thật), gọi
   `/health` liên tục từ bên ngoài — xác nhận response time ổn định (không bị block 13+
   giây như trước), không timeout.
3. Chạy N7 thật 1 tuần MỚI (kiểm tra Run History trước để chọn tuần chưa chạy) — theo dõi
   xuyên suốt run, xác nhận ALB health-check KHÔNG bị timeout, ECS task KHÔNG bị kill giữa
   chừng (khác với 4 lần trước).
4. Deploy Dev qua CI, verify ECS digest khớp `:latest`.
5. Lưu report (bao gồm bằng chứng health-check ổn định trong lúc N7 chạy) vào
   `docs/implementation-notes/AA-416-fix-event-loop-blocking.md`.

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Tạo branch mới: yes — feature/aa-416-async-to-thread-bedrock
- Merge vào: main
- Sau khi done: `git pull origin main` trước, resolve nếu cần, rồi
  `git add . && git commit -m "fix: wrap synchronous Bedrock calls in asyncio.to_thread to stop blocking event loop [AA-416]" && git push`,
  tự `gh pr create` (KHÔNG tự merge)

Sau khi done:
- Paste PR link + bằng chứng health-check ổn định trong lúc N7 chạy về Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-416 title khớp bối cảnh trước khi post
  comment kết quả — không tự đổi status. Nếu N7 run thật xác nhận không còn ALB timeout
  (0/1 thay vì 4 lần tái diễn trước đó), đề xuất đóng — để Nghiệp quyết.
