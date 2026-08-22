## Task cho Claude Code: Kiểm tra cách DFS đang được dùng THẬT trong code hiện tại (A1/T2) — phục vụ thiết kế score_distinctiveness() kết hợp

Mục tiêu: Trước khi Nghiệp/Claude Chat chốt công thức kết hợp distinctiveness + DFS relevance thành 1 điểm cho atom, cần biết DFS đang được gọi ở CẤP ĐỘ NÀO trong hệ thống hiện tại (từ khóa/tour/khác), tần suất, chi phí, và dữ liệu output thật trông ra sao — để công thức thiết kế dựa trên thực tế vận hành, không phải suy đoán.

Repo: AA-CIS-App
Branch: feature/aa-439-tenant-tier-audit (đã tồn tại — checkout, KHÔNG tạo branch mới, KHÔNG push, KHÔNG PR).

## Cần làm

1. Đọc `services/seo_intelligence/dataforseo_client.py` (đã nhắc ở AA-438-01, DFS = DataForSEO xác nhận) — liệt kê TOÀN BỘ method/endpoint DFS đang gọi thật (search_volume, SERP, keyword_suggestions, keyword_difficulty, content_parsing, v.v.) — cấp độ nào (theo keyword đơn, theo domain, theo cả trang)?
2. Đọc `services/seo_intelligence/seed_builder.py` (nhắc ở AA-438-01: `build_seed`, dùng trong A1 rewrite) — DFS được gọi ở cấp TOUR (1 lần/tour) hay cấp TỪ KHÓA (nhiều lần/tour, mỗi từ khóa 1 lần)? Trích code cụ thể.
3. Query dev DB hoặc log thật: DFS đã được gọi bao nhiêu lần trong 30 ngày qua (nếu có log/usage table), chi phí ước tính nếu biết (theo giá DataForSEO hiện tại nếu tìm được qua tài liệu chính thức DataForSEO — hoặc chỉ đếm số lần gọi nếu không có giá).
4. Xác nhận: dữ liệu DFS hiện tại (search_volume, v.v.) có được LƯU LẠI (persist) ở đâu không, hay chỉ dùng 1 lần lúc rewrite rồi bỏ? Nếu có lưu, bảng nào, có thể truy vấn lại theo tour/keyword sau này không (quan trọng — nếu đã lưu, không cần gọi lại DFS để tính atom score).
5. Có `keyword_difficulty` field thật trong response DataForSEO client hiện tại không (AA-439-04 đã lưu ý reference implementation cũ KHÔNG có field này, nhưng client thật của AA-CIS-App có thể khác — xác nhận).
6. Ước tính: nếu phải gọi DFS RIÊNG cho từng atom (không dùng chung dữ liệu tour), với ~2500 atom hiện có + tốc độ tích lũy ~150-300 atom/tenant/tháng (theo AA-439-03) — số lượng API call phát sinh thêm là bao nhiêu, có đáng lo về chi phí/rate limit không (so với cách dùng chung dữ liệu DFS đã có ở cấp tour).

## Output

Báo cáo ngắn, tập trung dữ kiện thật (không đề xuất công thức, không quyết định thiết kế — chỉ cung cấp dữ kiện vận hành để Claude Chat/Nghiệp quyết định giữa "DFS riêng theo atom" vs "dùng chung DFS của tour"):
- Cấp độ DFS hiện gọi (tour hay keyword), tần suất, có lưu lại không.
- Ước tính chi phí/khối lượng nếu mở rộng gọi theo atom.
- Field nào thực tế có sẵn trong response DFS client thật (không phải reference implementation cũ).

Sau khi done:
- Viết báo cáo vào `docs/claude_audit/AA-439-05-dfs-usage-pattern-audit.md`.
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-439-05-audit-dfs-usage.md`.
- git commit trên branch `feature/aa-439-tenant-tier-audit` — KHÔNG push, KHÔNG PR.
- Comment tóm tắt lên Linear AA-439.
- Paste nội dung báo cáo về Claude Chat.
