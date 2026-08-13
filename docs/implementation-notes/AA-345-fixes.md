# AA-345 — Fixes round (2 real bugs + 2 UX polish + English translation)

Ngày: 2026-08-13. Branch mới `pqnghiep1354/aa-345-atomize-fixes` từ `main`
(sau khi PR #131 đã merge và Nghiep live-verify thật trên production, phát
hiện 2 bug thật + 2 UX gap). File này bổ sung `AA-345-build.md`, không thay
thế.

## Bug 1 — 401 Unauthorized silent-fail khi bấm "Atom hoá" (ROOT CAUSE)

**Nguyên nhân thật, KHÁC HẲN lỗi AssumeRole đã báo cáo trước** (đã tự nhầm
lẫn 2 lỗi khác tầng, cần phân biệt rõ):

- Response `{"message":"Unauthorized"}` (không phải `{"detail": ...}` kiểu
  FastAPI, cũng không phải `{"error": ...}` kiểu `lib/auth-server.ts`) —
  đúng format deny mặc định của **AWS API Gateway**, nghĩa là request bị
  chặn TRƯỚC KHI chạm tới FastAPI app.
- `api/routers/admin_pipeline.py` đã tự ghi chú rõ pattern này từ AA-230:
  `/v1/pipeline/*` (và cùng nhóm `/v1/atoms/*`) nằm sau **API Gateway Lambda
  Authorizer** (bắt buộc Bearer JWT), còn `/admin/*` thì KHÔNG — được miễn
  hoàn toàn.
- PR #131 tạo `frontend/app/api/atoms/[...path]/route.ts` proxy tới
  `${API_URL}/v1/atoms/${path}` — chỉ gửi `X-Admin-Secret`, không có Bearer
  JWT → Lambda Authorizer chặn ở tầng gateway, decompose() trong
  `v1_atoms.py` KHÔNG BAO GIỜ được gọi tới.
- Vì sao STEP 0/build session không thấy: chạy `uvicorn` local trực tiếp,
  KHÔNG qua API Gateway — không có tầng authorizer nào để chặn, nên lỗi
  local luôn là AssumeRole (tầng AWS IAM, sau khi auth app đã pass), không
  phải 401 (tầng auth app, trước khi chạm request).

**Fix — đúng pattern AA-230 (verbatim, không phát minh cách mới):**
- `api/routers/admin_pipeline.py`: thêm `POST /admin/atoms/decompose` —
  `verify_admin_secret()` rồi gọi thẳng `v1_atoms.decompose(body=body,
  request=request, tenant=None)` (tenant=None vì decompose() không đọc
  tenant, chỉ dùng qua `Depends()` cho auth FastAPI-native, không áp dụng
  khi gọi hàm trực tiếp — giống hệt lý do AA-230's alias đã ghi).
- Frontend: đổi `POST /api/atoms/decompose` → `POST /api/admin/atoms/decompose`
  (đi qua proxy `/api/admin/[...path]/route.ts` đã hoạt động đúng production
  cho mọi endpoint khác). Xoá hẳn `frontend/app/api/atoms/[...path]/route.ts`
  (chết, không còn ai gọi).
- Xử lý lỗi hiển thị: `extractErrorMessage()` helper mới đọc cả 3 shape lỗi
  (`detail`/`message`/`error`) — không chỉ FastAPI mà cả API Gateway/BFF
  layer — banner đỏ rõ ràng (icon + heading "Atomization failed to start" +
  message thật), áp dụng cho MỌI lỗi trên trang (load tour lỗi lẫn decompose
  lỗi), không chỉ riêng case 401 này.
- **Verify**: local `uvicorn` (không có API Gateway nên không tái hiện được
  chính xác lỗi 401 tầng gateway) — verify được: (1) endpoint mới trả 202
  thay vì 401 ở tầng FastAPI, (2) banner lỗi hiện rõ ràng khi decompose thật
  fail (AssumeRole, giới hạn local đã biết). Root cause fix dựa trên đọc code
  + đối chiếu chính xác comment AA-230 đã có sẵn trong repo, không phải đoán.

## Bug 2 — Filter "chỉ hiện tour đã atom hoá" không lọc đúng

**Nguyên nhân**: `include_atomized: bool` cũ chỉ có 2 trạng thái — loại trừ
tour đã atom hoá (`false`) hoặc KHÔNG lọc gì cả / hiện tất cả (`true`).
Không hề có khả năng lọc để CHỈ hiện tour đã atom hoá — đúng như bug report
mô tả ("vẫn lẫn cả tour CHƯA ATOM HOÁ" khi bấm nút, vì nút chỉ mở rộng sang
"tất cả", không bao giờ thu hẹp về "chỉ đã atom hoá").

**Fix**: `GET /admin/tours-for-atomization` đổi `include_atomized: bool` →
`status: Literal["pending","atomized",""] = "pending"` — 3 nhánh WHERE rõ
ràng (`a.tour_id IS NULL` / `a.tour_id IS NOT NULL` / không lọc). Frontend
đổi từ 1 nút toggle sang dropdown thật (tái dùng `FilterBar`'s `filters`
prop — pattern có sẵn từ `/admin/curation`, không tự sáng tạo UI mới):
"Not yet atomized" / "Already atomized" / "All tours".

**Verify live**: `status=atomized` → 135/135 tour đều `atom_count>0` (đúng
135 tour đã atom hoá thật), `status=pending` → 628, `status=""` → 763 — cả
3 chiều đều đúng số, verify qua cả curl trực tiếp lẫn Playwright (đổi
dropdown qua lại 4 lần, đọc lại "Showing X of Y" mỗi lần).

## UX 3 — Pagination / "Showing X of Y"

`GET /admin/tours-for-atomization` thêm `limit`/`offset` (mặc định 150,
giống `GET /admin/atoms` trong `admin_atoms.py`) + `total` từ COUNT(*) riêng
(không phải page hiện tại). Frontend: copy nguyên pattern "Load more (X / Y)"
từ `/admin/curation` (LOAD_LIMIT batch, `offsetRef` để tránh stale-closure
bug đã ghi chú sẵn ở đó). "Showing X of Y tours" đặt cố định trong sticky
header, cập nhật đúng khi đổi status filter hay bấm Load More (verify live:
150→300 sau 1 lần bấm, tổng vẫn đúng 628).

## UX 4 — Sticky header

Copy nguyên layout pattern từ `/admin/s1-rewrite` (page tương tự nhất — có
sẵn đúng shape "sticky panel phía trên + `<main>` cuộn riêng phía dưới"):
outer flex-column `overflow:hidden`, header `position:sticky, top:0,
zIndex:20`, nội dung cuộn trong `<main overflowY:auto>`. Không tự viết CSS
mới — verify live: cuộn danh sách xuống 2000px, heading + filter bar vẫn cố
định trên đầu màn hình.

## Tiếng Anh hoá toàn trang

Rà soát lại toàn bộ `frontend/app/admin/atomize/page.tsx` — mọi label,
badge, placeholder, thông báo lỗi, nút bấm đổi sang tiếng Anh. Cũng sửa
label sidebar nav "Atom hoá (N2)" → "Atomize (N2)" trong `AdminSidebar.tsx`
(trực tiếp đại diện cho trang này, để lại tiếng Việt ở đó sẽ lệch tông ngay
cạnh 1 trang toàn tiếng Anh). KHÔNG động vào `/admin/curation` (còn tiếng
Việt ở vài chỗ) — ngoài phạm vi 4 vấn đề được giao, giữ nguyên theo đúng chỉ
đạo "KHÔNG LÀM". Verify: quét toàn bộ `body.innerText` qua Playwright bằng
regex Unicode tiếng Việt (`[À-ỹ]`) — 0 ký tự tiếng Việt còn lại trên trang
sau khi render đầy đủ (kể cả sau khi trigger lỗi thật).

## Should know

- Không sửa `admin_atoms.py`/`/admin/curation` — đúng phạm vi giao.
- Không bulk-trigger atomize cho 628 tour — chỉ chọn 1 tour để verify UI
  hiện đúng trạng thái lỗi (không cần decompose thành công thật, đã biết
  giới hạn local IAM từ session build trước).
- Test mới: `TestAdminDecomposeAlias` (2 test — auth gate + delegation đúng
  `tenant=None`) bổ sung vào `test_aa345_atomize.py`, cùng với việc viết lại
  toàn bộ `TestToursForAtomization` để test cả 3 chiều `status` (không chỉ
  1 chiều như bản cũ). 15/15 test pass, full suite 1132 pass, flake8 sạch,
  `tsc --noEmit` sạch.
- Chưa có Playwright/E2E test tự động nào tồn tại sẵn cho trang này từ PR
  #131 (chỉ có unit test) — không có gì để "cập nhật", việc verify UI ở round
  này làm thủ công qua Playwright script tạm (không commit vào repo, đúng
  quy ước "scratchpad" của session).
