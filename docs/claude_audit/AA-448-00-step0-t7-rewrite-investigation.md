# AA-448 — STEP0 Investigate: T7 Content Planning viết lại hoàn toàn

Investigate + tổng hợp only, không sửa code. Branch `feature/aa-448-step0-t7-rewrite-investigation`,
worktree `../aa-448-worktree`. Đọc trực tiếp `services/acp_planning/quarter.py`,
`services/acp_planning/allocator.py`, `services/acp_planning/runway.py`,
`services/acp_planning/models.py`, `services/acp_planning/constants.py` toàn bộ file phiên này
(không suy đoán, không tin lại memory) + đối chiếu `docs/claude_audit/AA-447-01-sync-audit-matrix.md`,
`docs/claude_audit/AA-440-marketplace-planning-produce-migration-audit.md`,
`docs/claude_audit/AA-445-01-dfs-distinctiveness-step0-audit.md` (worktree `aa-445-worktree`),
`docs/implementation-notes/AA-430-*.md`/`AA-431-*.md`/`AA-444-*.md`/`AA-445-02-*.md`, và
`frontend/app/(tenant)/portal/_components/Sidebar.tsx` (đọc toàn bộ 171 dòng).

**⚠️ Không có quyền truy cập Notion trong phiên này** — mọi trích dẫn "ADR-2026-038 §x" dưới đây
kế thừa từ cách các task trước (AA-440/AA-444/AA-445-01/AA-445-02) đã trích, không tự fetch lại
ADR gốc. Không phát hiện file ADR-2026-038 nào tồn tại trên đĩa trong bất kỳ repo nào của
workspace — văn bản gốc chỉ có trên Notion.

**Headline — 1 phát hiện quan trọng làm sai lệch tiền đề của chính task prompt AA-448**:
`dfs_relevance` **CHƯA được build**, trái với khẳng định "Đã build xong (AA-445, PR #199)" trong
bối cảnh task. Grep toàn repo (`main`, nhánh mới nhất post-PR#199) cho chuỗi `dfs_relevance`:
**0 kết quả**. AA-445-01 (STEP0 của chính cụm AA-445, 23/08) đã tự xác nhận "0 hits — chưa build
gì" và liệt `dfs_relevance` vào mục "chưa quyết định/chưa build, real open point cho AA-445-02".
Đọc trực tiếp implementation notes của AA-445-02 (`docs/implementation-notes/AA-445-02-*.md`) xác
nhận session đó chỉ build `CompetitorIndex`/`score_distinctiveness()`/DFS→T2 (`process_seo()` vào
`trigger_rewrite()`)/competitor UI — **không có dòng nào build `dfs_relevance`**. Xem mục 5 bên
dưới để biết ảnh hưởng cụ thể tới T7.

---

## 1. Logic thật trong `quarter.py` + `allocator.py` — giữ gì, bỏ gì

### Tên hàm thật (xác nhận qua đọc code, khớp memory)

| Hàm | File:line | Vai trò |
|---|---|---|
| `compute_runway_map(tenant_id, year, trips, markets)` | `runway.py:155` | N4 — pure, tính BOFU/MOFU/TOFU/OFF theo destination×market×month từ `period`/`duration_raw`/`lifecycle_stage`. |
| `compute_quarter_plan(tenant_id, year, quarter, trips, markets, capacity_posts_per_week, specials, runway, atoms_by_trip, excludes)` | `quarter.py:141` | N5 — pure, chấm điểm + chọn trip cho quý, tính `destination_shares`, chọn `big_rocks`. |
| `compute_slot_grid(tenant_id, year, month, channels, capacity_posts_per_week, quarter_plan, runway, trips_by_id, atoms_by_trip, primary_market, today)` | `allocator.py:121` | N6 — pure, lấp lịch tuần/kênh từ `QuarterPlan` đã approve. |
| `fetch_trips(tenant_id, pool)` | `runway.py:205` | DB wrapper — đọc `acp_contract.v_trip_registry`. **Xem cảnh báo quan trọng bên dưới.** |
| `fetch_atoms_by_trip(tenant_id, pool)` | `quarter.py:262` | DB wrapper — đọc atom. **Đây chính là bug đã biết, mục 3.** |
| `plan_quarter()` / `allocate_month()` | `quarter.py:272` / `allocator.py:260` | Async wrapper nối compute-function với 2 fetch ở trên. |
| `approve_quarter_plan()` (in-memory) / `save_quarter_plan_version()` / `approve_quarter_plan_version()` / `fetch_approved_quarter_plan()` / `fetch_current_version_no()` / `fetch_quarter_plan_version()` | `quarter.py:291-486` | Gate B persist layer (AA-320/AA-323). |
| `allocate_month_from_db()` | `allocator.py:279` | Wrapper đọc Gate-B-approved plan rồi gọi `allocate_month()`. |
| `create_weekly_produce_run()` / `persist_slot_grid()` / `fetch_due_slots()` / `mark_slot_status()` / `allocate_and_persist_week()` | `allocator.py:309-432` | N7 persist layer (AA-377/AA-378), ghi `acp_shared.acp_v2_runs`/`acp_v2_slots`. |

### (A) Business logic thuần túy — GIỮ NGUYÊN CÔNG THỨC (copy logic, không copy file)

Tất cả các hàm này là pure function (không DB/LLM, 100% unit-testable), nhận `tenant_id` như
tham số bắt buộc, không tự query gì — **AA-440's claim "100% reusable, đã tenant-scoped by
design" vẫn ĐÚNG, verify lại bằng đọc trực tiếp code phiên này**:

1. **`compute_runway_map`** — công thức offset theo market (`long_haul`/`family_extended`/
   `short_haul`, `constants.RUNWAY_OFFSETS_MONTHS`) + band BOFU/MOFU/TOFU (`_stage_for_dist`,
   B11 fix) + phát hiện family trip (`_family_detected`, B9 fix, scan `itinerary_source`).
2. **`compute_quarter_plan`** — công thức chấm điểm trip: `score = runway_fit*0.4 + richness*0.3
   + dist*0.3 + forced_bonus`; special-tour fuzzy match (`_fuzzy_match`, B4 fix — token overlap +
   prefix, không phải substring containment); cap chia sẻ nội dung cho trip "thin" (
   `_cap_thin_trip_shares`, B5 fix, ngưỡng `THIN_TRIP_MAX_SHARE=0.15`); chọn `big_rocks` (top-3
   trip, ≥2 atom HIGH chưa dùng); nhãn lý do chấm điểm (`_score_reason`, AA-323 round 6 — tie-break
   fix quan trọng, giữ nguyên).
3. **`compute_slot_grid`** — round-robin theo `destination_shares`; atom floor + cooldown +
   used-this-month dedupe (`_eligible_atoms`, B7 fix); slot_id xác định (`_deterministic_slot_id`,
   AA-377/AA-410 fix — **PHẢI giữ đúng công thức hash `tenant_id|year|month|week|trip_id|channel`**,
   đổi sẽ làm mọi slot đã persist trước đó "mồ côi"); keyword_seed qua `seed_builder.build_seed()`
   (AA-379 fix); framework lookup (`constants.FRAMEWORK_TABLE`); phasing_out trip chỉ vào tháng
   hiện tại (không phải tháng khác).
4. **Persist layer N7** (`create_weekly_produce_run`/`persist_slot_grid`/`fetch_due_slots`/
   `mark_slot_status`/`allocate_and_persist_week`) — đã tenant-scoped, `ON CONFLICT DO NOTHING`
   idempotent đúng thiết kế (AA-377/378/410), **hoàn toàn không đụng Gate B** — không có lý do gì
   phải viết lại, T7 mới (dù chỉ tính tới N5/N6) nên để nguyên lớp N7 persist này cho tương lai T8.

### (B) Phải bỏ hoàn toàn — Gate B hardcode chặn cứng

Grep chính xác chuỗi `"Ms. Thu"`/`"Ms Thu"` trong exception message thật (không tính comment/
docstring/test) — **đúng 2 chỗ**, khớp claim AA-440:

| File:line | Nội dung |
|---|---|
| `allocator.py:130` (trong `compute_slot_grid`) | `raise QuarterPlanNotApprovedError("Gate B: quarter plan must be approved by a human (Ms. Thu) before allocation — never auto.")` |
| `allocator.py:297` (trong `allocate_month_from_db`) | `raise QuarterPlanNotApprovedError(f"No approved quarter plan for tenant={tenant_id} ... Gate B: quarter plan must be approved by a human (Ms. Thu) before allocation — never auto.")` |

Ngoài 2 chỗ raise thật này, "Ms. Thu" còn xuất hiện trong **comment/docstring** (không phải logic
chặn) ở `quarter.py:17`, `models.py:26`, `models.py:121` (`QuarterPlanNotApprovedError`'s
docstring, `QuarterPlan.approved` field comment) — các dòng này mô tả ý định Gate B, không tự nó
chặn gì, nhưng **nên xoá/viết lại cùng lúc** vì cùng nói về khái niệm Gate B đã bị ADR §0.2 bãi bỏ,
để lại sẽ gây hiểu lầm cho người đọc code sau này.

Ngoài 2 exception message, các phần khác PHẢI bỏ/viết lại theo cùng lý do (không phải hardcode
"Ms. Thu" trực tiếp nhưng LÀ hiện thân của gate chặn con người):
- `QuarterPlan.approved`/`approved_by` (field) + `approve_quarter_plan()`/
  `approve_quarter_plan_version()` (`quarter.py:291-396`) — toàn bộ khái niệm "pending → cần người
  duyệt → approved" tự nó là Gate B, không chỉ 2 dòng raise.
- `GET /admin/quarter-plan/pending` + `POST /admin/quarter-plan/{version_id}/approve`
  (`api/routers/admin.py`, dòng AA-440 đã trích `1811-1850`/`1962-1999` — **chưa re-verify số dòng
  chính xác phiên này**, chỉ xác nhận 2 route này tồn tại qua `grep -n "quarter_plan"
  admin.py`) — cross-tenant admin worklist, không còn ý nghĩa khi không còn ai cần duyệt.

### Verify lại claim "tenant-scoped 100%" — có 1 ngoại lệ AA-440 không nêu rõ đủ

`compute_quarter_plan`/`compute_slot_grid` bản thân đúng là pure & tenant-safe (nhận
`tenant_id`, không tự query). Nhưng **`fetch_trips()` (`runway.py:205`) — hàm DB-wrapper cấp
input `trips` cho toàn bộ N4/N5/N6 — hiện KHÔNG filter theo tenant nào cả**:

```python
_TRIP_ROW_QUERY = """
    SELECT id, name, destination, period, duration_raw, itinerary_source,
           lifecycle_stage, trip_url, url_alive
    FROM acp_contract.v_trip_registry
"""
# WHERE tenant_id = $1 đã bị BỎ có chủ đích, xem comment inline runway.py:206-222
```

Comment inline (13/08/2026, AA-323 round 6 Phần B, quyết định của Nghiệp) giải thích: filter theo
tenant khiến MỌI tenant B2B thấy 0 trip (vì `v_trip_registry.tenant_id` chỉ từng là
`aa_internal`), nên tạm thời **mọi tenant đọc chung 763 trip của platform catalog**, "REVISIT WHEN
N1 SHIPS". AA-440 đã trích đúng đoạn này (§1c) nhưng liệt nó vào mục "reusable, tenant-scoped by
design" — **cách gọi đó hơi lỏng**: `fetch_trips()` không hề tenant-scoped, nó CỐ Ý dùng chung 1
danh sách cho mọi tenant. `compute_*` phía sau vẫn an toàn (không leak dữ liệu RIÊNG TƯ của tenant
khác — trip chỉ là catalog công khai của platform), nhưng **T7 mới, nếu build trên
`fetch_trips()` y nguyên, sẽ cho MỌI tenant thấy đúng 1 danh sách trip giống hệt nhau** — không
phải bug an toàn dữ liệu, nhưng là 1 giới hạn sản phẩm thật (không có "my trips" riêng theo
Marketplace/N1 licensing) cần biết trước khi build T7, không phải điều task prompt gốc nhắc tới.
**Câu hỏi mở — xem mục Open Questions.**

---

## 2. Trích AA-447-01 — tình trạng T7

Từ `docs/claude_audit/AA-447-01-sync-audit-matrix.md` (bảng ma trận, dòng T7):

> **T7** Content Planning / Quarter Plan | ⚠️ Real logic (`compute_quarter_plan`, `allocator.py`)
> NHƯNG **2 bug thật chặn dùng**: (1) Gate B hardcode "Ms. Thu" chưa gỡ (AA-440 §1b); (2)
> **`fetch_atoms_by_trip()` join sai `raw_tours.tenant_id` thay vì `owner_scope`** — đã biết từ
> AA-440 §1c (22/08), **live-verify thật 2 lần trong AA-445-02 (23/08): 0 trips/0 atoms cho tenant
> có 15 atom T5 thật** | ❌ **KHÔNG CÓ ROUTE NÀO** — xác nhận `find "frontend/app/(tenant)/portal"
> -iname "*t7*"` = rỗng, và `Sidebar.tsx` (đọc toàn bộ) không có mục nào tên "Content
> Planning"/"Quarter Plan"/T7 — khớp ĐÚNG ảnh chụp thật Nghiệp gửi | ✅
> `acp_shared.quarter_plan`/`quarter_plan_version` (9 row thật, tenant_id có) — hạ tầng sẵn sàng,
> không phải vấn đề hạ tầng | ⚠️→❌ **LỆCH TẦNG NẶNG** (gần như CHƯA CÓ nếu tính từ góc nhìn
> tenant) | Admin-side "Quarter Plan (Gate B)" trong AdminSidebar CÓ (dòng 208-210) nhưng đó là
> admin duyệt CHO tất cả tenant, không phải tenant tự dùng. **Tenant hoàn toàn không có cách nào
> chạm vào T7** — không route, không link từ T6, không gì cả.

Và phần ghi chú riêng (cùng file, mục "Chi tiết theo stage"):

> **T7 — bug then đã biết trước, giờ mới live-verify thật.** `AA-440` (22/08, §1c) đã ĐỌC RA
> chính xác bug này qua code + đếm row — nhưng chưa từng GỌI THẬT hàm `fetch_atoms_by_trip()` để
> xem nó trả về gì. `AA-445-02`'s verify (23/08) là lần đầu tiên gọi thật hàm này với 1 tenant có
> atom T5 thật — xác nhận **0 trips, 0 atoms**, đúng như AA-440 dự đoán từ đọc code.

Kết luận đối chiếu: mô tả trong AA-448 task description ("Real logic tồn tại, 0 route/sidebar,
infra sẵn sàng, 2 bug chặn dùng") **khớp đúng 100%** với AA-447-01. Không có mâu thuẫn ở mục này.

---

## 3. `fetch_atoms_by_trip()` — bug + tất cả call site thật

### Vị trí bug (`quarter.py:232-269`)

```python
_ATOM_ROW_QUERY = """
    SELECT ta.atom_id, ta.tour_id, ta.text, ta.activity_type, ta.distinctiveness, ta.starred,
           ta.deleted, ta.weight, ta.cooldown_until, ta.usage_log
    FROM acp_contract.tour_atoms ta
    JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = ta.tour_id
    WHERE rt.tenant_id = $1 AND NOT ta.deleted AND NOT ta.is_empty_marker
"""
```

`raw_tours.tenant_id` luôn là `aa_internal` (không có pipeline B2B nào ghi `raw_tours` cho tenant
khác — xác nhận lại đúng như AA-438/AA-440 đã nêu, không phải giả định). Atom T5
(`owner_scope=<tenant_id>` thật) không bao giờ khớp `rt.tenant_id = $1` khi `$1` là 1 tenant B2B
thật → **0 atom, luôn luôn**, đúng như AA-445-02 live-verify 2 lần (0 trước/0 sau khi tạo atom
mới cho `test-n1-flow`).

### Toàn bộ call site thật (grep `fetch_atoms_by_trip`, không giới hạn quarter.py/allocator.py)

| File:line | Loại |
|---|---|
| `quarter.py:262` (định nghĩa) | — |
| `quarter.py:284` (`plan_quarter()`) | **Production — N5** |
| `allocator.py:268,272` (`allocate_month()`, import cục bộ từ `.quarter`) | **Production — N6** |
| `tests/unit/test_aa301_quarter.py:20,282` | Test |
| `tests/unit/test_aa377_aa378_run_slot_persist.py:386` | Test (docstring, không gọi thật) |
| `tests/verify_scripts/aa375_slot_production_verify.py:109` | Verify script (docstring) |
| `tests/verify_scripts/aa391_e2e_orchestrator.py:146,322` | Verify script (gọi thật) |

**Kết luận: đúng 2 call site production thật** — `plan_quarter()` (N5) và `allocate_month()`
(N6), không có chỗ thứ 3 nào khác trong `api/routers/*` gọi trực tiếp hàm này. T7 mới sẽ thay thế
cả 2 wrapper này (hoặc viết wrapper mới dùng đúng `owner_scope`), không cần sửa gì ở
`admin_atoms.py`/`v1_marketplace.py` (2 nơi ĐÃ dùng đúng `owner_scope` từ trước, AA-431/AA-444).

---

## 4. Route/tên mới cho T7

### Convention hiện có (đọc `Sidebar.tsx` toàn bộ 171 dòng, xác nhận đúng — không suy đoán)

`NAV1` (nhóm "Workspace", `Sidebar.tsx:24-32`), thứ tự thật hiện tại:

| # | href | label | Stage |
|---|---|---|---|
| 1 | `/portal/dashboard` | Dashboard | — |
| 2 | `/portal/t1-rewrite` | Browse Pool | T1 |
| 3 | `/portal/t4-pool` | My Catalog | T4 |
| 4 | `/portal/t0-brand` | Brand Identity | T0 |
| 5 | `/portal/t6-atoms` | Atom Curation | T6 (AA-431) |
| 6 | `/portal/marketplace` | Marketplace | không T-stage (AA-444) |
| 7 | `/portal/api` | API Access | — |

`NAV2` (nhóm "Account"): Activity Log / Billing / Settings — 3 mục utility, không T-stage.

Convention rút ra (khớp AA-430's implementation-notes bảng "Tab → Route" + AA-431/AA-444's
Decisions): route path = `t<N>-<tên-ngắn-1-2-từ>` cho stage có T-number thật; route không có
T-number cho utility/cross-stage view (`marketplace`, `api`, `activity`, `billing`, `settings`).
Label sidebar dùng tên mô tả chức năng, KHÔNG lộ chữ "T7"/số kỹ thuật ra UI (đúng nguyên văn quyết
định AA-431: *"giữ tên kỹ thuật T-number chỉ trong route path/code comment, không lộ ra UI"*).

### Đề xuất route T7

**`/portal/t7-planning`**, label sidebar **"Content Planning"** (khớp tên stage trong chính task
description, "Content Planning / Quarter Plan" — "Content Planning" ngắn hơn, tự nhiên hơn cho
UI so với "Quarter Plan", giống cách "Atom Curation" được chọn thay vì "T6"/"My Atoms"). Đặt sau
"Atom Curation" (T6), trước "Marketplace" — theo đúng thứ tự pipeline thật (T6 curate atom → T7
lên kế hoạch dùng atom đó → Marketplace là view tổng hợp riêng không thuộc chuỗi tuần tự này).
**Không tìm thấy tên khác trong ADR gốc** (không có file ADR trên đĩa để đối chiếu — xem cảnh báo
đầu file); nếu Nghiệp/Claude Chat có bản ADR ghi tên khác, ưu tiên tên đó.

Component đề xuất: `frontend/app/(tenant)/portal/_components/PlanningTab.tsx` (theo đúng convention
đặt tên `<Stage>Tab.tsx` — `BrandTab`/`PoolTab`/`CatalogTab`/`AtomsTab`/`MarketplaceTab`), route
file `frontend/app/(tenant)/portal/t7-planning/page.tsx`. `Sidebar.tsx` thêm 1 dòng vào `NAV1`
(icon gợi ý: `CalendarRange`/`Target` từ `lucide-react`, chưa dùng bởi mục nào khác trong sidebar
này). `layout.tsx` thêm `/portal/t7-planning` vào `BREADCRUMBS` (đúng pattern AA-431 đã làm).

### Endpoint mới đề xuất (mức khung, không phải quyết định cuối — xem Open Questions về Gate B thay thế bằng gì)

Theo convention `/v1/*` (tenant-JWT-only) đã thấy ở `v1_tours.py`/`v1_marketplace.py`/
`v1_competitors.py`, KHÔNG dùng `/admin/quarter-plan/*` (đó là admin cross-tenant, sẽ bị
retire theo mục 1B):

| Method | Path | Vai trò |
|---|---|---|
| `GET /v1/planning/quarter-plan?year=&quarter=` | Đọc plan hiện tại (nếu có) của tenant cho quý đó — tương đương `fetch_approved_quarter_plan`/`fetch_current_version_no` cũ, nhưng không còn khái niệm "approved" theo nghĩa người duyệt. |
| `POST /v1/planning/quarter-plan/preview` | Chạy `compute_quarter_plan()` (tính thử, chưa lưu) — cho tenant xem trip nào được chọn, `trip_scores` đầy đủ, trước khi "chốt". Tương đương `preview-slotgrid` admin cũ nhưng tenant-JWT. |
| `POST /v1/planning/quarter-plan` | Tenant "chốt" plan cho quý — gọi `save_quarter_plan_version()` rồi tự set trạng thái final (thay vì `pending` chờ người duyệt — xem Open Questions #1 về đặt tên trạng thái mới). |
| `GET /v1/planning/slot-grid?year=&month=` | Đọc/tính `compute_slot_grid()` cho tháng — chuẩn bị cho T8-T9 đọc sau này. |

Đây là khung gợi ý dựa trên shape hàm hiện có, KHÔNG phải quyết định cuối cùng — cần Nghiệp/Claude
Chat chốt tên field response + có cần endpoint riêng cho "excludes" (manual override N5 Gap 1,
AA-323) hay gộp vào body của POST preview.

---

## 5. Input/output data T7 mới cần

### 5a. Atom đã curate — qua Marketplace view (AA-444)

Xác nhận tên thật: **`GET /v1/marketplace`**, file `api/routers/v1_marketplace.py`, query có tên
`_MARKETPLACE_QUERY` (theo implementation notes AA-444, chưa đọc trực tiếp file router phiên này
— tên endpoint/router đã xác nhận qua router registration + implementation notes, đủ độ tin cậy
cho STEP0 này). Nguồn dữ liệu: `gold_aa_internal.tenant_tour_versions` (T4) **LEFT JOIN**
`acp_contract.tour_atoms` theo `owner_scope` (T6) — gom theo **latest version per published
tour**, atom_count có thể = 0 (tour đã rewrite nhưng chưa atomize, cố ý không lọc ẩn). Live-verify
thật (23/08) trả đúng field `tenant_id`/`posts_per_week`/tour list/`atom_count`/`runway_months`.

**Lưu ý quan trọng cho T7**: Marketplace view đọc atom qua `owner_scope` đúng cách — nếu T7 mới
tái dùng chính query/logic này (khuyến nghị, thay vì tự viết `fetch_atoms_by_trip()` phiên bản 2),
bug mục 3 tự động biến mất, đúng như task description đã giả định.

### 5b. `dfs_relevance` — **CHƯA TỒN TẠI, khác với giả định của task**

Đã nêu ở Headline — nhắc lại chi tiết: `dfs_relevance` là tên field ADR-2026-038 §0.4 **đặt ra**
(theo trích dẫn của AA-445-01, không phải tên đã có sẵn trong code từ trước) cho 1 signal **cấp
tour** dự kiến tính từ `seo_context.search_volume`, dùng để lọc/ưu tiên tour ở T1 và T7 — **tách
biệt với `distinctiveness`** (cấp atom, ĐÃ build xong qua `score_distinctiveness()`,
AA-445-02, PR #199 — phần này đúng như task mô tả). Nhưng bản thân `dfs_relevance`:
- Không có cột DB nào tên này.
- Không có hàm nào tên `score_relevance`/`compute_dfs_relevance`/tương tự.
- `quarter.py`'s công thức chấm điểm hiện tại (`runway_fit*0.4 + richness*0.3 + dist*0.3 +
  forced_bonus`) **không có chỗ cho 1 trọng số thứ 4** — AA-445-01 đã tự nêu đúng điểm này
  ("§0.4 nói 'thay hoặc bổ sung runway_fit' mà không chọn — 4 trọng số phải re-derive lại từ đầu,
  không phải chỉ cắm số vào").
- T2 đã có sẵn phần nền cần thiết (DFS→T2 qua `process_seo()`, AA-445-02 build xong) — nghĩa là
  `seo_context.search_volume` GIỜ đã có dữ liệu thật cho tour tenant rewrite, nhưng **chưa có ai
  đọc nó ra thành `dfs_relevance` cả**.

**Ảnh hưởng cụ thể tới T7**: T7 mới **KHÔNG THỂ** "dùng `dfs_relevance` ngay, không cần chờ" như
task description giả định — vì field đó chưa tồn tại ở bất kỳ dạng nào. T7 có 2 lựa chọn: (a) tự
build `dfs_relevance` như 1 phần của việc viết lại T7 (mở rộng scope), hoặc (b) build T7 trước với
công thức 3-trọng-số hiện tại (runway_fit/richness/dist, bỏ `forced_bonus` nếu cần), để
`dfs_relevance` là 1 việc bổ sung riêng sau (kèm 1 vé Linear mới, không lẫn vào phạm vi "viết lại
T7"). **Đây là câu hỏi mở, không tự quyết ở đây** — xem Open Questions #2.

### 5c. Rate-limit/quota theo tenant

Kiểm tra trực tiếp (không chỉ tin lại AA-440 §4, dù kết luận trùng khớp):

| Cơ chế | Bảng/cột | Enforce thật hay chỉ hiển thị? |
|---|---|---|
| `posts_per_week` | `shared.tenants.posts_per_week` (migration 099) | **Enforce thật** — trực tiếp là `capacity_posts_per_week` input của `compute_slot_grid`/`plan_quarter`, quyết định `total_slots = capacity_posts_per_week * 4` (`allocator.py:138`). |
| `rate_limit_rpm` | `shared.tenants.rate_limit_rpm` | **Enforce thật** nhưng chỉ ở tầng HTTP request/phút (`api/middleware/rate_limit.py`), không phải "số quarter plan/tháng". |
| `acp_quota_ledger` (`s2_runs_limit`/`s3_runs_limit`/`s4_blogs_limit` + `*_used`, migration 042) | `acp_shared.acp_quota_ledger` | **Bảng tồn tại, được ghi 1 lần lúc tạo tenant** (`admin.py:150-159`, hardcode `10,10,50`, biến `plan_limits` tính ra nhưng KHÔNG dùng — có vẻ là dead code từ trước, không phải phạm vi AA-448) **nhưng KHÔNG BAO GIỜ được đọc lại hay tăng `*_used` ở bất kỳ đâu khác trong repo** (grep `s2_runs_used`/`s3_runs_used`/`s4_blogs_used`/`s2_runs_limit` toàn repo: chỉ đúng 1 chỗ, chính là INSERT lúc tạo tenant). Đây là 1 phát hiện MỚI so với AA-440 (AA-440 không nêu tên bảng này) — có sẵn khung bảng đúng ý "quota theo N loại run", nhưng hoàn toàn chưa enforce, cũng chưa map field nào cho "quarter plan"/N5-N6 cả. |
| `tours_quota_monthly`/`api_calls_quota_monthly` | `shared.v_tenant_monthly_usage` (view) | **Chỉ hiển thị** (Settings/Billing UI), không chặn gì — khớp đúng AA-440 §4. |

**Kết luận cho T7**: khớp đúng kết luận AA-440 — có 2 cơ chế enforce thật (`posts_per_week`,
`rate_limit_rpm`) đã đủ dùng NGAY cho T7 mới (không cần chờ thiết kế quota riêng để bắt đầu build).
`acp_quota_ledger` là 1 khung có sẵn, gần đúng ý "giới hạn N lần chạy/tháng" ADR §0.2 mục 3 muốn,
nhưng **hiện là bảng chết** — nếu Nghiệp muốn T7 enforce thêm "N quarter plan/tháng", đây là chỗ
tự nhiên để mở rộng (thêm 1 cột `n5_runs_limit`/`n5_runs_used` hoặc tái dùng `s3_runs_*` — S3 =
N5 theo naming gốc `aamc`?, cần hỏi lại vì tên cột hiện tại dùng ký hiệu S2/S3/S4 của kiến trúc
CŨ, không khớp N4-N11 hiện tại) — nhưng đây là việc THIẾT KẾ MỚI, không phải điều kiện chặn T7 bắt
đầu build.

---

## Tổng hợp — giữ nguyên vs. viết mới hoàn toàn

### Giữ nguyên công thức (copy logic thuần, viết lại code path xung quanh)
- `compute_runway_map()` toàn bộ (`runway.py:155-185`) — kể cả `_offset_for`/`_stage_for_dist`/
  `_family_detected`/`parse_duration_days`/`parse_period`.
- `compute_quarter_plan()` toàn bộ (`quarter.py:141-229`) — kể cả `_fuzzy_match`/
  `_cap_thin_trip_shares`/`_score_reason`.
- `compute_slot_grid()` toàn bộ (`allocator.py:121-257`) — kể cả `_eligible_atoms`/
  `_deterministic_slot_id`/`_add_note` — **giữ đúng công thức hash slot_id, không đổi**.
- Toàn bộ persist layer N7 (`create_weekly_produce_run`→`allocate_and_persist_week`,
  `allocator.py:309-432`).
- `fetch_trips()` bản thân KHÔNG CẦN sửa code (đã tenant_id-safe về mặt an toàn dữ liệu) — chỉ cần
  biết trước giới hạn "mọi tenant thấy chung 1 catalog" khi thiết kế UI T7 (mục Open Questions #3).

### Phải viết mới hoàn toàn
- `fetch_atoms_by_trip()` → thay bằng query dùng `owner_scope IN ('platform', $1)` (khuyến nghị
  tái dùng logic Marketplace view AA-444 thay vì viết query thứ 3).
- Toàn bộ khái niệm Gate B: field `approved`/`approved_by`, `approve_quarter_plan()`,
  `approve_quarter_plan_version()`, 2 exception "Ms. Thu" (`allocator.py:130,297`), route admin
  `/admin/quarter-plan/pending`+`/approve`.
- Toàn bộ tầng API/FE: router mới (`v1_planning.py`?), `PlanningTab.tsx`, route
  `/portal/t7-planning`, sidebar entry.
- `dfs_relevance` — chưa tồn tại ở bất kỳ dạng nào, cần quyết định có nằm trong scope T7 hay tách
  vé riêng (Open Questions #2).

---

## Open Questions — cần Nghiệp/Claude Chat quyết định trước khi build

1. **Gate B thay bằng trạng thái gì?** AA-440 nêu 2 hướng (a. tenant tự tạo → tự động
   `approval_status='approved'`; b. đổi ý nghĩa cột thành "draft" vs. "current") nhưng không chọn.
   T7 mới cần chọn 1 trong 2 (hoặc phương án khác) trước khi thiết kế response shape của
   `POST /v1/planning/quarter-plan`.
2. **`dfs_relevance` có nằm trong scope "viết lại T7" hay tách vé riêng?** Nếu nằm trong scope,
   cần thêm bước: (a) chọn công thức 4-trọng-số mới cho `compute_quarter_plan` (thay/bổ sung
   `runway_fit`, theo đúng câu hỏi AA-445-01 đã treo), (b) build hàm đọc
   `seo_context.search_volume` → bucket HIGH/MED/LOW (ngưỡng tạm §0.4: <50/50-500/>500, tự nhận
   "uncalibrated"), (c) quyết định null-handling (seo_context có thể null hoàn toàn, xem
   AA-439-05). Nếu tách vé riêng, T7 build trước với 3 trọng số hiện có (bỏ `dfs_relevance` khỏi
   phạm vi ban đầu) — **khuyến nghị nhẹ: tách vé riêng**, để không chặn T7 vào việc chờ 1 quyết
   định công thức scoring còn treo, nhưng đây là gợi ý, không phải quyết định.
3. **`fetch_trips()` dùng chung catalog cho mọi tenant — T7 có cần "my trips" riêng không, hay
   giữ nguyên hành vi này?** Đây là hành vi CHỦ Ý của Nghiệp (13/08/2026), "REVISIT WHEN N1
   SHIPS" — nếu N1/Marketplace licensing coi như đã đủ chín (AA-444 xong), đây có thể là lúc
   revisit đúng như comment inline đã hẹn, nhưng KHÔNG nằm trong 5 mục task prompt AA-448 yêu cầu
   điều tra — nêu ra vì trực tiếp ảnh hưởng "T7 hiển thị trip nào cho tenant nào", không tự quyết.
4. **Route/label tên chính xác `/portal/t7-planning` + "Content Planning"** — đề xuất ở mục 4,
   chưa có ADR gốc để đối chiếu (không truy cập được Notion phiên này) — cần Nghiệp xác nhận hoặc
   sửa nếu ADR thật ghi tên khác.
5. **Endpoint shape mục 4** — chỉ là khung gợi ý dựa theo shape hàm hiện có, chưa chốt field
   response/request cụ thể, đặc biệt cách truyền `excludes` (N5 Gap 1 manual override) qua API.

## Giới hạn phiên này

- Không truy cập Notion — mọi trích ADR-2026-038 kế thừa qua các audit trước, không tự fetch lại
  văn bản gốc để verify từng chữ.
- Không chạy DB/ECS-exec (không cần cho task investigate-only này, không có yêu cầu số liệu mới).
- `api/routers/v1_marketplace.py` xác nhận qua implementation notes + router registration, chưa tự
  đọc trực tiếp toàn file phiên này (đã đủ độ tin cậy cho STEP0, nhưng nếu build T7 tái dùng logic
  này, nên đọc trực tiếp file trước khi copy).
- `admin.py`'s route `/admin/quarter-plan/pending`/`/approve` xác nhận TỒN TẠI (`grep -n
  "quarter_plan" admin.py`) nhưng chưa re-verify số dòng chính xác AA-440 đã trích (`1811-1850`/
  `1962-1999`) — không ảnh hưởng kết luận (route này chắc chắn bị retire dù ở dòng nào).
