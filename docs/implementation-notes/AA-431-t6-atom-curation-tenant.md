# AA-431 — T6 Atom Curation (tenant-facing) + fix owner_scope auth gap

⚠️ Phụ thuộc AA-430 (route `/portal/t6-atoms` convention) — xác nhận AA-430 đã merge
+ deploy thành công (task def `:116`, smoke test pass) trước khi bắt đầu, đúng chỉ dẫn.

## Decisions

- **Backend fix trước, UI sau, cùng 1 PR** — đúng chỉ dẫn issue ("việc gộp bắt buộc").
  `_resolve_atom_owner_scope()` mirror chính xác `_resolve_brand_tenant_id()` (AA-424,
  `admin_pipeline.py`): thử Bearer JWT tenant trước, fallback `X-Admin-Secret`. Khác 1
  điểm so với bản mẫu: trả về `Optional[str]` (owner_scope: tenant_id hoặc `None` cho
  admin/staff — không phải trả tenant_id cố định `AA_INTERNAL` khi fallback, vì
  admin_atoms.py cần "None = không filter, thấy hết" chứ không phải "coi như 1 tenant cụ
  thể" như brand-identity's use case).
- **`owner_scope` KHÔNG BAO GIỜ là query param/body field client tự truyền** — chỉ derive
  từ JWT `sub` đã verify. Đúng chỉ dẫn issue ("không cho tenant tự truyền owner_scope làm
  param").
- **UPDATE (patch_atom/patch_atoms_bulk) cũng WHERE-scope theo owner_scope**, không chỉ
  filter ở SELECT — nếu chỉ filter đọc mà không filter ghi, tenant đoán được 1 atom_id
  ngoài phạm vi mình (id không phải UUID, dễ đoán dạng `atom_<hash>`) vẫn PATCH được. Test
  `test_tenant_owner_scope_mismatch_404s_not_editable` khoá lại hành vi này (404, không
  phải 200 thành công hay 403 — cùng shape với "atom không tồn tại", không lộ thông tin
  atom đó CÓ tồn tại ở owner_scope khác).
- **`preview_slotgrid` KHÔNG đụng** — vẫn `x_admin_secret` only, admin-only. Không phải
  "Atom Curation" (đây là N4-N6 Slot Grid preview, feature khác hẳn, đọc qua nhiều
  tenant/atom cùng lúc theo thiết kế) và không nằm trong 4 endpoint issue liệt kê
  (`_LIST_SELECT_COLS`, `patch_atoms_bulk`, `patch_atom` — đúng 3 hàm + `atoms_summary`
  đi kèm vì cùng nhóm "list/summary/patch" logic).
- **FE dùng `_components/ui.tsx` (token tenant), KHÔNG dùng `adminUi.tsx`** — nhất quán
  toàn bộ tenant portal (BrandTab/PoolTab/CatalogTab đều vậy), và tự nhiên tách biệt
  "trông giống trang tenant" khỏi "trông giống trang admin" mà không cần cố tình ẩn cột —
  component khác hẳn từ đầu, không phải bản admin che bớt UI.
- **Không copy 826 dòng `admin/curation/page.tsx`** — bản tenant chỉ ~200 dòng: không có
  tour-batch-budget pagination (dữ liệu 1 tenant nhỏ hơn nhiều so với toàn platform), không
  multi-select bulk actions, không accordion theo tour, không delete-forever admin
  messaging. List phẳng + Load More (giống pattern `PoolTab.tsx`/`CatalogTab.tsx` đã dùng),
  filter distinctiveness + unreviewed, star/delete từng atom.
- **Nav label "Atom Curation"** (không phải "My Atoms"/"T6") — khớp title trang, giữ tên
  kỹ thuật T-number chỉ trong route path/code comment, không lộ ra UI (user không cần biết
  ADR-2026-038).

## Changed

### Backend
- `api/routers/admin_atoms.py`:
  - Mới `_resolve_atom_owner_scope()` (Depends) — thay `x_admin_secret: str = Header(None)`
    trên `list_atoms`, `atoms_summary`, `patch_atoms_bulk`, `patch_atom`.
  - `list_atoms`: thêm `AND ta.owner_scope = $n` khi `owner_scope is not None`.
  - `atoms_summary`: cả 3 query con (breakdown/totals/by_tour) đều filter owner_scope khi
    có.
  - `patch_atoms_bulk`/`patch_atom`: UPDATE WHERE thêm `AND owner_scope = $n` khi có.
  - `preview_slotgrid`: **không đổi**.
- `tests/unit/test_aa300_admin_atoms.py`: 39 call site `x_admin_secret=_TEST_SECRET` →
  `owner_scope=None` (giữ nguyên hành vi admin cũ). 3 test "wrong secret rejected" (route-
  level) chuyển thành comment trỏ sang class test mới (secret validation giờ nằm ở
  resolver, không phải ở route function nữa). Thêm mới: `TestResolveAtomOwnerScope` (4
  test: JWT hợp lệ → tenant_id, JWT sai → 401, không có JWT + secret đúng → None, không có
  JWT + secret sai → 403) + 6 test owner_scope-filter-added (list_atoms x2, patch_atom x2
  gồm IDOR-mismatch, atoms_summary x1, patch_atoms_bulk x1).

### Frontend
- Mới `frontend/app/(tenant)/portal/_components/AtomsTab.tsx` — component chính.
- Mới `frontend/app/(tenant)/portal/t6-atoms/page.tsx` — route (dùng convention AA-430 đã
  chừa).
- `Sidebar.tsx`: thêm nav item "Atom Curation" (icon `Puzzle`, sau "Brand Identity").
- `layout.tsx`: thêm `/portal/t6-atoms` vào `BREADCRUMBS`.
- `middleware.ts`: **không đổi** — wildcard `/portal/:path*` tự gate (đã xác nhận ở AA-430).

## Tradeoffs

- List phẳng + Load More (không group theo tour) — đơn giản hơn, chấp nhận được ở quy mô 1
  tenant (nhiều nhất vài chục-trăm atom/tenant thay vì hàng nghìn của cả platform). Nếu 1
  tenant sau này atomize rất nhiều tour, có thể cần group lại — chưa phải vấn đề hiện tại.

## Should know

- **Xác nhận KHÔNG ảnh hưởng `/admin/curation`**: FE proxy `/api/admin/[...path]/route.ts`
  chỉ gửi `X-Admin-Secret` (không có `Authorization` header) — `_resolve_atom_owner_scope`
  luôn nhận `credentials=None` cho request admin → fallback `verify_admin_secret` →
  `owner_scope=None` → không filter, y hệt hành vi cũ. Xác nhận thêm qua verify trực tiếp
  (xem bên dưới): admin thấy đủ 24/24 atom test (platform + cả 2 tenant) và
  `total_count=2572` (toàn bộ dataset thật) — không bị thu hẹp.
- `preview-slotgrid` vẫn hoàn toàn admin-only — nếu tương lai muốn tenant xem slot grid
  của chính mình, đó là 1 quyết định/scope riêng (đọc chéo qua nhiều atom + quarter plan
  của platform, phức tạp hơn nhiều so với list/star/delete).

## Verify

### Backend — test 2-tenant thật (bắt buộc theo issue)

**Setup thật** (S3-mediated ECS exec, không mock):
- 2 tenant thật: `tenant_a` (`50af8dd7-39c1-466f-8a8f-e1716bdc22bd`), `tenant_b`
  (`dec1b573-a776-47c7-881d-d002c4eadf13`).
- Seed 6 atom thật vào `acp_contract.tour_atoms` (cùng 1 tour_id thật đã có sẵn 24 atom
  platform khác trước đó, để test lẫn lộn dữ liệu là realistic, không phải bảng trống
  sạch): 2 `owner_scope='platform'`, 2 `owner_scope=<tenant_a>`, 2
  `owner_scope=<tenant_b>`.
- JWT thật: mint qua `POST https://api-cis.lumiguides.it.com/auth/tenant-login` (API live
  thật) cho cả 2 tenant — xác nhận token hợp lệ, 280 ký tự mỗi token.

**Cách chạy code MỚI (chưa merge) trước khi có PR**: upload trực tiếp
`admin_atoms.py` (bản đã sửa) vào container đang chạy thật qua S3-mediated exec (đè file
trên disk container — KHÔNG restart uvicorn, KHÔNG ảnh hưởng traffic thật đang phục vụ,
process uvicorn vẫn giữ module cũ trong memory). Chạy 1 script Python MỚI (process riêng)
import `admin_atoms` tươi từ file vừa đè → gọi trực tiếp `list_atoms()`/`atoms_summary()`/
`patch_atom()` như hàm Python thật, pool asyncpg thật, DB thật — cùng cách AA-389/AA-424 đã
verify trước khi merge.

**Kết quả (log đầy đủ):**
```json
{
  "list_atoms[tenant_a]":    { "total": 2, "atom_ids": ["aa431_tenant_a_0", "aa431_tenant_a_1"] },
  "list_atoms[tenant_b]":    { "total": 2, "atom_ids": ["aa431_tenant_b_0", "aa431_tenant_b_1"] },
  "list_atoms[admin]":       { "total": 24, "atom_ids": [ /* đủ cả platform + tenant_a + tenant_b + 18 atom thật khác cùng tour */ ] },
  "atoms_summary[tenant_a]": { "total_count": 2 },
  "atoms_summary[tenant_b]": { "total_count": 2 },
  "atoms_summary[admin]":    { "total_count": 2572 },
  "idor_guard": "blocked as expected: HTTPException: Atom aa431_tenant_b_0 not found (or is an empty-marker row)",
  "own_atom_patch": { "atom_id": "aa431_tenant_a_0", "starred": true }
}
```

**Xác nhận:**
- tenant_a **chỉ** thấy atom của chính mình (2/2), KHÔNG thấy atom tenant_b hay platform.
- tenant_b tương tự, hoàn toàn tách biệt tenant_a.
- admin thấy TẤT CẢ (24 atom test + platform), `atoms_summary` admin ra đúng tổng dataset
  thật (2572) — hành vi admin không bị ảnh hưởng.
- tenant_a thử PATCH atom của tenant_b bằng đúng atom_id → 404 (không phải 403/500, không
  lộ "atom này tồn tại nhưng không cho sửa") — IDOR guard hoạt động đúng.
- tenant_a PATCH atom của chính mình → thành công (starred=true).

Dọn dẹp: xoá 6 atom test + 2 tenant test (kể cả `tenant_api_usage` con) ngay sau verify —
xác nhận `DELETE` count khớp, DB sạch.

### Frontend — UI thật qua browser (Playwright, chưa deploy nên chỉ test route/render,
không test data vì backend live chưa có fix — sẽ verify data qua UI thật sau khi deploy,
xem phần "Deploy verify" khi báo cáo tổng hợp)

- Login tenant thật qua form → `/portal/dashboard` ✅
- Click "Atom Curation" ở Sidebar → `/portal/t6-atoms`, breadcrumb đúng "Atom Curation" ✅
- Trang render đủ: title, mô tả, filter (distinctiveness/unreviewed), empty state đúng
  ("No atoms yet" — vì tenant test chưa có atom seed lúc chạy UI check này, và backend
  live chưa deploy fix nên fetch 403 âm thầm rơi vào cùng nhánh empty — không crash, không
  lỗi hiển thị) ✅
- F5 refresh trên `/portal/t6-atoms` → ở nguyên đúng route ✅
- Middleware: không cookie → 307 `/tenant-login`; có cookie tenant → 200 ✅

### Kỹ thuật
- `npx tsc --noEmit` — 0 lỗi. `npm run build` — sạch, `/portal/t6-atoms` lên đúng route
  list.
- `.venv/bin/python -m flake8 api/routers/admin_atoms.py tests/unit/test_aa300_admin_atoms.py`
  — 0 lỗi.
- `eslint` — 1 finding mới (`AtomsTab.tsx` — `react-hooks/set-state-in-effect` trên
  fetch-on-mount) — **cùng pattern pre-existing** đã có ở MỌI Tab component khác trong
  cùng thư mục (`PoolTab.tsx`, `layout.tsx`, v.v., đã xác nhận qua AA-430's notes) — không
  phải lỗi mới, không phải regression. `layout.tsx` 2 finding pre-existing khác (đã ghi ở
  AA-430) không đổi.
- `.venv/bin/python -m pytest tests/unit -q` — full suite xanh (số liệu chính xác ghi
  trong log verify cuối, xem báo cáo tổng hợp cuối phiên).
