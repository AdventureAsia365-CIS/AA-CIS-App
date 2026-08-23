# AA-448 — STEP0 Investigate: T7 Content Planning viết lại hoàn toàn

## Bối cảnh (đã xác nhận, không cần điều tra lại)

- AA-447 (23/08): T7→T8→T9→T10→T11 là 1 cụm liền kề gần như hoàn toàn thiếu FE — 0 route, 0 mục sidebar cho cả 5 stage, T7/T8/T11 còn thiếu cả phần lõi.
- Quyết định đã chốt: **T7 viết lại hoàn toàn**, KHÔNG vá `services/acp_planning/quarter.py`/`allocator.py` cũ — đồng bộ kiến trúc với cách T8 sẽ được xây (viết lại từ đầu, ADR §0.5).
- ADR-2026-038 §0.2 (22/08): Gate B (T7 approval) chuyển tenant self-service hoàn toàn — AA KHÔNG gác cổng nội dung tenant ở bất kỳ bước nào T0-T11. AA chỉ kiểm soát qua (1) rate-limit/quota lúc setup tenant, (2) A4 Cross-Tenant Oversight giám sát hậu-kiểm, không phải gate chặn trước.
- ADR-2026-038 §0.3 (22/08): Marketplace = view tổng hợp `tenant_tour_versions` (T4) JOIN `tour_atoms` (T6) theo tenant — KHÔNG phải trang/bảng riêng. Đã build xong (AA-444, PR #197) — T7 mới nên đọc từ view này, không tự query lại 2 bảng gốc riêng.
- ADR-2026-038 §0.4 (22/08): `distinctiveness` (cấp atom, T6 badge) và `dfs_relevance` (cấp tour, MỚI — dùng để lọc/ưu tiên tour ở T1 và T7, KHÔNG gắn atom) — 2 trục TÁCH BIỆT, không gộp 1 điểm. Đã build xong (AA-445, PR #199), verify live thật — T7 mới CÓ THỂ dùng `dfs_relevance` ngay, không cần chờ.
- Bug đã biết trong code cũ, KHÔNG fix riêng — tự động biến mất khi viết code mới: `fetch_atoms_by_trip()` dùng `WHERE rt.tenant_id = $1` (sai — tenant sở hữu gốc của tour) thay vì `WHERE ta.owner_scope = $1` (đúng — tenant vừa rewrite/atomize). Code T7 mới PHẢI dùng `owner_scope`, không lặp lại lỗi này.

## Việc cần làm — CHỈ ĐIỀU TRA, KHÔNG SỬA CODE

### 1. Đọc lại toàn bộ logic `quarter.py` + `allocator.py` hiện có
- Liệt kê rõ: hàm nào tính gì (đặc biệt `compute_runway_map`, `compute_quarter_plan` nếu tên đúng vậy — xác nhận lại tên hàm thật trong code, đừng tin theo trí nhớ memory).
- Hàm/logic nào là **business logic thuần túy đáng giữ lại** (công thức runway/allocate, không đụng gate/auth) vs. **cái gì phải bỏ hoàn toàn** (Gate B chặn cứng — theo AA-440 đã tìm thấy đúng 2 chỗ, literally ghi tên "Ms. Thu" trong exception message, tìm và liệt kê chính xác các chỗ đó).
- Xác nhận lại: theo AA-440, business logic thuần đã tenant-scoped sẵn 100% — verify claim này còn đúng không (đọc code thật, không tin lại báo cáo cũ).

### 2. Đọc file audit `docs/claude_audit/AA-447-01-sync-audit-matrix.md`
- Trích đúng phần mô tả tình trạng T7 (route/sidebar/backend) để đối chiếu với claim trong AA-448 description.

### 3. Xác nhận call site `fetch_atoms_by_trip()`
- Tìm chính xác file/dòng chứa bug join sai đã nêu trên.
- Liệt kê tất cả nơi gọi hàm này (không chỉ trong quarter.py/allocator.py — có thể còn chỗ khác).

### 4. Quyết định route/tên mới cho T7
- Đối chiếu convention route tenant portal đã có: `/portal/t0-brand`, `/portal/t1-rewrite`, `/portal/t4-pool`, `/portal/t6-atoms`.
- Đề xuất tên route T7 theo đúng convention này (không tự đoán — nếu ADR gốc có ghi tên khác thì ưu tiên tên ADR, báo lại nếu có xung đột).
- Kiểm tra sidebar tenant hiện có bao nhiêu mục, cấu trúc thêm mục mới ra sao (dựa theo cách đã thêm T6 ở AA-431).

### 5. Xác nhận input/output data T7 mới cần
- T7 đọc atom đã curate từ T6 (qua Marketplace view mới — AA-444) — verify chính xác tên view/bảng sau khi AA-444 xong.
- T7 cần đọc `dfs_relevance` (mới từ AA-445) — verify tên cột/hàm chính xác.
- Rate-limit/quota theo ADR §0.2 mục 3: "cơ chế cụ thể (bảng nào lưu quota, enforcement ở đâu) — CẦN điều tra/thiết kế riêng, chưa có trong ADR" — kiểm tra hiện có bảng/cột nào liên quan quota/rate-limit theo tenant chưa (VD trong `shared.tenants`, plan tier) để biết T7 có cần chờ thiết kế quota riêng hay có thể build trước, để rate-limit sau.

## Deliverable

1 file audit mới: `docs/claude_audit/AA-448-00-step0-t7-rewrite-investigation.md` — liệt kê đầy đủ 5 mục trên, kèm:
- Danh sách hàm/logic giữ được nguyên vẹn (copy logic, không copy code file)
- Danh sách phải viết mới hoàn toàn
- Đề xuất tên route + cấu trúc endpoint mới (POST/GET cụ thể)
- Câu hỏi mở cần Nghiệp/Claude Chat quyết định trước khi build (nếu có xung đột hoặc thiếu thông tin)

**KHÔNG build gì trong task này.** Nếu phát hiện gì cần quyết định kiến trúc (vượt phạm vi đã chốt trong ADR), dừng lại và liệt kê thành câu hỏi, không tự quyết.

Nhớ lưu prompt task này vào `docs/claude_tasks/` theo đúng quy trình (skill ai-nghiep §2.1).

---

*Saved verbatim as received from Nghiep/Claude Chat, per ai-nghiep skill §2.1 — before starting
investigation. Branch `feature/aa-448-step0-t7-rewrite-investigation`, worktree
`../aa-448-worktree`.*
