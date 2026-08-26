# AA-445-01 — STEP0 investigate: DFS + score_distinctiveness()

Task cho Claude Code: STEP0 investigate — DFS + score_distinctiveness() (AA-445)

Mục tiêu: điều tra 4 câu hỏi để biết chính xác cần build gì trước khi soạn task build B4
(CompetitorIndex) + T0 intake + DFS mở rộng T1/T2. KHÔNG viết code, KHÔNG sửa gì — thuần
investigate.

⚠️ Lưu ý concurrency: nếu có Claude Code session khác đang chạy song song trên AA-CIS-App, dùng
git worktree riêng cho task này (`git worktree add ../aa-445-worktree
feature/aa-445-01-step0-dfs-investigate`), không làm trực tiếp trên thư mục chung — tránh lặp lại
sự cố mất uncommitted work đã xảy ra ở AA-444.

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: yes: feature/aa-445-01-step0-dfs-investigate (dùng worktree riêng, xem lưu ý trên)
Merge vào: main (không áp dụng phiên này — investigate only)

Files cần đọc trước:
- Linear AA-317 (đầy đủ, kể cả comment) — thiết kế B4 gốc đã chốt, đối chiếu
  `aa-marketing-v2::corpus.py::score_distinctiveness()`
- ADR-2026-038 mục 0.4 (Notion `3c3b8a41-ec5d-8123-911f-e0c308841e79`) — DFS mở rộng T2
- `docs/claude_audit/AA-439-05-*.md` (hoặc report tương ứng trong chuỗi AA-439 nói về DFS/T1/T2
  gap) — đã xác nhận T1/T2 chưa từng gọi DFS
- ADR-2026-021 (Notion, DFS_INTENT_UNDERUSED false-positive fix) — hiểu rõ cơ chế DFS hiện tại
  hoạt động thế nào ở A1 (admin tier), trước khi hỏi có mở rộng sang T2 được không
- `services/content_generation/graph.py` — nơi DFS check hiện chạy (theo ADR-2026-021 dòng
  446-462)
- N7 Produce code (từ AA-298/AA-368) — tìm chỗ đọc field `distinctiveness` nếu có
- N5 allocator (nếu tồn tại — xác nhận tên module thật qua grep, đừng giả định tên file)
- `frontend/*/BrandTab.tsx` (T0) — xem đã có field nào gần "domain đối thủ" chưa

Context:
- Thiết kế B4 đã chốt từ AA-317 (21/07): domain list tenant tự khai (`domains: list[str]`),
  fetch homepage trực tiếp (`requests.get`, best-effort). KHÔNG cần SERP-discovered rivals.
- `score_distinctiveness()` mặc định trả `MED` khi `CompetitorIndex.phrases` rỗng — hành vi CÓ
  CHỦ ĐÍCH, không phải bug.
- Câu hỏi chưa có lời đáp (ghi rõ trong AA-317, giờ mới điều tra): N7/N5 có thật sự đọc
  `distinctiveness` để quyết định gì (lọc/ưu tiên atom) hay chưa từng dùng tới field này.

Steps:

1. **Grep toàn repo tìm `distinctiveness`** — liệt kê MỌI nơi field này được đọc/ghi. Với mỗi
   chỗ đọc, xác định: có ảnh hưởng quyết định thật (lọc atom, chọn atom ưu tiên, gate pass/fail)
   hay chỉ hiển thị/log. Nếu N7/N5 chưa từng đọc field này, nói rõ — đó là finding quan trọng
   (nghĩa là B4 hiện tại 0% có tác động, xây xong cũng chưa ai dùng).

2. **Grep DFS call site hiện tại** (`score_dfs`, `dfs_relevance`, hoặc tên hàm thật trong
   `graph.py`) — liệt kê đầy đủ nơi đang gọi (chắc chắn có ở A1/admin tier), xác nhận T1/T2
   (tenant rewrite) có gọi hay không. Nếu không, xác định chính xác cần thêm gọi ở đâu (function
   nào, node nào trong LangGraph flow) để mở rộng sang T2.

3. **Đọc `BrandTab.tsx` (T0) + schema `brand_identity`** — xác nhận có cột/field nào gần giống
   "danh sách domain đối thủ" chưa. Nếu chưa, cần thêm 1 field mới (không cần bảng mới — có thể
   thêm cột JSON hoặc mảng trong bảng `brand_identity` đã có, xác nhận qua schema thật).

4. **Đọc lại cách S2 dùng DataForSEO/Apify** (competitor research stage đã có) — xác định 2 khả
   năng: (a) B4 tái dùng service/client đã có cho S2, chỉ đổi input là domain tenant tự khai; hay
   (b) B4 cần code path hoàn toàn riêng vì mục đích khác (S2 là research/SEO keyword, B4 là fetch
   homepage nội dung để so sánh distinctiveness — có thể khác bản chất). Đọc code thật, đừng suy
   đoán từ tên.

5. **Tổng hợp và đề xuất scope cho task build tiếp theo** — không tự quyết định kiến trúc, chỉ
   liệt kê phương án nếu có điểm cần quyết định (giống cách AA-436/AA-437 STEP0 đã làm). Đặc biệt
   nêu rõ nếu finding ở bước 1 cho thấy N7/N5 chưa từng dùng `distinctiveness` — vì điều đó ảnh
   hưởng độ ưu tiên thật của cả task này (xây B4 trước khi có nơi dùng thật sẽ không có tác dụng
   ngay).

Verify: không cần verify code — verify là bằng chứng thật cho từng finding (grep output, code
path thật, dòng code cụ thể).

Sau khi done:
- Lưu CHÍNH file task prompt này vào `docs/claude_tasks/AA-445-01-step0-dfs-investigate.md`
  trước khi bắt tay điều tra.
- Lưu báo cáo investigate vào
  `docs/claude_audit/AA-445-01-dfs-distinctiveness-step0-audit.md`.
- Paste tóm tắt kết quả về Claude Chat.
- Linear AA-445: giữ nguyên status Backlog — Claude Chat sẽ đọc báo cáo, quyết định kiến trúc
  cùng Nghiệp, rồi soạn task build riêng (AA-445-02).
