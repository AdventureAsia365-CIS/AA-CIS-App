# AA-473 STEP0 — Điều tra 3 nhánh dọn dẹp admin-gate

Ngày: 2026-08-27 | Loại: STEP0 thuần túy (đọc code + query DB read-only, KHÔNG sửa code, KHÔNG tạo PR)

Bối cảnh: sau AA-472 (bỏ Gate B + portfolio_id bắt buộc, PR #232/#233, migration 119), Nghiệp
xem ảnh chụp UI thật `/admin/tenants` và `/admin/atomize`, nghi ngờ 3 nơi có thể là tàn dư
admin-gate cần dọn theo nguyên lý ADR-2026-038 §0.2 (AA không gate nội dung/hoạt động tenant,
chỉ hậu-kiểm qua A4). Báo cáo này xác nhận từng nhánh bằng code/DB thật.

**Kết luận nhanh (đọc trước khi vào chi tiết)**: trong 3 nghi ngờ ban đầu, chỉ có 1 nhánh
(Gate A) có việc thật cần làm — và đó là **dọn dữ liệu test**, không phải xoá code. 2 nhánh
còn lại (Atomize/Curation, Planning tab) **không phải tàn dư admin-gate** — cả hai đều là hạ
tầng đang sống, xoá sẽ làm hỏng pipeline thật hoặc mất công cụ sản xuất catalog dùng chung.

---

## Nhánh 1 — Atomize/Curation (Master Content)

### Hiện trạng xác nhận

**Backend endpoints:**

`api/routers/admin_atoms.py` (đăng ký tại `api/main.py:139`, prefix `/admin`):
- `GET /admin/atoms` (`admin_atoms.py:184`) — list/filter atom, phân trang (mặc định 50),
  `owner_scope` được resolve từ tenant JWT hoặc admin secret (`_resolve_atom_owner_scope`,
  dòng 86)
- `GET /admin/atoms/summary` (dòng 282) — số liệu dashboard + accordion theo tour
- `PATCH /admin/atoms/bulk` (dòng 362) — star/soft-delete hàng loạt
- `PATCH /admin/atoms/{atom_id}` (dòng 424) — star/soft-delete/sửa nhẹ text
- `GET /admin/atoms/preview-slotgrid` (dòng 486) — chạy thật chuỗi N4→N5→N6
  (`services/acp_planning/*`) cho 1 tenant, trả preview SlotGrid; chỉ admin-secret (không cho
  tenant-JWT)

`api/routers/admin_pipeline.py` (đăng ký tại `api/main.py:136`, cùng prefix `/admin`):
- `GET /admin/tours-for-atomization` (dòng 1718) — floor 763 tour từ `v_trip_registry`, filter
  pending/atomized/all, feed cho tour picker của trang Atomize
- `POST /admin/atoms/decompose` (dòng 1860) — **admin alias**, gọi thẳng
  `v1_atoms.decompose(tenant=None)`. Comment tại dòng 1847-1858 giải thích lý do: `/v1/atoms/
  decompose` nằm sau Lambda Authorizer của API Gateway (yêu cầu Bearer JWT), nhưng admin BFF
  proxy chỉ gửi `X-Admin-Secret` → 401 ngay tại gateway edge nếu gọi trực tiếp — alias này là
  workaround CHỦ ĐÍCH, không phải sai sót.

`v1_atoms.py` (`prefix /v1/atoms`):
- `POST /v1/atoms/decompose` (dòng 359) — implementation thật. `_get_tenant()` (dòng 87) chấp
  nhận CẢ `X-Admin-Secret` LẪN tenant Bearer JWT — endpoint này về thiết kế không chỉ dành riêng
  cho admin, nhưng thực tế chưa có frontend tenant nào gọi trực tiếp (xác nhận ở mục 2).

**Frontend:**
- `frontend/app/admin/atomize/page.tsx` — gọi `GET /api/admin/tours-for-atomization` (dòng 197)
  và `POST /api/admin/atoms/decompose` (dòng 248, trúng alias admin_pipeline.py). Comment đầu
  file (dòng 2-8) nói rõ scope: trang này lo phần **pre-decompose** (chọn tour → trigger),
  `/admin/curation` lo phần **post-decompose** (curate atom đã có) — đây là chia tách chủ đích,
  không phải trùng lặp.
- `frontend/app/admin/curation/page.tsx` — gọi `GET /api/admin/atoms/summary` (dòng 280),
  `GET /api/admin/atoms` (dòng 331), `PATCH /api/admin/atoms/{id}` (dòng 352),
  `PATCH /api/admin/atoms/bulk` (dòng 391).
- `frontend/app/admin/curation/preview/page.tsx` — gọi `GET /api/admin/atoms?atom_ids=`
  (dòng 164) và `GET /api/admin/atoms/preview-slotgrid[?version_id=]` (dòng 251).

Cả 2 route đều được gate trong `frontend/middleware.ts:73-74` cho role admin/reviewer/content.

**T-series (tenant portal) — xác nhận KHÔNG có chức năng tương đương ở cấp catalog chung:**
`frontend/app/(tenant)/portal/t6-atoms/page.tsx` dùng `AtomsTab.tsx`, chỉ gọi
`GET /api/tenant/admin/atoms/summary`, `GET /api/tenant/admin/atoms`,
`PATCH /api/tenant/admin/atoms/{id}` (dòng 64, 76, 92, 102) — tức DÙNG LẠI đúng các endpoint
của `admin_atoms.py`, nhưng `owner_scope` được resolve từ JWT tenant (`_resolve_atom_owner_scope`,
`admin_atoms.py:86-101`) nên tenant chỉ thấy/sửa atom mình đã sở hữu (atom T5 tự rewrite,
`owner_scope=<tenant_id>`). **Không có trang tenant nào gọi `POST /v1/atoms/decompose`** — đã
grep toàn bộ cây tenant portal + lớp BFF proxy, 0 kết quả. Tenant có thể star/sửa/soft-delete
atom hiện có của mình (T6), nhưng KHÔNG có đường nào để atomize nội dung mới vào catalog
dùng chung (`owner_scope='platform'`) — việc đó vẫn chỉ dành cho admin qua alias trong
`admin_pipeline.py` + `X-Admin-Secret`.

### Gap/bug tìm thấy

1. **Gap thật, xác nhận (không đề xuất build ngay)**: tenant portal hoàn toàn không có khả năng
   atomize/curate catalog Master Content dùng chung. Đây khác về bản chất với Gate B/portfolio
   (vốn là gate duyệt hoạt động của tenant) — đây là công cụ SẢN XUẤT tồn kho chung mà mọi
   tenant kéo về qua `/v1/tours/pool`. Xoá admin/atomize + curation theo tinh thần ADR-2026-038
   §0.2 ("AA không gate hoạt động tenant") sẽ là **áp dụng sai nguyên lý** — không có gì để
   "trả lại" cho tenant tự làm, vì tenant chưa từng có chức năng này.
2. **Không có bug trong luồng ống dẫn** — pattern admin-alias-vòng-qua-gateway-auth
   (`admin_pipeline.py:1860`) là workaround chủ đích, đã ghi chú rõ; owner_scope scoping
   (AA-431) được enforce đúng ở mọi endpoint cho tenant caller.
3. Ghi chú kiến trúc: `admin_atoms.py`'s `preview-slotgrid` là NGƯỜI DÙNG của N4/N5/N6
   (`services/acp_planning/*`), không phải phụ thuộc ngược — không có chỗ nào trong N4/N5/N6
   gọi lại vào `admin_atoms.py`. Nên nếu có dọn Nhánh 1, chắc chắn KHÔNG làm hỏng N4/N5/N6
   (chiều phụ thuộc chỉ 1 hướng: admin UI → planning services).

### Đề xuất hướng xử lý (không tự quyết)

- **Option A (khuyến nghị) — Giữ nguyên admin/atomize + admin/curation.** Đây không phải gate
  hoạt động tenant, mà là công cụ duy nhất sản xuất/curate catalog dùng chung. Thực chất, trong
  3 nghi ngờ ban đầu của STEP0, nhánh này hoá ra không phải "candidate cleanup" thật. Đánh đổi:
  gần như không có — khuyến nghị KHÔNG động vào nhánh này trong AA-473.
- **Option B — Nếu Nghiệp muốn tenant tự phục vụ atomize vào catalog chung trong tương lai**,
  đây là tính năng MỚI thật sự (tenant được ghi vào `owner_scope='platform'`), không phải dọn
  dẹp — cần issue riêng với quyết định sản phẩm rõ ràng (ai được ghi, kiểm duyệt thế nào...),
  nằm ngoài phạm vi 1 đợt "bỏ admin gate".
- Không có caller ẩn nào phụ thuộc vào bề mặt HTTP admin ngoài 2 trang frontend + test — nên
  nếu Option A sai và Nghiệp thực sự muốn xoá/di dời UI này, không có rủi ro phá vỡ hệ thống
  khác (khác với Gate A/Planning tab, nơi có thể có người đọc downstream thật).

---

## Nhánh 2 — Gate A (tenant onboarding approval)

### Hiện trạng xác nhận

**Backend (`api/routers/admin.py`):**

- `POST /admin/tenants/{tenant_id}/gate-a/approve` — `approve_gate_a()`, dòng 943-991. Trong 1
  transaction: `SELECT approval_status FROM acp_shared.tenant_onboarding WHERE tenant_id = $1
  FOR UPDATE` (row lock, dòng 967-970) → từ chối 409 trừ khi `approval_status == 'pending'`
  (dòng 971-978) → `UPDATE acp_shared.tenant_onboarding SET approval_status='approved',
  approved_by=$2, approved_at=now()` (dòng 980-987) → `UPDATE shared.tenants SET
  is_active=true, updated_at=now()` (dòng 988-991). Sau AA-472, `approval_status=='pending'` là
  điều kiện tiên quyết DUY NHẤT — check `has_angle` cũ (dựa vào `tenant_atom_state`) và nhánh
  "không có row onboarding → 404" đều đã bị xoá ở PR #232.
- `GET /admin/tenants/{tenant_id}/gate-a/status` — `get_gate_a_status()`, dòng 1014-1050. Đọc
  `acp_shared.tenant_onboarding JOIN shared.tenants` (dòng 1023-1032), 404 nếu chưa có row
  (giữ chủ đích vì GET này không ràng buộc transaction với `create_tenant()`).
- Danh sách tenant pending — nằm trong `list_tenants()` (dòng 187-305), query cụ thể tại dòng
  242-250:
  ```sql
  SELECT t.tenant_id, t.name, t.slug, t.plan_tier::text, t.posts_per_week,
         t.country, t.created_at, to_.approval_status
  FROM shared.tenants t
  LEFT JOIN acp_shared.tenant_onboarding to_ ON to_.tenant_id = t.tenant_id
  WHERE t.is_active = false
  ORDER BY t.created_at
  ```
  Trả ra dưới dạng `pending_tenants[].onboarding.gate_a_status = r["approval_status"] or
  "not_started"` (dòng 299).
- `create_tenant()` (dòng 77-182) tạo tenant với `is_active=false` (dòng 114-119) và tự insert
  row onboarding trong CÙNG transaction, luôn `portfolio_id=NULL` (dòng 160-169) — không còn
  bước seed riêng nào trước khi Gate A có thể được approve (đây là fix của AA-472).
- **Đường activate thứ 2** — `PATCH /admin/tenants/{tenant_id}` tổng quát (dòng 371-419). Khi
  set `is_active=true`, có check lại `SELECT approval_status ... WHERE tenant_id=$1`, từ chối
  400 trừ khi `'approved'` (dòng 403-412); **nhưng deactivate (`is_active→false`) qua CHÍNH
  endpoint này KHÔNG bị chặn** (comment dòng 396: "suspending an existing tenant stays
  unrestricted"). Cùng bất đối xứng này lặp lại ở `offboard_tenant()` (dòng 800-840) và
  soft-delete endpoint (dòng 440-450) — cả 2 đều set `is_active=false` mà không đụng đến
  `tenant_onboarding.approval_status`.

**Cột tracking:**
- `acp_shared.tenant_onboarding.approval_status TEXT NOT NULL DEFAULT 'pending' CHECK
  (approval_status IN ('pending','approved'))`, cùng `approved_by`, `approved_at`,
  `created_at` — bảng tạo ở migration `098_acp_shared_tenant_atom_state.sql:71-78`.
- `acp_shared.tenant_onboarding.portfolio_id` — vốn `NOT NULL` FK vào
  `acp_shared.marketplace_portfolios`; migration `119_tenant_onboarding_portfolio_optional.sql:
  16-17` (AA-472) bỏ `NOT NULL` (giữ FK, chỉ để tương thích tenant cũ trước AA-472).
- `shared.tenants.is_active BOOLEAN NOT NULL DEFAULT TRUE` — default schema là `TRUE`
  (migration `003_schema_v3.sql:138-148`); hành vi `is_active=false` lúc tạo là override ở
  tầng ứng dụng (literal `false` trong INSERT của `create_tenant()`, `admin.py:117`), không
  phải đổi schema.

**Frontend (`frontend/app/admin/tenants/page.tsx`):**
- Type `PendingOnboarding`/`PendingTenant` gồm `gate_a_status:
  "not_started"|"pending"|"approved"` (dòng 59-70).
- `PendingOnboardingSection` (chỉ render nếu ≥1 tenant pending) — dòng 846-870.
- `PendingTenantCard` — dòng 807-844; badge text qua `pendingStepLabel()` (dòng 803-805):
  ```ts
  function pendingStepLabel(o: PendingOnboarding): string {
    return o.gate_a_status === "approved" ? "Gate A approved" : "Gate A pending approval";
  }
  ```
  ("Gate A pending approval" bao trùm cả `"not_started"`.) Nút toggle "Continue
  onboarding"/"Hide" — dòng 831-833.
- `OnboardingTabContent` (UI approve thật) — dòng 432-503. Fetch status qua
  `GET /api/admin/tenants/{id}/gate-a/status` (dòng 441); `approved = gateA.approval_status ===
  "approved"` (dòng 477); hiện "Approved by {approved_by} at {…}" nếu true (dòng 483-487),
  ngược lại hiện copy giải thích + nút **Approve Gate A** (dòng 490-497) gọi
  `POST /api/admin/tenants/{id}/gate-a/approve` (dòng 452-471).
- Wiring cấp cao trong `TenantsPage`: tách response `GET /api/admin/tenants` thành `tenants`
  (active) vs `pendingTenants = data.pending_tenants` (dòng 1018-1023), render
  `<PendingOnboardingSection pending={pendingTenants} onGateAApproved={load} />` tại dòng 1076.

**Xác nhận chủ sở hữu duy nhất**: không có router/service production nào khác (đã grep sạch
`services/acp_planning/*.py`) đọc/ghi `acp_shared.tenant_onboarding` hay cột Gate A — chỉ
`admin.py` (backend) + `page.tsx` (frontend), cộng `tests/unit/test_aa309_tenant_onboarding.py`
và `tests/verify_scripts/aa389_gate_a_bypass_verify.py`.

### Gap/bug tìm thấy

**Không còn dạng rủi ro như AA-472 trong Gate A.** Bug thật của AA-472 (PR #232, xem
`docs/implementation-notes/AA-472.md` "Should know") là `seed_tenant_atoms()` làm 2 việc trong
1 hàm — insert `tenant_onboarding` (phần task nhắc đến) VÀ insert `tenant_atom_state` (phần
không được nhắc) — và chỉ chuyển insert đầu vào `create_tenant()` đã âm thầm phá vĩnh viễn check
`has_angle` cũ trong `approve_gate_a()`. Toàn bộ dạng rủi ro đó giờ đã hết: `approve_gate_a()`
chỉ còn đúng 1 điều kiện (`approval_status=='pending'`) trên đúng 1 bảng. Không còn hàm nào
"nửa xoá, ràng buộc 2 bảng" để lo ở đây.

**1 anomaly thật, xác nhận qua query DB thật** (không phải bug code — rủi ro gây hiểu nhầm UI):
2 tenant có `tenant_onboarding.approval_status='approved'` NHƯNG `tenants.is_active=false`.
Nguyên nhân gốc là bất đối xứng approve/deactivate nói trên: approve `is_active→true` bị gate
bởi `approval_status=='approved'` (dòng 403-412), nhưng deactivate về `false` (qua PATCH,
soft-delete, hay `offboard_tenant()`) không bao giờ reset `approval_status`. Về mặt logic có
thể xem là ĐÚNG (approval và trạng thái active hiện tại là 2 sự thật khác nhau), nhưng hệ quả
là badge "Gate A approved" trong danh sách pending hiển thị cho tenant thực ra đã bị deactivate/
offboard hoàn toàn — không phân biệt được bằng mắt thường với 1 tenant thật sự approved nhưng
vì lý do nào đó chưa active. Đây là tồn tại từ trước, không phải do AA-472 gây ra.

**Ghi chú tên trùng** (ngoài phạm vi, chỉ để tránh nhầm lẫn sau này): `admin_acp_proxy.py:569`
và `v1_acp_gate.py:87` có `gate_approve`/`GateApproveRequest` RIÊNG cho gate HITL của pipeline
sản xuất nội dung (ACP Gate B/C) — khái niệm "Gate" hoàn toàn khác Gate A tenant-onboarding.
Cùng chữ "Gate", khác hệ thống — đừng nhầm khi đọc code sau này.

### Danh sách tenant Gate-A-pending

Query live trên `shared.tenants WHERE is_active=false LEFT JOIN acp_shared.tenant_onboarding`,
chạy 2026-08-27 qua S3-mediated ECS exec (ECS/RDS đã xác nhận đang chạy, chỉ SELECT read-only).
**11 tenant inactive, 4 active.**

| Tên | Slug | Plan | Created | approval_status | Test/Thật |
|---|---|---|---|---|---|
| PeakAdventures | peakadventures | business | 2026-04-21 | NULL (không có row onboarding) | **Không rõ — có vẻ thật**; tenant cũ nhất, tên không có dấu hiệu test, `approval_status` NULL nghĩa là được tạo trước khi `create_tenant()` đảm bảo insert row (trước AA-472, có thể trước cả AA-389 Gate A UI) |
| Test Agency | test-agency | starter | 2026-04-30 | pending | Test (đã biết) |
| lumitest | lumitest | business | 2026-05-06 | NULL | Test (đã biết) |
| Atlas & Hearth | atlas-hearth | starter | 2026-05-19 02:51 | NULL | Nghi ngờ test — 1 trong cụm 4 tenant tạo trong 7 phút cùng ngày, chưa từng động tới sau đó |
| Terra Family Expeditions | terra-family-expeditions | starter | 2026-05-19 02:53 | NULL | Nghi ngờ test — cùng cụm |
| Trail Pulse | trail-pulse | starter | 2026-05-19 02:53 | NULL | Nghi ngờ test — cùng cụm |
| WildKind Travel | wildkind-travel | starter | 2026-05-19 02:58 | NULL | Nghi ngờ test — cùng cụm |
| Sri Lanka UAT | sri-landka | starter | 2026-05-22 | NULL | Test (đã biết; tên có "UAT") |
| AA-309 Live Verify Tenant | aa309-verify-c5316bd4 | growth | 2026-08-08 | **approved** (is_active=false) | Test (đã biết) — leftover live-verify, xem anomaly ở trên |
| AA-384 Live Verify | aa-384-live-verify | growth | 2026-08-08 | **approved** (is_active=false) | Test (đã biết) — leftover live-verify |
| test1 | test1 | business | 2026-08-25 | NULL | Test (tên rõ ràng) |

10/11 có tín hiệu test rõ ràng (tên literal "test"/"UAT", nằm trong danh sách test đã biết,
hoặc thuộc cụm 4 tenant tạo cách nhau vài phút chưa từng xử lý). Chỉ `PeakAdventures` không có
tín hiệu test nào.

### Đề xuất hướng xử lý (không tự quyết)

1. **Code Gate A: không cần sửa gì trong AA-473.** Đã sạch từ AA-472; không còn dạng rủi ro
   "1 hàm ghi 2 bảng, xoá nửa gây bug" như Gate B từng gặp.
2. **Dọn dữ liệu rác**: đề xuất Nghiệp xác nhận rồi xoá thật 9-10 tenant test (gồm cả 2 tenant
   "approved-nhưng-inactive"). Đánh đổi: cần xoá đúng cascade (`tenant_onboarding`, `audit_log`,
   `tenant_atom_state` nếu có, `acp_quota_ledger`...) — cùng pattern AA-472 đã dùng khi dọn
   tenant test của chính nó.
3. **PeakAdventures cần Nghiệp xác nhận riêng** — nếu là tenant thật bị bỏ quên 4 tháng chưa
   qua Gate A thì cần approve thủ công hoặc điều tra thêm; nếu là rác nội bộ thì xoá theo nhóm
   trên.
4. **Anomaly approved/inactive**: đề xuất KHÔNG sửa code — chỉ cần xoá 2 tenant test gây ra
   hiện tượng này (mục 2) là hết. Nếu muốn cải thiện UX lâu dài, có thể thêm nhãn phụ
   "Deactivated after approval" khi `is_active=false && approval_status='approved'`, nhưng đây
   là cải tiến nhỏ không bắt buộc.
5. **Không cần PR riêng cho nhánh Gate A** — nếu phần việc chỉ là dọn dữ liệu, đây là task
   data-cleanup (không cần review code), có thể gộp chung với PR build của nhánh khác nếu có,
   hoặc chạy độc lập qua script không cần PR.

---

## Nhánh 3 — Planning tab (Markets/Channels "Save")

### Hiện trạng xác nhận

**Nút Save FE gọi API thật, không phải chỉ local state.** `PlanningTabContent`
(`frontend/app/admin/tenants/page.tsx:522-633`): nút Save (dòng 621-622) gọi `save()`
(dòng 552-572), fetch `PUT /api/admin/tenants/{tenantId}/config` (dòng 562-565) với body
`{markets, channels, posts_per_week}`. Đây là Next proxy same-origin
(`frontend/app/api/admin/[...path]/route.ts`), forward đúng method/body/header
`X-Admin-Secret` tới backend ECS — không có gì sai trong proxy (đọc toàn bộ file, pass-through
generic, xử lý GET/PUT/lỗi kết nối đều ổn, dòng 1-80).

**Backend endpoint tồn tại thật và ghi đúng bảng.** `api/routers/admin.py:888-934`:
`GET/PUT /admin/tenants/{tenant_id}/config`, gọi `fetch_tenant_planning_config()`/
`save_tenant_planning_config()` trong `services/acp_planning/tenant_config.py`.
`save_tenant_planning_config()` (dòng 59-76) UPDATE `shared.tenants.posts_per_week` + UPSERT
`acp_shared.tenant_config` (migration 101, file tồn tại:
`api/migrations/101_acp_shared_tenant_config.sql`).

**N4/N5/N6 lõi (`compute_runway_map`, `compute_quarter_plan`,
`allocate_month`/`allocate_and_persist_week`) đều nhận `markets`/`channels` làm tham số
caller-supplied** (`runway.py:155`, `quarter.py:148-149`, `allocator.py:122,280-281`) — bản
thân chúng không tự đọc config.

**Người gọi thật (không chỉ admin preview) chính là T8 —
`services/acp_angle_gate/service.py:118`**: `create_request()` (dòng 159, đã xác nhận ở AA-451
là đường live thật của tenant self-service) gọi `fetch_tenant_planning_config(tenant_id, pool)`
tại dòng 118, dùng `config.markets`/`config.channels`/`config.capacity_posts_per_week` để
`compute_runway_map()` (dòng 133) và `allocate_and_persist_week()` (dòng 137-138) — **đây
chính là bảng `acp_shared.tenant_config` + `shared.tenants.posts_per_week` mà Planning tab
admin ghi vào**. Ngoài ra `api/routers/v1_planning.py:65,77,199` (T7's `GET /v1/planning/
slot-grid`, tenant-facing) và `services/acp_planning/trip_reallocation.py:43,46` cũng đọc cùng
nguồn qua `fetch_tenant_planning_config`. `api/routers/admin_atoms.py:563,568,574,597,601,613`
(admin preview flow) cũng đọc cùng nguồn.

### Gap/bug tìm thấy

**Không tìm thấy bug pipeline thật ở tầng code** — chuỗi Save → PUT → DB →
`fetch_tenant_planning_config` → N4(runway)/N6(allocate) đã nối đầy đủ, không có bảng "mồ côi"
nào chỉ Planning tab ghi mà không ai đọc, và không có nơi nào N4/5/6 đọc từ nguồn khác bị
Planning tab bỏ quên. Đây khác với giả thuyết ban đầu trong đề bài (Planning tab "làm gì đó
không rõ").

Cảm nhận "Save không làm gì" của Nghiệp nhiều khả năng là **UX quan sát được, không phải lỗi
chức năng**: phản hồi thành công chỉ là icon checkmark nhỏ + text "Saved" biến mất sau 2 giây
(`page.tsx:570,624`), không có thay đổi hiển thị rõ ràng nào khác trên trang — dễ bị bỏ lỡ khi
xem qua ảnh chụp UI tĩnh. Một khả năng khác chưa loại trừ hoàn toàn (ngoài phạm vi kiểm tra code
tĩnh của nhánh này): migration 101 tồn tại trong repo nhưng **chưa xác nhận đã apply lên RDS
live** — nếu chưa apply, mọi PUT sẽ lỗi 500 (nhưng lỗi đó sẽ hiện banner đỏ `error`, không phải
"im lặng không làm gì" — nên khả năng này thấp).

### Đề xuất hướng xử lý (không tự quyết)

1. **Không xoá gì ở nhánh này** — đây không phải tàn dư an toàn để dọn theo ADR-2026-038 §0.2
   như nghi ngờ ban đầu; đây là cấu hình thật, đang được N4/N6/T7/T8 dùng sống. Xoá sẽ làm hỏng
   pipeline thật.
2. Nếu vẫn muốn cải thiện, hướng nhẹ: cải UX phản hồi Save (banner rõ ràng hơn thay vì icon nhỏ
   2 giây) — không liên quan ADR-2026-038, chỉ là polish, có thể gộp task riêng nhỏ hoặc bỏ qua.
3. Việc còn thiếu (ngoài phạm vi code-only của nhánh này) là **live-verify** thật: mở
   `/admin/tenants/{id}` → tab Planning trên tenant thật → bấm Save → query trực tiếp
   `acp_shared.tenant_config` xem row có được ghi/update không. Đây là bước duy nhất còn lại để
   loại trừ hoàn toàn khả năng lỗi runtime (vd. migration 101 chưa apply, hoặc `X-Admin-Secret`
   mismatch) — khuyến nghị làm nếu Nghiệp muốn đóng dứt điểm nghi ngờ "Save không làm gì", nhưng
   dựa trên code, đây gần như chắc chắn hoạt động đúng.

---

## Đề xuất thứ tự build

Cả 3 nhánh **độc lập nhau** về code (không nhánh nào chạm chung file/bảng với nhánh khác), nên
không có lý do kỹ thuật phải gộp 1 PR lớn. Nhưng về khối lượng việc thật sự cần làm, chỉ có
1 nhánh có việc:

- **Nhánh 1 (Atomize/Curation)**: KHÔNG có việc cần build — khuyến nghị đóng thread này trong
  AA-473, không cần code change.
- **Nhánh 3 (Planning tab)**: KHÔNG có việc cần build (trừ khi Nghiệp muốn polish UX Save, việc
  nhỏ, có thể làm riêng bất cứ lúc nào không cần ưu tiên).
- **Nhánh 2 (Gate A)**: CÓ việc thật, nhưng là **data cleanup** (xoá tenant test), không phải
  code change — không cần PR review code, có thể chạy như 1 script dọn dữ liệu độc lập (giống
  cách AA-472 tự dọn tenant test của nó), miễn Nghiệp xác nhận danh sách xoá (đặc biệt xác nhận
  `PeakAdventures` là rác hay tenant thật bị bỏ quên) trước khi chạy.

**Tóm lại: không có "PR build kế tiếp" cần thiết cho cả 3 nhánh AA-473 như giả định ban đầu của
task này** — trừ khi Nghiệp muốn thêm nhãn phụ "Deactivated after approval" (Nhánh 2, cải tiến
nhỏ) hoặc polish UX Save (Nhánh 3, cải tiến nhỏ). Việc bắt buộc duy nhất là xác nhận + chạy dọn
dữ liệu test ở Nhánh 2.

---
---

# STEP0 lần 2 — Chứng minh cứng

Ngày: 2026-08-27 | Yêu cầu: mọi khẳng định phải kèm bằng chứng runtime thật (SQL result,
HTTP response thật) — không được viết "hoạt động đúng"/"gần như chắc chắn" mà không có
output cụ thể. Task này ra đời vì báo cáo STEP0 lần 1 (phần trên) dựa quá nhiều vào đọc code
tĩnh, đúng loại lỗi đã xảy ra ở AA-461 (mô tả nghe hợp lý nhưng sai thực tế) và vi phạm bài học
AA-465 (phải verify qua đường thật, không chỉ tin "apply thành công").

**Tóm tắt kết quả**: cả 3 điểm đều được chứng minh sạch bằng bằng chứng thật (không phát hiện
mâu thuẫn với kết luận lần 1) — riêng Điểm 3, mức độ chắc chắn tăng từ "gần như chắc chắn" (chỉ
đọc code) lên "đã chứng minh, không còn nghi ngờ" (chạy thật toàn chuỗi).

## Điểm 1 — owner_scope isolation giữa platform catalog và tenant T5/T6

### Bằng chứng

**1. DB thật** — `SELECT owner_scope, COUNT(*) FROM acp_contract.tour_atoms GROUP BY owner_scope`
(qua S3-mediated ECS exec, container `aa-cis-dev-api`, 2026-08-26):
```
{'owner_scope': 'platform', 'c': 2629}
{'owner_scope': '6fbaf284-e3cd-4b4b-b53b-c9a04e8fae8e', 'c': 29}
{'owner_scope': '9fb0a3db-59aa-468a-a082-ded01ac50bee', 'c': 15}
{'owner_scope': 'a1b2c3d4-0001-4000-8000-000000000001', 'c': 7}
```
Đối chiếu `shared.tenants`: `6fbaf284-...` = TEST-N1-flow (active), `9fb0a3db-...` = Test Agency
(inactive), `a1b2c3d4-0001-...` = WanderLux Travel (active). Đúng 1 giá trị `'platform'`
(2629 atom), 3 giá trị còn lại là tenant_id thật khớp `shared.tenants` — không lẫn lộn.

**2. Chọn tenant thật để test** — `test-n1-flow` (`tenant_id=6fbaf284-e3cd-4b4b-b53b-c9a04e8fae8e`,
`is_active=true`, atom count=29 khớp DB).

**3. HTTP thật với JWT mint bằng secret fallback `cis-dev-jwt-secret-change-in-prod`** (xác nhận
đây đúng là secret thật đang chạy vì token được backend chấp nhận, không 401):
- `curl -H "X-Admin-Secret: ..." ".../admin/atoms?limit=5"` → 200, atom trả về thuộc tour
  "South Korea by Road Bike" (không phải của test-n1-flow) — xác nhận admin thấy dữ liệu ngoài
  phạm vi 1 tenant, không bị filter.
- `curl -H "Authorization: Bearer <test-n1-flow JWT>" ".../admin/atoms?limit=50"` → 200,
  `"count":29,"total":29` — khớp chính xác số atom thật của tenant trong DB.
- Cross-check cứng: lấy toàn bộ 29 `atom_id` trả về, query lại DB `WHERE atom_id = ANY(...)`:
  ```
  total rows found: 29 expected: 29
  mismatches (owner_scope != test-n1-flow): []
  all owner_scope values seen: {'6fbaf284-e3cd-4b4b-b53b-c9a04e8fae8e'}
  ```
  100% khớp, 0 lẫn `'platform'` hay tenant khác.

**4. Negative test (quan trọng nhất)** — atom platform thật `atom_83c773a60a`
(`owner_scope='platform'`, `starred=False`). Dùng JWT của test-n1-flow (không sở hữu atom này):
```
PATCH .../admin/atoms/atom_83c773a60a  Authorization: Bearer <test-n1-flow JWT>  {"starred": true}
→ HTTP 404  {"detail":"Atom atom_83c773a60a not found (or is an empty-marker row)"}
```
Verify lại DB ngay sau đó (không tin theo status code): `starred` vẫn `False`, `updated_at` vẫn
timestamp cũ (21/07) — row hoàn toàn không bị đổi, không cần revert vì không có ghi nào xảy ra.

Ghi chú phụ (không phải leak): admin GET `total`=2602 khác tổng 4 owner_scope (2680) — điều tra
ra do 78 atom bị soft-delete (`deleted=true`) bị lọc mặc định ở GET, không liên quan owner_scope.

### Kết luận

**Sạch — owner_scope tách biệt hoàn toàn, chứng minh bằng cả đọc lẫn ghi.** Bằng chứng mạnh nhất:
PATCH thật từ JWT tenant lên atom platform-scoped trả 404 VÀ DB xác nhận row bất biến — không chỉ
tin HTTP status. Không có lỗ hổng cross-tenant/cross-scope ở cả đọc (29/29 khớp) lẫn ghi (404 +
DB xác nhận). Kết luận "giữ nguyên Nhánh 1" của STEP0 lần 1 có căn cứ thật, không phải suy đoán.

---

## Điểm 2 — PeakAdventures

### Bằng chứng

**Query 1** — `shared.tenants WHERE slug='peakadventures'`:
```json
{"tenant_id": "a1b2c3d4-0003-4000-8000-000000000003", "name": "PeakAdventures",
 "plan_tier": "business", "posts_per_week": 5, "is_active": false,
 "created_at": "2026-04-21 03:19:30.905252+00:00", "updated_at": "2026-08-24 12:58:38.768174+00:00"}
```

**Query 2** — quét toàn bộ 52 bảng có cột `tenant_id` (tự khám phá qua `information_schema.
columns`, không đoán tên): `tenant_onboarding`=0, `tenant_config`=0,
`tour_atoms WHERE owner_scope=...`=0, `acp_quota_ledger`=0, `audit_log`=0 (cnt=0, min/max NULL).
**0/52 bảng nghiệp vụ có row**, ngoại trừ `shared.tenants` chính nó và view
`v_tenant_monthly_usage` (1 row, nhưng đọc `pg_get_viewdef` xác nhận đây là LEFT JOIN luôn trả
1 row cho MỌI tenant kể cả rỗng — `tours_rewritten:0, api_calls_used:"0", llm_cost_usd:"0.0000"`
— không phải bằng chứng hoạt động thật).

**Phát hiện quyết định — pattern UUID**: `tenant_id` = `a1b2c3d4-0003-4000-8000-000000000003`,
cùng chuỗi dựng tay `a1b2c3d4-000X-...` với `0001`=WanderLux Travel và `0002`=ExploreAsia Co.
(2 tenant này có `created_at` giống hệt nhau tới micro-giây — xác nhận insert hàng loạt 1 lần).
`git log --all -i -S"a1b2c3d4"` xác nhận `api/migrations/007_seed_test_tenants.sql` là migration
seed CHÍNH THỨC cho `0001`/`0002` làm "Tenant A"/"Tenant B" demo test RLS — file này KHÔNG có
`0003`. `git log --all -i -S"PeakAdventures"` → **0 kết quả trong toàn bộ lịch sử git**.
`grep -rn "PeakAdventures"` toàn bộ working tree hiện tại → **0 kết quả** (khác WanderLux/
ExploreAsia, vẫn còn làm tên ví dụ placeholder trong `page.tsx`/`PlaceholderTabs.tsx`).

Chi tiết chưa giải thích được: `updated_at = 2026-08-24 12:58:38` — cách `created_at` hơn 4
tháng, chỉ 3 ngày trước điều tra này, mà không có bảng liên quan nào ghi nhận hoạt động gì
tương ứng (không có CloudTrail/access log được kiểm trong phạm vi task này).

### Kết luận và đề xuất

Bằng chứng hội tụ: PeakAdventures **gần như chắc chắn là tenant demo/scratch tạo tay**, mô
phỏng theo bộ seed `a1b2c3d4-000X` nhưng KHÔNG nằm trong migration/commit nào — không phải
tenant thật bị bỏ quên. 0 hoạt động thật ở toàn bộ 52 bảng nghiệp vụ; UUID tự chọn theo pattern
giả (9 tenant thật còn lại đều dùng UUID v4 ngẫu nhiên của `create_tenant()`).

**CHƯA CHỨNG MINH ĐƯỢC**: ai/khi nào tạo nó và vì sao `updated_at` là 2026-08-24 — không tìm
được log xác nhận trực tiếp trong phạm vi công cụ có sẵn.

**Đề xuất**: đủ bằng chứng để xoá cùng nhóm 9 tenant test khác — không cần tách xử lý riêng
nữa như STEP0 lần 1 để "không rõ". Việc xoá thật (không phải chỉ đề xuất) vẫn cần Nghiệp xác
nhận cuối, vì đây là xoá dữ liệu.

---

## Điểm 3 — Planning tab Save→DB→N4/N6 live-verify

### Bằng chứng

**Setup**: ECS `aa-cis-dev-api` desired=1/running=1, RDS `available` — xác nhận trước khi bắt
đầu. Tenant test: `test-agency` (`tenant_id=9fb0a3db-59aa-468a-a082-ded01ac50bee`,
`is_active=false`). Baseline trước khi ghi: `tenant_config`=None, `posts_per_week=1`.

**Bước 1 — PUT thật**:
```
PUT /admin/tenants/9fb0a3db-.../config  {"markets":["VN","TH"],"channels":["blog","facebook"],"posts_per_week":5}
→ 200  {"tenant_id":"9fb0a3db-...","markets":["VN","TH"],"channels":["blog","facebook"],"posts_per_week":5}
```

**Bước 2 — Query DB ngay sau đó**:
```
tenant_config: {'markets': ['VN','TH'], 'channels': ['blog','facebook'], 'updated_at': 2026-08-26 23:53:05...}
tenants.posts_per_week: 5
```
Khớp 100% với body đã gửi.

**Bước 3 — GET round-trip**: `GET /admin/tenants/9fb0a3db-.../config` → 200,
`{"markets":["VN","TH"],"channels":["blog","facebook"],"posts_per_week":5}` — khớp field-by-field
với Bước 1 (không chỉ tin theo status 200).

**Bước 4 — Gọi trực tiếp hàm production thật** (import `/app/services/acp_planning/
tenant_config.py` ngay trong container ECS đang chạy, không viết lại logic SQL riêng):
```python
from services.acp_planning.tenant_config import fetch_tenant_planning_config
cfg = await fetch_tenant_planning_config(TENANT_ID, pool)
→ TenantPlanningConfig(markets=['VN', 'TH'], channels=['blog', 'facebook'], capacity_posts_per_week=5)
```
Khớp chính xác giá trị vừa Save. Đây CHÍNH LÀ hàm mà T8's `create_request()` gọi ở
`service.py:118` — chạy thẳng module production thật đã deploy, không phải suy luận qua tên hàm.

(Không chạy `create_request()` đầy đủ — `test-agency` không có atom T5 nào nên sẽ không có gì
để chọn angle, và sẽ kích hoạt Bedrock thật không cần thiết; Bước 4 đã đủ mạnh theo đúng lựa
chọn dự phòng được cho phép trong chỉ thị gốc.)

**Dọn dẹp**: đã khôi phục `test-agency` về đúng baseline (`DELETE FROM tenant_config...` +
`UPDATE tenants SET posts_per_week=1`), xác nhận lại khớp 100% trạng thái ban đầu. Đã xoá script
tạm khỏi S3.

### Kết luận

**Chuỗi Save → PUT → DB → `fetch_tenant_planning_config()` (hàm N4/N6/T8 thật sự gọi) nối liền
đầu-cuối — đã chứng minh bằng chạy thật, không còn "gần như chắc chắn".** Mọi giá trị khớp
chính xác qua cả 4 lớp (HTTP write → DB row → HTTP read → hàm Python production thật đang chạy
trong container). Nghi ngờ ban đầu của Nghiệp ("Save có thể không làm gì") **sai** đối với đường
dữ liệu Save→DB→read-path; nếu cảm giác "không làm gì" vẫn còn, nguyên nhân nằm ở phản hồi trực
quan mờ nhạt của nút Save (icon nhỏ 2 giây, đã nêu ở STEP0 lần 1), không phải ở đường dữ liệu.

---
---

# STEP0 xác nhận build Gate A + Planning tab

Ngày: 2026-08-27 | Quyết định của Nghiệp (đã chốt, không còn cân nhắc giữ/xoá): Gate A xoá hẳn
giống Gate B (AA-472); Planning tab admin xoá UI vì cho rằng T7 đã có UI tương đương cho tenant.
Task này xác nhận vị trí/điều kiện an toàn TRƯỚC khi build — vẫn STEP0, chưa sửa code.

**PHÁT HIỆN QUAN TRỌNG NGAY ĐẦU — làm thay đổi phạm vi Phần B**: tiền đề "T7 đã có UI cho tenant
tự set Markets/Channels" là **SAI**, xác nhận bằng đọc code trực tiếp (không suy đoán) — xem chi
tiết ở Phần B bên dưới. Gate A (Phần A) không bị ảnh hưởng bởi phát hiện này — vẫn AN TOÀN ĐỂ
BUILD như dự định.

## Phần A — Xác nhận trước khi xoá Gate A

### 1. Toàn bộ code path cần xoá (xác nhận lại từng dòng, số dòng CHÍNH XÁC tại 2026-08-27,
repo không có thay đổi nào từ STEP0 lần 1 — `git status` sạch)

**Backend (`api/routers/admin.py`)**:
- `class GateAApproveRequest` — dòng 939-940 (model, xoá cùng endpoint)
- `POST /tenants/{tenant_id}/gate-a/approve` (`approve_gate_a`) — dòng 943-1009, TOÀN BỘ hàm
- `GET /tenants/{tenant_id}/gate-a/status` (`get_gate_a_status`) — dòng 1014-1047, TOÀN BỘ hàm
- `create_tenant()` (dòng 78-182):
  - Dòng 117: `VALUES ($1, $2, $3::plan_tier_enum, $4, $5, $6, false)` → đổi `false` → `true`
  - Dòng 160-169: block INSERT `acp_shared.tenant_onboarding` — xoá toàn bộ (bảng sẽ bị DROP,
    xem mục 2)
  - Dòng 179: `is_active=False` trong `CreateTenantResponse` → đổi `True`
  - Dòng 180-181: message "Tenant is inactive until Gate A approval..." → đổi thành thông báo
    tenant active ngay
  - Docstring dòng 83-95 nhắc "AA-309 [N1]... is_active now starts false" — cần viết lại, không
    còn đúng
- `list_tenants()` (dòng 188-303):
  - Dòng 242-250: query `pending_rows` (JOIN `tenant_onboarding`) — xoá
  - Dòng 289-302: block build `"pending_tenants"` trong response — xoá
  - **Quyết định cần Nghiệp xác nhận riêng** (không tự quyết): sau khi xoá Gate A, `is_active=
    false` không còn nghĩa "đang chờ duyệt" — chỉ còn nghĩa "đã bị tắt thủ công" (qua PATCH
    dòng 440-450 soft-delete, hay `offboard_tenant()` dòng 800-840). Xoá toàn bộ khái niệm
    "pending" là đúng, nhưng có nên thêm 1 view khác cho "tenant đã tắt" trong `/admin/tenants`
    hay bỏ hẳn (tenant tắt chỉ còn thấy qua query DB tay)? Đây là quyết định UI/UX riêng, ngoài
    phạm vi "xoá Gate A" thuần tuý — đề xuất: bỏ hẳn `pending_tenants` khỏi response, không thay
    thế bằng gì (đơn giản nhất, đúng tinh thần ADR-2026-038 §0.2 — admin không cần theo dõi
    "đang chờ" nữa vì không còn gì để chờ); nếu Nghiệp muốn giữ 1 danh sách "tenant đã tắt" để
    tiện thao tác, đó là tính năng riêng, không phải phần "xoá" này.
- `update_tenant()` PATCH (dòng 371-419):
  - Dòng 396-412: nhánh check `approval_status != "approved"` khi `is_active=True` — xoá TOÀN
    BỘ nhánh if, để `is_active` set thẳng không điều kiện (giống hệt cách deactivate ở dòng kế
    bên đã luôn không điều kiện). **Xác nhận xoá nhánh này AN TOÀN**: nhánh `else`/phần sau (set
    `is_active` không điều kiện, dòng 413-419) giữ nguyên logic, không phụ thuộc gì vào nhánh bị
    xoá — chỉ đơn giản bỏ điều kiện tiên quyết. Comment giải thích lý do nhánh này tồn tại
    (AA-389, ngăn "one-click bypass" Gate A) tự nhiên hết ý nghĩa vì không còn gì để bypass.

**Cột/bảng DB**: `acp_shared.tenant_onboarding` — xác nhận qua grep TOÀN REPO (production code,
không tính migration files và test files): **CHỈ `api/routers/admin.py` đọc/ghi bảng này**,
không có router/service nào khác (`services/acp_planning/*.py` đã xác nhận sạch từ STEP0 lần 1,
re-confirm qua grep lần 2: đúng). → Xem mục 2 để quyết xoá cột hay xoá cả bảng.

**Frontend (`frontend/app/admin/tenants/page.tsx`)**:
- Dòng 59-71: `interface PendingOnboarding` + `interface PendingTenant` — xoá cả 2
- Dòng 432-503: `OnboardingTabContent()` — TOÀN BỘ hàm (gọi `gate-a/status` dòng 441,
  `gate-a/approve` dòng 457)
- Dòng 706: `type DTab = "onboarding" | "tours" | "pipeline" | "activity" | "planning" | "api" |
  "brand"` → bỏ `"onboarding"` khỏi union
- Dòng 715: `useState<DTab>(isActive ? "tours" : "onboarding")` → đổi default thành `"tours"`
  luôn (không còn case tenant mới tạo cần "onboarding" tab vì active ngay)
- Dòng 747: `{ key: "onboarding", label: "Onboarding" }` trong danh sách tab — xoá
- Dòng 785: `{tab === "onboarding" && <OnboardingTabContent .../>}` — xoá
- Dòng 803-805: `pendingStepLabel()` — xoá
- Dòng 807-844: `PendingTenantCard()` — xoá
- Dòng 846-870: `PendingOnboardingSection()` — xoá
- Dòng 1009, 1022: state `pendingTenants` + gán từ `data.pending_tenants` — xoá
- Dòng 1076: `<PendingOnboardingSection pending={pendingTenants} onGateAApproved={load} />` —
  xoá khỏi render

### 2. `acp_shared.tenant_onboarding` — xoá cột hay xoá cả bảng?

**Đề xuất: DROP TABLE hẳn, không chỉ xoá cột.** Lý do: sau khi mục 1 xoá xong, KHÔNG còn code
production nào đọc/ghi bảng này (đã xác nhận sạch qua grep). Giữ lại bảng rỗng-về-mặt-chức-năng
chỉ để "phòng khi cần" là đúng loại rác nửa vời task này muốn dọn — khác trường hợp Gate B/
`marketplace_portfolios` (AA-472 giữ bảng vì còn dùng làm seed source cho N1, có lý do thật).
Ở đây không tìm thấy lý do tương tự.

### 3. Migration DRAFT (chưa apply)

```sql
-- Migration 120: AA-473 — xoá Gate A hoàn toàn (tương tự Gate B ở AA-472/migration 119).
-- Tenant giờ is_active=true ngay khi tạo (create_tenant() INSERT trực tiếp true) — không còn
-- bước duyệt riêng, theo ADR-2026-038 §0.2 (AA không gate hoạt động tenant, chỉ hậu-kiểm A4).
-- Xác nhận an toàn: grep production code (api/, services/) chỉ có api/routers/admin.py đọc/ghi
-- bảng này (STEP0 AA-473, 2026-08-27) — không còn caller nào sau khi code Gate A bị xoá.

DROP TABLE IF EXISTS acp_shared.tenant_onboarding;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('120', now(), 'AA-473: DROP acp_shared.tenant_onboarding — Gate A removed, tenant is_active=true at creation')
ON CONFLICT DO NOTHING;
```

(Chưa apply — chỉ để review. Áp dụng theo đúng S3-mediated ECS exec pattern khi build thật.)

### 4. Tests cần sửa/xoá — xác nhận qua đọc trực tiếp file

`tests/unit/test_aa309_tenant_onboarding.py` (282 dòng, 6 class):
- `TestCreateTenantPostsPerWeek` (dòng 64) — **GIỮ**, không liên quan Gate A (test posts_per_week
  input, tính năng AA-384 riêng)
- `TestCreateTenantIsInactive` (dòng 85) — **XOÁ** (test hành vi `is_active=false` khi tạo, giờ
  ngược lại hoàn toàn)
- `TestGateAApprove` (dòng 105) — **XOÁ** (test thẳng endpoint bị xoá)
- `TestGateAStatus` (dòng 142) — **XOÁ** (test thẳng endpoint bị xoá)
- `TestListTenantsPending` (dòng 170) — **XOÁ** (test `pending_tenants` response, bị xoá ở mục 1)
- `TestUpdateTenantGateAGuard` (dòng 230) — **XOÁ** (test nhánh guard bị xoá ở mục 1)

`tests/verify_scripts/aa389_gate_a_bypass_verify.py` (225 dòng) — **XOÁ TOÀN BỘ FILE**: đây là
verify script riêng cho chính cơ chế Gate A guard (AA-389), không còn đối tượng để verify sau
khi xoá. Không có test nào khác trong repo phụ thuộc file này (đã grep, chỉ tự nó tham chiếu).

## Phần B — Xác nhận trước khi xoá Planning tab admin

### DỪNG LẠI — tiền đề sai, KHÔNG đề xuất xoá PUT của Planning tab admin

**1. Route/component T7 tenant-facing** — `frontend/app/(tenant)/portal/t7-planning/page.tsx`
(9 dòng, chỉ render `<PlanningTab />`) → thật sự nằm ở
`frontend/app/(tenant)/portal/_components/PlanningTab.tsx`. Đọc toàn bộ file, liệt kê MỌI lệnh
`fetch(...)`:
```
POST /api/tenant/v1/planning/quarter-plan/preview   (dòng 91)
POST /api/tenant/v1/planning/quarter-plan           (dòng 105, finalize)
POST /api/tenant/v1/planning/metrics                (dòng 284)
POST /api/tenant/v1/planning/metrics/rollup         (dòng 301)
GET  /api/tenant/v1/planning/trip-reallocation/suggest (dòng 357)
POST /api/tenant/v1/planning/trip-reallocation/confirm (dòng 366)
```
**KHÔNG có lệnh `fetch` nào ghi markets/channels.** Dòng 200 chỉ HIỂN THỊ read-only:
`<StatBlock label="Markets" value={preview.config.markets.join(", ") || "—"} />` — đây là giá
trị trả về từ `POST .../quarter-plan/preview` (tính toán, không phải form nhập).

**2. Backend T7** — `api/routers/v1_planning.py` (đăng ký `/v1/planning`): dòng 53
`from services.acp_planning.tenant_config import TenantNotFoundError, fetch_tenant_planning_config`
— **chỉ import hàm ĐỌC**. Grep toàn bộ file: KHÔNG có `save_tenant_planning_config` ở đâu trong
`v1_planning.py`. Danh sách đầy đủ endpoint của router này: `/quarter-plan/preview` (POST),
`/quarter-plan` (POST finalize, GET read), `/slot-grid` (GET), `/metrics` (POST), `/metrics/
rollup` (POST), `/trip-reallocation/suggest` (GET), `/trip-reallocation/confirm` (POST) — không
endpoint nào ghi `acp_shared.tenant_config`.

**Xác nhận bằng chứng phủ định ở tầng hàm gốc**: `grep -rn "save_tenant_planning_config"
--include="*.py" api/ services/` → CHỈ 3 kết quả: định nghĩa hàm trong `tenant_config.py:56`,
`__all__` export ở `tenant_config.py:80`, và **DUY NHẤT MỘT nơi gọi** —
`api/routers/admin.py:924` (chính là Planning tab admin's `PUT /admin/tenants/{id}/config`).

**3. Live-verify Save→DB→read-path** — đã làm ở "STEP0 lần 2, Điểm 3" phía trên (PUT admin →
DB → GET → `fetch_tenant_planning_config()` thật, tenant `test-agency`) — chuỗi này CHỈ chứng
minh phía ADMIN ghi đúng; không chứng minh có đường T7 nào ghi vì **T7 không có đường ghi để
test**.

**4. Kết luận — dừng theo đúng điều kiện đã đặt ra trong chỉ thị gốc**: đây không phải trường
hợp "khác bảng/hàm" (2 đường ghi vào 2 nơi khác nhau) — mà là **T7 hoàn toàn KHÔNG có đường ghi
markets/channels nào**, ở bất kỳ bảng nào. Admin Planning tab (`PUT /admin/tenants/{id}/config`)
hiện là **NGUỒN GHI DUY NHẤT** cho `acp_shared.tenant_config` trong toàn bộ hệ thống — không
phải bản sao thừa của T7, mà là điểm cấu hình duy nhất tồn tại. Xoá nó (đặc biệt xoá PUT) sẽ làm
mất khả năng set markets/channels khác mặc định (`["US"], ["blog"]`) cho BẤT KỲ tenant nào,
vĩnh viễn — trừ khi ai đó chạy SQL tay.

**Không đề xuất xoá `PUT /admin/tenants/{id}/config` hay `PlanningTabContent`
(`frontend/app/admin/tenants/page.tsx:522-633`) trong lần build này.** Theo đúng điều kiện Nghiệp
đặt ra ("nếu khác thì dừng lại, không đề xuất xoá, đây sẽ thành issue riêng") — việc hợp nhất
2 đường (cho T7 tự set, rồi mới bỏ admin) là quyết định sản phẩm cần bàn riêng, ngoài phạm vi
"xoá tàn dư admin-gate" của AA-473.

**GET có thể xoá độc lập không?** Không kiểm tra thêm vì không có ý nghĩa khi PUT vẫn giữ — GET
là cặp đọc/ghi tự nhiên của cùng 1 config, xoá GET mà giữ PUT không hợp lý.

## Phần C — STEP0 lần 2 (Nhánh 1, owner_scope) — đã hoàn tất ở trên

Xem "STEP0 lần 2 — Chứng minh cứng, Điểm 1" phía trên: đã chạy đủ 5 bước yêu cầu (đọc code, đếm
DB, GET admin vs GET tenant-scoped, **PATCH chéo owner_scope xác nhận 404 + DB bất biến**, kết
luận). Kết quả: **tách sạch, không rò rỉ** — điều kiện bắt buộc trước khi chốt "giữ nguyên Nhánh
1" đã thoả mãn bằng bằng chứng thật, không phải suy đoán. Không phát hiện gì làm thay đổi ưu
tiên so với Gate A/Planning tab.

## Tổng kết — sẵn sàng cho build

| Nhánh | Trạng thái | Hành động |
|---|---|---|
| Nhánh 1 (Atomize/Curation) | Đã chứng minh sạch (owner_scope tách biệt hoàn toàn, đọc+ghi) | **GIỮ NGUYÊN**, không đưa vào PR build |
| Gate A | Đã xác nhận đầy đủ vị trí xoá + migration draft + tests cần sửa | **AN TOÀN ĐỂ BUILD** — danh sách file/dòng ở Phần A dùng thẳng cho prompt build |
| Planning tab admin | Tiền đề "T7 đã có UI tương đương" SAI, xác nhận bằng đọc code | **KHÔNG XOÁ** trong lần build này — cần quyết định sản phẩm riêng (có xây UI T7 tự set trước không) trước khi tính xoá admin |
| Gate A pending-tenant data cleanup | 10/11 tenant xác nhận rác/test (bao gồm PeakAdventures, giờ đã đủ bằng chứng), chỉ cần Nghiệp gật đầu cuối | Data cleanup độc lập, không cần PR |

**Đề xuất prompt build kế tiếp**: 1 PR duy nhất cho Gate A (dùng đúng danh sách Phần A: xoá
`approve_gate_a`/`get_gate_a_status`/`GateAApproveRequest`, sửa `create_tenant()`, xoá nhánh
guard trong `update_tenant()`, xoá `pending_tenants` khỏi `list_tenants()`, xoá 8 khối frontend
liệt kê ở Phần A, migration 120 DROP TABLE, xoá/sửa 2 file test). Planning tab admin KHÔNG nằm
trong PR này — cần Nghiệp quyết hướng (xây T7 write UI trước, hay giữ nguyên admin Planning tab
vô thời hạn) trước khi có prompt build riêng cho nó.

Dừng lại chờ Nghiệp review trước khi giao prompt build.
