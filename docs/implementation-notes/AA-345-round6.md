# AA-345 — Round 6 (fix "Clear filter" regression từ PR #136)

Ngày: 2026-08-13. Branch `pqnghiep1354/aa-345-atomize-round6` từ `main`
(sau khi #131-136 đã merge). Bổ sung các file round trước, không thay thế.

**Kết luận: đây là regression thật do PR #136 (round 5) gây ra, đã tái
hiện bằng browser thật (production build), đã sửa, đã verify lại.**

## Vì sao lần này KHÔNG tái hiện được qua `next dev` (round 5's own
verification) nhưng LẠI tái hiện qua production build

Kiểm tra ban đầu bằng `next dev` (dev server local): "Clear filter" hoạt
động ĐÚNG — URL đổi, banner biến mất, danh sách reset đầy đủ. Nghi vấn ban
đầu của Nghiep (`useMemo` dependency sai) — đã đọc lại code, dependency
array `[searchParams]` đúng, không sai.

**Chỉ sau khi build + chạy production thật** (`npm run build && npm run
start`, đúng cách Vercel serve production) mới tái hiện được: `/admin/
curation` build ra `○ (Static)` (prerendered tĩnh) — khác hẳn hành vi
render của `next dev` (luôn dynamic per-request). Đây là round THỨ 2 liên
tiếp mà 1 bug chỉ xuất hiện ở 1 chế độ render cụ thể của Next.js, không
xuất hiện ở chế độ còn lại — bài học ghi lại cho các round sau: **verify
bằng `next dev` KHÔNG đủ, phải build + start production để verify bất kỳ
thay đổi nào liên quan đến `useSearchParams()`/`router.push()`/
`router.replace()`**.

## Nguyên nhân THẬT (xác nhận qua console.log đặt trực tiếp trong code,
không đoán)

`router.replace("/admin/curation")` trong nút "Clear filter" là 1
navigation **CÙNG pathname, chỉ khác search params** (`?tour_ids=X` →
không có query) — khác với round 5's bug (navigation ĐỔI pathname, từ
`/admin/atomize` sang `/admin/curation`). Đặt `console.log` trực tiếp
trong `onClick` xác nhận: hàm CÓ được gọi, `router.replace()` CÓ được gọi
— nhưng sau đó **cả URL bar lẫn giá trị `useSearchParams()` đều đứng yên,
không đổi gì**. Đây là 1 lớp lỗi flaky đã biết của Next.js App Router
(same-pathname, chỉ đổi search params) — khác cơ chế với round 5 (race
điều kiện thời gian giữa mount và router áp URL), lần này router.replace()
đơn giản KHÔNG kích hoạt lại render/URL update cho trường hợp cụ thể này
trên production build.

## Sửa

`frontend/app/admin/curation/page.tsx`:
- Thêm `cleared` — 1 `useState<boolean>` đơn giản, nút "Clear filter" set
  trực tiếp (`setCleared(true)`) — CHẮC CHẮN trigger re-render (React state
  cơ bản, không phụ thuộc router). `highlightTourIds`'s `useMemo` check
  `cleared` TRƯỚC, trả `[]` ngay nếu true, không cần đọc `searchParams`
  nữa — filter logic không còn phụ thuộc router.replace() có thành công
  hay không.
- Đổi `router.replace("/admin/curation")` → `window.history.replaceState(
  null, "", "/admin/curation")` — gọi thẳng browser API, không qua tầng
  router của Next.js (không bị ảnh hưởng bởi lớp lỗi same-pathname ở trên)
  — verify: URL bar cập nhật đúng 100% qua mọi lần test, kể cả khi
  `router.replace()` (thử trước đó) không đổi gì. Vẫn là "replace" (không
  phải "push") nên hành vi nút Back của trình duyệt không bị ảnh hưởng.
- **Không dùng cả 2** (`router.replace()` + `history.replaceState()` cùng
  lúc) — thử ban đầu, phát hiện gây double-fetch (mỗi cái tự trigger
  1 lần re-render/refetch riêng) — bỏ `router.replace()` hẳn, chỉ giữ
  `history.replaceState()`.

## Should know — hạn chế còn lại (không phải bug mới, ghi nhận minh bạch)

Ngay cả sau khi sửa, quan sát thấy đôi khi vẫn có 2 lần gọi API (`/atoms/
summary` + `/atoms`) thay vì 1 lần khi bấm Clear filter — nghi vấn: Next.js
router có thể tự nhận biết `history.replaceState()` (dù gọi thẳng, không
qua router API) và tự trigger thêm 1 lần re-render riêng của nó, cộng dồn
với lần re-render từ `cleared`. Đây là 1 network round-trip thừa, KHÔNG
ảnh hưởng tính đúng đắn (kết quả cuối cùng vẫn đúng, đã verify qua
Playwright nhiều lần) — không đầu tư sửa thêm ở round này (ngoài phạm vi
được giao: chỉ sửa "Clear filter không hoạt động", không phải "tối ưu số
lần gọi API").

## Test

Mở rộng CHÍNH file test đã có từ round 5
(`tests/e2e/aa345-round5-curation-deeplink.spec.ts`, đúng yêu cầu) — thêm
bước sau khi verify deep-link filter đúng: bấm "Clear filter", assert cả
3: (1) URL không còn `tour_ids`/`tour_id`, (2) banner "Filtering to..."
biến mất, (3) danh sách hiện lại NHIỀU hơn 1 section (không chỉ dựa vào
banner biến mất — phải chứng minh data thật đã reset, không chỉ ẩn text).

**Test này PHẢI chạy qua `BASE_URL` trỏ vào 1 production build
(`next build && next start`), KHÔNG PHẢI `next dev`** — đã verify trực
tiếp: cùng file test, chạy qua `next dev` sẽ KHÔNG bắt được bug này (chạy
xanh dù code cũ chưa sửa), chỉ qua production build mới fail đúng như mô
tả. Đã verify test bắt đúng regression theo đúng quy trình 2 chiều (yêu
cầu bắt buộc của các round trước): `git stash` code fix → build production
→ chạy test → FAIL đúng vị trí `expect(...searchParams.has('tour_ids'))
toBe(false)` (nhận `true`, đúng triệu chứng "Clear filter không có tác
dụng"). `git stash pop` khôi phục fix → build lại → chạy test → PASS.

9 test E2E cũ (`aa300-curation.spec.ts`, `aa300-curation-redesign.spec.ts`)
vẫn pass sau fix (chạy qua production build, có `CONTENT_PASSWORD` tạm
thời trong `.env.local` cục bộ — không commit, chỉ để test local, dev
Vercel/CI đã có sẵn qua secrets).

Full suite pytest: 1152 pass (không đổi — round này không đụng backend).
`tsc --noEmit` sạch.
