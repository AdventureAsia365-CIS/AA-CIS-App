# AA-445-02 — Build B4 + score_distinctiveness() + DFS mở rộng T2 + UI competitor

Task cho Claude Code: Build B4 + score_distinctiveness() + DFS mở rộng T2 + UI competitor
(AA-445-02)

Mục tiêu: 3 việc độc lập nhưng cùng phục vụ 1 mục đích (làm distinctiveness/DFS có tác dụng
thật). Nối tiếp STEP0 (`docs/claude_audit/AA-445-01-dfs-distinctiveness-step0-audit.md`) — đọc
lại report đó trước, đừng điều tra lại.

⚠️ Concurrency: dùng git worktree riêng (`git worktree add ../aa-445-02-worktree
feature/aa-445-02-build`) nếu có session khác đang chạy song song.

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: yes: feature/aa-445-02-distinctiveness-dfs-t2-build
Merge vào: main

Files cần đọc trước:
- `docs/claude_audit/AA-445-01-dfs-distinctiveness-step0-audit.md` — toàn bộ findings, không
  điều tra lại
- Linear AA-317 (comment) — thiết kế gốc `score_distinctiveness()`, code mẫu đầy đủ
- `aamc/corpus.py` (bản gốc `aa-marketing-v2`, nếu còn trong repo hoặc archive — dùng làm tham
  khảo triển khai, KHÔNG copy nguyên nếu không khớp kiến trúc hiện tại)
- `services/*/quarter.py` (N5) và `services/*/allocator.py` (N6) — 2 nơi đọc `distinctiveness`
  thật, xác nhận field type/format mong đợi trước khi viết `score_distinctiveness()`
- `api/routers/v1_tours.py:317-321` và `services/*/tenant_pipeline.py:152-154` — 2 call site cần
  sửa cho DFS T2
- `api/routers/v1_competitors.py` (AA-88) — API `/v1/competitors` đã có, đọc kỹ trước khi build
  UI mới gọi nó
- Migration 027 (`acp_silver_s2.competitor_inputs`) — schema thật

Context — quyết định đã chốt (23/08/2026):
1. `distinctiveness` CÓ người dùng thật (N5 30% trọng số, N6 hệ số nhân) — xây B4 có tác dụng
   ngay.
2. DFS mở rộng T2 — sửa đúng 2 call site đã xác định, không phải cả hệ thống.
3. Domain đối thủ — TÁI DÙNG `competitor_inputs` + `/v1/competitors` (AA-88) đã có sẵn, KHÔNG
   xây field mới trong BrandTab.tsx. Chỉ cần build UI portal mới gọi API cũ.
4. B4 fetch homepage — code path riêng (`requests.get`, best-effort), không tái dùng Apify.
5. Phân biệt rõ: đây là "DFS" = data fetch (`process_seo`), KHÔNG phải `DFS_INTENT_UNDERUSED`
   (check validate, ADR-2026-038 §5 đã từ chối mở rộng check đó sang T3 — không đụng vào).

Steps:

**1. Build `score_distinctiveness()` + B4 (CompetitorIndex)**
- Viết class/function `CompetitorIndex` theo thiết kế gốc AA-317: nhận list domain (từ
  `competitor_inputs` của tenant), fetch homepage (`requests.get`, best-effort — timeout ngắn,
  không chặn pipeline nếu fetch fail), lưu `phrases` (nội dung text đã fetch, dùng để so sánh).
- Viết `score_distinctiveness(text: str, idx: CompetitorIndex) -> str` — trả `MED` khi
  `idx.phrases` rỗng (giữ đúng hành vi gốc), refine khi có index thật.
- Xác nhận format output khớp đúng những gì N5 (`quarter.py`)/N6 (`allocator.py`) đang mong đợi
  đọc (kiểu dữ liệu, giá trị enum LOW/MED/HIGH hay số).
- Verify: chạy thử với 1 tenant có `competitor_inputs` thật (nếu có sẵn data) hoặc seed 1-2
  domain test — xác nhận không còn trả MED cứng, có phân biệt HIGH/LOW thật dựa trên nội dung.

**2. DFS mở rộng T2**
- Sửa `v1_tours.py:317-321` và `tenant_pipeline.py:152-154` — truyền `seo_data` thật vào
  `_rewrite_tour()` thay vì để mặc định `None`/`{}`, theo đúng cách A1 đang truyền.
- KHÔNG đụng vào `DFS_INTENT_UNDERUSED` (check validate) — chỉ sửa phần data fetch.
- Verify: chạy 1 T2 rewrite thật, xác nhận `seo_data` không còn rỗng trong log/output.

**3. UI competitor portal (tenant nhập domain đối thủ)**
- Trang mới trong portal (`/portal/t0-brand` hoặc trang riêng — quyết định theo route convention
  hiện có, có thể là tab con trong Brand Identity vì đây là dữ liệu cấu hình tenant tương tự) gọi
  API `/v1/competitors` đã có (GET/POST/PATCH/DELETE).
- UI đơn giản: list domain hiện có, thêm/xóa domain, hiển thị giới hạn max 10/country (theo API
  đã enforce).
- Verify: thêm 1 domain test qua UI thật, xác nhận ghi đúng vào `competitor_inputs`, xóa được,
  giới hạn max 10 hoạt động đúng.

Verify tổng:
- pytest suite hiện có: không regression.
- Chạy thử toàn chuỗi: thêm domain đối thủ qua UI mới → B4 fetch → `score_distinctiveness()`
  trả giá trị khác MED cho ít nhất 1 atom test → N5/N6 đọc được giá trị mới (log hoặc query trực
  tiếp xác nhận).

Sau khi done:
- Lưu CHÍNH file task prompt này vào
  `docs/claude_tasks/AA-445-02-build-distinctiveness-dfs-t2.md` trước khi bắt tay code.
- Lưu báo cáo thực thi vào
  `docs/implementation-notes/AA-445-02-distinctiveness-dfs-t2-build.md`.
- git commit + push, tạo PR, KHÔNG tự merge.
- Paste kết quả verify về Claude Chat.
- Linear AA-445: giữ nguyên status, Claude Chat verify qua comment trước khi đổi Done
  (ADR-2026-037).
