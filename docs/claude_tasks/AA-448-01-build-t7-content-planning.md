# AA-448 — Build T7 Content Planning (viết lại hoàn toàn)

## Bước 0 — Merge worktree investigation trước khi build

Branch `feature/aa-448-step0-t7-rewrite-investigation` (worktree `../aa-448-worktree`) đã có
deliverable `docs/claude_audit/AA-448-00-step0-t7-rewrite-investigation.md`, docs-only, chưa merge.
Merge branch này vào branch build mới TRƯỚC khi bắt đầu code (không code trên nhánh investigation
gốc — theo đúng lesson AA-444 về concurrency, dùng worktree riêng cho task build này).

## Bối cảnh — đọc trước khi code

Đọc lại toàn bộ `docs/claude_audit/AA-448-00-step0-t7-rewrite-investigation.md` (vừa merge) —
không lặp lại investigation, chỉ dùng làm nền. 3 quyết định của Nghiệp (23/08, đã ghi trong comment
Linear AA-448):

1. **Gate B thay bằng gì — CHƯA CHỐT.** Trước khi implement phần persist/status của quarter plan,
   đề xuất ít nhất 2 phương án cụ thể (VD: (a) tự động `status='active'` ngay khi tenant tạo, không
   còn field `approved`; (b) đổi hẳn model — mỗi lần tenant "chốt" tạo 1 version mới, field
   `is_current` thay vì `approved`, không có trạng thái "pending") kèm trade-off ngắn gọn mỗi
   phương án, dừng lại hỏi Claude Chat/Nghiệp trước khi implement DB schema/status logic — đây là
   PHẦN DUY NHẤT trong task này cần dừng giữa chừng để xác nhận, các phần còn lại có thể build
   thẳng.
2. **`dfs_relevance` GỘP vào scope T7 lần này** — không tách vé riêng. Cần build:
   a. Hàm đọc `seo_context.search_volume` → bucket HIGH/MED/LOW, ngưỡng tạm `<50`/`50-500`/`>500`
      (config được, không hardcode — đúng ADR §0.4, ngưỡng "chưa hiệu chỉnh bằng data thật", để dễ
      sửa sau).
   b. Null-handling: fallback MED khi `seo_context` null hoàn toàn (giống cách `distinctiveness`
      gốc đã xử lý thiếu competitor index).
   c. Công thức 4-trọng-số mới cho `compute_quarter_plan` — ADR §0.4 nói "thay HOẶC bổ sung
      `runway_fit`" mà không chọn. Đề xuất cụ thể (giữ nguyên 3 trọng số cũ, thêm trọng số thứ 4
      cho `dfs_relevance`, tổng vẫn =1.0 — hoặc thay thế 1 phần `runway_fit`) — nêu rõ lý do chọn,
      không tự quyết âm thầm nếu ảnh hưởng đáng kể tới kết quả chấm điểm hiện có.
3. **`fetch_trips()` (catalog chung platform) KHÔNG dùng làm input cho T7.** T7 phải lấy trip/tour
   từ Marketplace view (`GET /v1/marketplace`, AA-444) — tức tour tenant ĐÃ chọn+rewrite+atomize
   (đã qua T1→T5, có `tenant_tour_versions`+`tour_atoms` với tenant_id/owner_scope thật), KHÔNG
   phải toàn bộ Master Content platform. Đây là thay đổi so với `compute_runway_map`/
   `compute_quarter_plan` bản cũ (vốn nhận `trips` từ `fetch_trips()`) — cần viết wrapper fetch mới
   dùng Marketplace query, sau đó truyền vào các hàm pure `compute_*` giữ nguyên công thức.

## Việc cần làm

### 1. Backend — viết mới trong `services/acp_planning/` (giữ tên file cũ hay đổi tên tuỳ bạn quyết,
   ghi rõ lý do nếu đổi)

- Giữ nguyên công thức: `compute_runway_map()`, `compute_quarter_plan()` (thêm trọng số
  `dfs_relevance` theo mục 2c), `compute_slot_grid()` — copy logic thuần, không copy nguyên file
  (viết lại code path xung quanh cho sạch, bỏ hết Gate B).
- Viết mới: fetch wrapper dùng Marketplace query (mục 3) thay `fetch_trips()`+`fetch_atoms_by_trip()`.
- Viết mới: hàm tính `dfs_relevance` (mục 2a/2b).
- Bỏ hoàn toàn: field `approved`/`approved_by`, `approve_quarter_plan()`,
  `approve_quarter_plan_version()`, 2 exception "Ms. Thu" (`allocator.py:130,297`), toàn bộ khái
  niệm pending/approve — thay bằng quyết định mục 1 (sau khi đã xác nhận).
- Giữ nguyên, không đụng: toàn bộ persist layer N7 (`create_weekly_produce_run` →
  `allocate_and_persist_week`) — không thuộc scope T7, để dành cho T8.
- Retire route admin `/admin/quarter-plan/pending` + `/admin/quarter-plan/{version_id}/approve`
  (`api/routers/admin.py`) — không còn ý nghĩa.

### 2. API mới — theo khung đã đề xuất trong investigation (điều chỉnh nếu cần sau khi chốt mục 1)

- `GET /v1/planning/quarter-plan?year=&quarter=`
- `POST /v1/planning/quarter-plan/preview`
- `POST /v1/planning/quarter-plan` (chốt plan — status logic theo quyết định mục 1)
- `GET /v1/planning/slot-grid?year=&month=`

Convention `/v1/*` tenant-JWT-only (giống `v1_tours.py`/`v1_marketplace.py`/`v1_competitors.py`).

### 3. Frontend

- Route `frontend/app/(tenant)/portal/t7-planning/page.tsx`
- Component `frontend/app/(tenant)/portal/_components/PlanningTab.tsx`
- `Sidebar.tsx`: thêm mục "Content Planning" vào `NAV1`, đặt sau "Atom Curation", trước
  "Marketplace" (theo đúng đề xuất investigation)
- `layout.tsx`: thêm `/portal/t7-planning` vào `BREADCRUMBS`

### 4. Verify (bắt buộc, theo chuẩn team — không chỉ tin báo cáo)

- Live-verify qua JWT tenant thật: gọi `/v1/planning/quarter-plan/preview`, xác nhận trip trả về
  ĐẾN TỪ Marketplace/tenant đã atomize, KHÔNG phải catalog chung 763 trip.
- Xác nhận `dfs_relevance` trả HIGH/MED/LOW thật cho ít nhất 1 tour có `seo_context` thật (không
  phải toàn NULL→MED).
- Xác nhận `_deterministic_slot_id` hash công thức KHÔNG đổi (nếu đụng tới `compute_slot_grid`,
  dù chỉ để bỏ Gate B xung quanh nó) — so sánh output slot_id trước/sau bằng cùng input mẫu.
- Verify route mới hoạt động qua HTTP thật sau deploy (không chỉ test local).

## Không thuộc scope này

- T8 (Angle Gate) — issue riêng, chưa tạo, KHÔNG đụng persist layer N7.
- Quota/rate-limit enforcement mới cho `acp_quota_ledger` (bảng chết, không phải điều kiện chặn T7).
- Redesign lại UI Marketplace hiện có — chỉ đọc/tái dùng.

## Nhắc

- Lưu task prompt này vào `docs/claude_tasks/` trước khi bắt đầu (skill ai-nghiep §2.1).
- STOP tại mục 1 (Gate B thay thế) — trình phương án, đợi xác nhận trước khi viết code phần
  status/persist đó. Các phần khác (2, 3, phần lớn 1 trừ status logic) có thể build song song/trước.
- Dùng git worktree riêng cho task build này (không dùng lại `../aa-445-worktree` hay bất kỳ
  worktree đang có việc dở của session khác).

---

*Saved verbatim as received from Nghiep/Claude Chat, per ai-nghiep skill §2.1 — before starting
build. Branch `feature/aa-448-build-t7-planning`, worktree `../aa-448-build-worktree`, based on
`main` + fast-forward merge of `feature/aa-448-step0-t7-rewrite-investigation`.*
