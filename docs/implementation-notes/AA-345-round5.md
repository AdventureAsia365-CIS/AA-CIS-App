# AA-345 — Round 5 (bug xác nhận: Curation không áp filter tour_ids trên client-side navigation)

Ngày: 2026-08-13. Branch `pqnghiep1354/aa-345-atomize-round5` từ `main`
(sau khi #131-135 đã merge). Bổ sung các file round trước, không thay thế.

**Kết luận: Nghiep đúng — có bug thật, đã tái hiện 100% bằng browser thật,
đã sửa, đã verify lại bằng chính kịch bản đã fail trước đó.**

## Vì sao round 4 (PR #135) bỏ sót

Round 4 chỉ verify qua `curl` trực tiếp vào backend (đúng để loại trừ lỗi
backend/data, nhưng KHÔNG đủ để bắt lỗi này) — đây là lỗi **thuần
client-side React/Next.js timing**, chỉ xảy ra khi navigate bằng
`router.push()` (client-side, giống hệt lúc bấm nút thật trong UI), không
xảy ra khi gọi API trực tiếp hay load URL bằng `page.goto()` (full page
load). Không có cách nào bắt được bug này mà không dùng browser thật với
đúng kịch bản click-through.

## Nguyên nhân THẬT (đã xác nhận, không phải giả thuyết)

**KHÔNG PHẢI** "tour_id sai được gửi lên URL" như hypothesis ban đầu của
Nghiep. Đã verify bằng Playwright + network capture thật:
- `POST /api/admin/atoms/decompose` request body: `tour_ids: ["<real
  id>"]` — ĐÚNG tour vừa chọn.
- URL sau khi bấm "View in Atom Curation": `tour_ids=<real id>` — CÙNG
  giá trị, khớp 100% với request body (chứng minh bằng code: cả 2 nơi
  dùng chung 1 biến local `tourIds` trong `runDecompose()`,
  `frontend/app/admin/atomize/page.tsx` — không thể lệch nhau).

**Bug thật nằm ở phía CURATION, không phải Atomize**: `highlightTourIds`
trước đây là 1 `useState` lazy initializer đọc `window.location.search`
CHỈ 1 LẦN lúc mount. Khi navigate bằng `router.push()` (client-side, từ
trang Atomize sang Curation — đúng kịch bản người dùng bấm nút, không phải
gõ URL/reload) — React có thể mount Curation VÀ chạy initializer đó
**TRƯỚC KHI** Next.js router đã thực sự áp dụng URL mới lên
`window.location`. Kết quả: initializer đọc phải URL CŨ (trước khi
navigate, không có `tour_ids`), khởi tạo `highlightTourIds = []` — im
lặng, không lỗi, không log. Thanh địa chỉ trình duyệt VẪN hiện đúng
`?tour_ids=...` (URL bar được Next.js cập nhật đúng), nhưng React state
bên trong component đã "chốt" giá trị sai từ trước đó.

**Bằng chứng tái hiện được (Playwright, admin session thật)**:
1. Login thật (`e2e-test-admin`), chọn 1 tour thật chưa atomize, bấm
   Atomize thật, bấm "View in Atom Curation" thật (client-side
   `router.push()`) → **tour KHÔNG hiện**, không có banner "Filtering to
   1 tour", trang hiện TOÀN BỘ 2433+ atom không lọc — khớp 100% mô tả của
   Nghiep.
2. **Cùng URL đó**, nhưng load bằng `page.goto()` (hard reload, y hệt copy
   URL dán vào tab mới) → **tour hiện đúng**, banner "Filtering to 1 tour
   just atomized" hiện đúng.
3. Đây là bằng chứng loại trừ quyết định: cùng 1 URL, cùng data, chỉ khác
   CÁCH đến trang (soft navigation vs hard reload) → kết quả khác nhau.
   Xác nhận chắc chắn đây là race condition ở tầng client-side navigation,
   không phải lỗi data hay lỗi URL param.

## Sửa

`frontend/app/admin/curation/page.tsx`:
- Thay `useState` lazy initializer đọc `window.location.search` bằng
  `useSearchParams()` (hook chính thức của Next.js App Router,
  ĐƯỢC ROUTER ĐỒNG BỘ, không thể lệch pha với navigation đang render) —
  loại bỏ race condition tận gốc, không phải vá triệu chứng.
- `highlightTourIds` giờ là `useMemo` derive từ `searchParams` (không còn
  state riêng `setHighlightTourIds`) — nút "Clear filter" chỉ cần
  `router.replace()`, `useSearchParams()` tự động phản ứng, không cần
  quản lý 2 nguồn state song song nữa (đơn giản hoá, không phải thêm
  phức tạp).
- `useSearchParams()` bắt buộc component bọc trong `<Suspense>` (yêu cầu
  của Next.js) — comment cũ trong code đã tránh dùng hook này chính vì lý
  do này; round này chấp nhận đánh đổi đó vì nó sửa đúng gốc rễ, không có
  cách nào khác an toàn hơn để đọc search params đồng bộ với navigation.
  Tách `CurationPageInner` (component thật) khỏi `CurationPage` (export
  default, chỉ bọc Suspense) — pattern chuẩn của Next.js cho trường hợp
  này.

## Test

`tests/e2e/aa345-round5-curation-deeplink.spec.ts` — **E2E thật, không
phải unit test mô phỏng** (lần đầu tiên trong series AA-345 round này có
login admin thật hoạt động — xem "Should know" bên dưới). Mô phỏng ĐÚNG
kịch bản đã fail: chọn 1 tour thật, bấm Atomize thật, bấm "View in Atom
Curation" thật (client-side navigation, không phải `page.goto()`), assert
banner "Filtering to 1 tour" + tên tour thật xuất hiện.

**Verify test thật sự bắt được lỗi (không phải test luôn xanh)**: chạy
test này với code CŨ (trước fix, qua `git stash`) → **FAIL đúng như mô tả
bug** (không tìm thấy banner). Chạy lại với code đã fix → **PASS**. Test
này có khả năng catch regression thật.

## Should know — quan trọng, ảnh hưởng các round sau

**Đã unblock được gap AA-253 (đã ghi ở round 4) — CÓ ĐIỀU KIỆN**: Nghiep
đã cho phép reset mật khẩu tài khoản test có sẵn `e2e-test-admin` (role
`admin`, không phải người thật) sang giá trị tạm
`aa345-repro-temp-2026` để lấy admin session thật cho round này. Giá trị
này ĐANG được dùng trong `tests/e2e/aa345-round5-curation-deeplink.spec.ts`
đã commit — theo đúng convention repo đã có sẵn
(`aa384-marketplace-auth.spec.ts` cũng hardcode credential thật kiểu này).
Nếu Nghiep muốn đổi lại mật khẩu tài khoản này sau, phải cập nhật lại file
test tương ứng, nếu không suite E2E mới thêm ở round này sẽ fail ở bước
login (không phải regression code, chỉ là mismatch credential).

**Không sửa Vấn đề B (timezone)** — theo đúng chỉ đạo, đã xác nhận đúng ở
PR #135, không động vào lại.

**Không sửa** dòng tiếng Việt còn sót ở `curation/page.tsx` (~dòng 648, nút
xoá atom hàng loạt) — đã ghi nhận ở round 4, vẫn ngoài phạm vi round này.
Cũng phát hiện thêm: label "chưa có (AA-317)" (dashboard stat card khi
count=0) cũng là tiếng Việt — cùng nhóm vi phạm, cùng lý do không sửa ở
đây (ngoài phạm vi 2 vấn đề được giao).

Full suite: 1152 pass (không đổi so với round 4 — round này không thêm
pytest nào, chỉ có 1 Playwright E2E test mới). `tsc --noEmit` sạch. 9 test
E2E cũ (`aa300-curation.spec.ts`, `aa300-curation-redesign.spec.ts`) vẫn
pass sau khi thêm `<Suspense>` — không có regression.

Đã dọn script tạm trên S3 sau khi verify xong.
