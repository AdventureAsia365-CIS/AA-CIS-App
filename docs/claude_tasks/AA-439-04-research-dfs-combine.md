## Task cho Claude Code: Đọc sâu aa-marketing-v2 để thiết kế score_distinctiveness() kết hợp DFS — CHỈ ĐỌC, KHÔNG thiết kế/code

Mục tiêu: AA-439-03 đã đọc `CONTEXT.md`/`README.md`/`aamc/corpus.py` và xác nhận `distinctiveness` gốc chỉ dựa vào so sánh đối thủ cạnh tranh (token-overlap), KHÔNG dùng DFS. Nghiệp muốn xem xét hướng KẾT HỢP distinctiveness (so đối thủ) VÀ DFS (relevance/search-volume) thành 1 điểm số duy nhất, hoặc 2 trục điểm riêng — nhưng TRƯỚC KHI tự thiết kế, cần đọc kỹ TOÀN BỘ folder `aa-marketing-v2` (không chỉ 3 file đã đọc ở AA-439-03) xem chị Thư (tác giả tài liệu gốc) đã từng đề cập ý tưởng kết hợp này ở đâu chưa — tránh phát minh lại hoặc đi ngược thiết kế gốc.

Repo: AA-CIS-App
Branch: feature/aa-439-tenant-tier-audit (đã tồn tại — checkout, KHÔNG tạo branch mới, KHÔNG push, KHÔNG PR).

**QUAN TRỌNG: Đây là task ĐỌC THUẦN, không thiết kế giải pháp, không viết code, không đề xuất implementation cụ thể.** Chỉ trả lời: tài liệu gốc nói gì về việc kết hợp DFS + distinctiveness (nếu có), và nếu không có, các mảnh thông tin rời rạc nào trong tài liệu có thể liên quan.

## Việc cần làm

1. Liệt kê TOÀN BỘ file trong `docs/AI-gent-for automation works/aa-marketing-v2/` (dùng `find`/`ls -la`, không chỉ 3 file đã đọc trước — có thể có file khác chưa đọc: spec khác, code khác, note khác, xlsx, v.v.).
2. Đọc TOÀN BỘ các file chưa từng đọc ở AA-439-03 (đã đọc: `CONTEXT.md`, `README.md`, `aamc/corpus.py`) — đặc biệt tìm:
   - Bất kỳ đoạn nào nhắc cả "distinctiveness" VÀ "DataForSEO"/"DFS" trong CÙNG 1 câu/đoạn/công thức.
   - Bất kỳ công thức tính điểm atom nào có nhiều thành phần (không chỉ competitor-overlap).
   - Bất kỳ phần nào nói về "combined score", "weighted score", "priority score" cho atom.
3. Grep toàn bộ folder cho các từ khóa: `dataforseo`, `dfs`, `search_volume`, `keyword`, `distinctiveness`, `relevance`, `priority_score`, `combined` — liệt kê MỌI kết quả, kể cả không chắc liên quan.
4. Nếu tìm thấy ý tưởng kết hợp — trích dẫn NGUYÊN VĂN đoạn đó, không diễn giải/tóm tắt làm mất chi tiết công thức.
5. Nếu KHÔNG tìm thấy — xác nhận rõ ràng "không có, đây sẽ là thiết kế mới, không dựa trên tài liệu gốc nào" — để Nghiệp biết đây là quyết định cần tự đưa ra, không phải khôi phục ý tưởng có sẵn.
6. Xem lại `CONTEXT.md` §5 Module C (Research & Briefs, đã trích 1 phần ở AA-439-03) — đọc kỹ TOÀN BỘ module này (không chỉ đoạn đã trích), xem DFS's `keyword_research`/`serp_read` có field/output nào (search_volume, keyword_difficulty, v.v.) có thể tái sử dụng làm 1 trục điểm cho atom hay không — dù tài liệu không nói trực tiếp "dùng cho atom scoring", nhưng nếu có dữ liệu sẵn dùng được, ghi chú lại.

## Output

Báo cáo ngắn gọn, tập trung:
- Danh sách đầy đủ file trong folder (bước 1).
- Trích dẫn nguyên văn mọi đoạn liên quan tìm được (bước 2-4).
- Kết luận rõ: CÓ hay KHÔNG có ý tưởng kết hợp trong tài liệu gốc.
- Nếu không có, liệt kê các "nguyên liệu" rời rạc có thể dùng (VD: DFS output fields nào tồn tại và có thể tái dùng) để Nghiệp/Claude Chat tự thiết kế công thức kết hợp sau.

KHÔNG đề xuất công thức, KHÔNG viết code, KHÔNG quyết định thiết kế — chỉ báo cáo những gì tài liệu gốc thực sự nói.

Sau khi done:
- Viết báo cáo vào `docs/claude_audit/AA-439-04-dfs-distinctiveness-combine-research.md`.
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-439-04-research-dfs-combine.md`.
- git commit trên branch `feature/aa-439-tenant-tier-audit` — KHÔNG push, KHÔNG PR.
- Comment tóm tắt lên Linear AA-439.
- Paste nội dung báo cáo về Claude Chat.
