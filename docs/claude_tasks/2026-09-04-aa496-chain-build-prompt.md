# Build prompt — chuỗi issue độc lập, không liên quan T-series/atom (04/09/2026, phiên 3)

Nguồn: comment mới nhất trên Linear issue AA-496, đăng 04/09/2026 bởi nghiep pham quoc.
Lưu nguyên văn để tham chiếu trong suốt quá trình thực hiện chuỗi.

---

Nhóm này hoàn toàn độc lập với AA-525 (điều tra kiến trúc T5-T11 đang chạy song song) — chạy không cần chờ kết quả AA-525.

Giao Claude Code chạy **tuần tự, không dừng hỏi giữa chừng trừ khi ghi rõ**: AA-496 → AA-282 → AA-344 → AA-490 → AA-491 → AA-310 → AA-324 → AA-263 → AA-256 → AA-177 → AA-176 → AA-482. Mỗi issue tự STEP0 → build → live-verify thật → comment báo cáo trên đúng issue đó → sang issue kế. Không tự set Done — Claude Chat soát sau.

**Lưu nguyên văn prompt này vào `docs/claude_tasks/` trước khi bắt đầu issue đầu tiên.**

### 1. AA-496 — Bug 401 billing trên /portal
Theo đúng mô tả issue.

### 2. AA-282 — schema_versions gap migrations 043-050
Theo đúng mô tả issue. Thuần audit/fix ghi log, không đổi schema thật.

### 3. AA-344 — Upload History hiển thị rows_landed/rows_dropped
Theo đúng mô tả issue.

### 4. AA-490, AA-491 — 2 follow-up nhỏ (dedup dry_run + gỡ --ignore test)
Làm cùng lúc vì cùng vùng code (AA-488 gốc). Theo đúng mô tả từng issue.

### 5. AA-310 — ECS stopTimeout
Theo đúng mô tả issue.

### 6. AA-324 — Prompt caching vô hiệu qua acc1 satellite
STEP0 bắt buộc: xác nhận lại luồng gọi Bedrock hiện tại — AA-518 (Done) đã đổi sang 3-account trực tiếp (acc1/acc2/acc3), có thể đã tự giải quyết vấn đề "mọi call qua acc1 satellite" nêu trong issue gốc. Nếu đã tự giải quyết — báo cáo rõ, không cần build gì thêm, đề xuất Cancel.

### 7. AA-263 — Tách editor node khỏi validate_node trong S1 graph
Theo đúng mô tả issue (từ ADR-2026-020). STEP0 bắt buộc đọc kỹ: xác nhận graph S1 hiện tại còn đúng 7 node (generate→validate→llm_judge→brand_audit→flag_fix→revalidate→END) không, vì đã 2 tháng từ lúc issue tạo. Đây đụng production pipeline S1 (dùng chung A1+T2) — chạy full quy trình: STEP0 → CI → Deploy Dev → digest verify → UAT Preview → chờ Nghiệp merge tay vào main → Deploy Prod. KHÔNG tự merge.

### 8. AA-256 — Cost Explorer 3-account rollup
Theo đúng comment mới nhất trên issue (Option B, acc2 gọi sang acc1 + acc3). IAM/Infra vẫn KHÔNG auto-merge.

### 9. AA-177, AA-176 — Security scanning + safe rollout CI/CD
Theo đúng mô tả từng issue. Làm cùng lúc vì cùng thuộc CI/CD pipeline.

### 10. AA-482 — Landing page engine (ADR-2026-030)
Việc lớn nhất trong chuỗi, để cuối. Theo đúng mô tả issue + đọc ADR-2026-030 đầy đủ trước khi build. Nếu cần wireframe FE, đăng comment trước khi code theo đúng quy ước.

---

**Không đưa vào chuỗi này, xử lý riêng:**
- AA-254 — đã quyết giữ Backlog, không build
- AA-341 — cần Nghiệp quyết định 5 câu hỏi trước, không tự động được
- AA-522/523/524/525 — thuộc nhánh T5-T11, đóng băng chờ kết quả AA-525

Báo cáo evidence đầy đủ theo đúng chuẩn (browser/API/DB thật, không `/health` suông) trên từng issue tương ứng.
