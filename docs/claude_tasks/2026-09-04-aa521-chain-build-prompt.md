# Build prompt — chuỗi 6 issue tuần tự (04/09/2026)

Nguồn: Linear AA-521, comment 2026-09-04T01:36:57.088Z, tác giả nghiep pham quoc.
Lưu nguyên văn (nguyên bản tiếng Việt) trước khi bắt đầu issue đầu tiên, theo đúng yêu cầu của comment.

---

Giao Claude Code chạy **tuần tự, không dừng hỏi giữa chừng**: AA-521 → AA-256 → AA-257 → AA-254 → AA-489 → AA-462. Mỗi issue tự STEP0 → (wireframe nếu có FE, đăng comment trước khi code) → build → live-verify thật → comment báo cáo trên đúng issue đó → sang issue kế. Không tự set Done — Claude Chat soát sau.

**Lưu nguyên văn prompt này vào `docs/claude_tasks/` trước khi bắt đầu issue đầu tiên.**

---

### 1. AA-521 — Admin logout httpOnly cookie
Theo đúng mô tả issue: tạo `/api/auth/admin-logout` mirror `/api/auth/tenant-logout` (AA-427), đổi sidebar `logout()` gọi route mới, verify sau logout gọi endpoint admin bất kỳ → 307/401 ngay lập tức.

### 2. AA-256 — AWS Cost Explorer integration
Theo đúng mô tả issue. **Trước khi build: kiểm tra IAM role/profile hiện tại đã có quyền `ce:GetCostAndUsage` chưa** (`aws iam get-role-policy` / simulate-principal-policy). Nếu CHƯA có quyền — đây là thay đổi IAM, theo đúng quy ước Infra repo: KHÔNG tự thêm quyền mới qua Terraform auto-merge. Dừng đúng issue này, comment rõ cần cấp quyền gì, chuyển sang issue kế tiếp (AA-257), quay lại AA-256 sau khi Nghiệp xác nhận đã cấp quyền hoặc tự cấp qua console.

### 3. AA-257 — Live infra state endpoint
Theo đúng mô tả issue (`GET /admin/infra/status`, cache 60s).

### 4. AA-254 — Ops diagnosis panel
**STEP0 bắt buộc theo đúng 4 điểm đã ghi trong issue** trước khi lock design (tab Health hiện render gì, log driver CloudWatch, schema `pipeline_jobs` thật, volume job failed gần đây để quyết định rule engine có đáng làm hay chỉ cần link Langfuse). Nếu STEP0 cho thấy volume lỗi thấp/link Langfuse là đủ — báo cáo và đề xuất scope rút gọn thay vì build full rule engine, không tự ý build to hơn cần thiết.

### 5. AA-489 — Rewrite quota/tháng
Issue này có 4 điểm business chưa chốt (limit/tenant/tháng, theo plan_tier nào, reset cycle, hard-block hay soft-warning). **Không dừng hỏi Nghiệp giữa chuỗi — tự chọn phương án bảo thủ nhất, ghi rõ lý do trong comment STEP0/wireframe trước khi code:**
- Limit khởi điểm: dùng đúng số đã có sẵn trong `PLAN_LIMITS.tours_per_month` (admin.py) — không bịa số mới.
- Reset: đầu tháng calendar (đơn giản, khớp business thông thường).
- Hard-block khi vượt quota (an toàn hơn cho cost control — mục đích gốc issue nêu rõ là kiểm soát LLM cost).
- Endpoint `/v1/quota` build thật để CatalogTab.tsx dùng lại (đã dọn code chết ở AA-428).
Nếu Nghiệp không đồng ý phương án này, đây là điểm đầu tiên Claude Chat sẽ yêu cầu sửa lại khi soát — không chặn chuỗi tiếp tục.

### 6. AA-462 — Mở rộng Publish 6 kênh
Tương tự — cần quyết định kênh ưu tiên. **Tự chọn theo tiêu chí: kênh nào đã có content_piece/channel data thật nhiều nhất trong DB hiện tại** (query thật, không đoán) làm ưu tiên build trước; build publish adapter cho đúng 1-2 kênh có data thật nhiều nhất trước, không cố làm cả 6 cùng lúc. Ghi rõ lý do chọn kênh trong comment STEP0. Các kênh còn lại: tạo sub-issue riêng hoặc để lại trong chính AA-462, không tự ý mở rộng hết phạm vi.

---

Báo cáo evidence đầy đủ theo đúng chuẩn (browser/API/DB thật, không `/health` suông) trên từng issue tương ứng.
