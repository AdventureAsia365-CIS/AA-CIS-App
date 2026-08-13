# AA-345 — Round 7 (fix "Newest first" sort sai + thiếu tour khi Load more)

Ngày: 2026-08-13. Branch `pqnghiep1354/aa-345-atomize-round7` từ `main`
(sau khi #131-137 đã merge). Bổ sung các file round trước, không thay thế.

**Kết luận: đây là 1 (MỘT) nguyên nhân gốc duy nhất, không phải 2 bug tách
biệt — ảnh hưởng cả "Newest first" lẫn "Load more", và thực ra ảnh hưởng
CẢ 5 lựa chọn Sort trên trang Curation, không riêng "Newest first". Đã
tái hiện bằng số liệu thật, đã sửa, đã verify lại bằng browser thật
(production build) + số liệu đối chiếu DB thật.**

## Điều tra — xác nhận 1 hay 2 bug (bằng số liệu thật, không đoán)

1. **So sánh field dùng để sort** — Atomize page's "Newest atomized first"
   dùng `a.atomized_at DESC NULLS LAST` ở tầng SQL
   (`api/routers/admin_pipeline.py::get_tours_for_atomization`, `a` là CTE
   `MAX(tour_atoms.created_at)` per tour) — ĐÚNG, sort toàn bộ dữ liệu
   trước khi phân trang. Curation page's "Newest first" trước fix: sort
   CLIENT-SIDE (`Array.sort` trong React) trên `combined` — mà `combined =
   summary.by_tour.filter(t => atomsByTour.has(t.tour_id))`, tức là CHỈ
   sort trong số các tour ĐÃ CÓ atom load sẵn vào `atomsByTour`.
2. **`atomsByTour` đến từ đâu?** — từ `atoms` state, load qua
   `GET /admin/atoms?limit=150&offset=0...`, và query này
   (`api/routers/admin_atoms.py::list_atoms`) có `ORDER BY ta.tour_id,
   ta.created_at` — sort theo UUID của tour_id, KHÔNG liên quan gì đến
   recency. Đây là gốc rễ: trang lấy 150 dòng atom ĐẦU TIÊN theo thứ tự
   UUID ngẫu nhiên, RỒI MỚI sort trong số đó theo atomized_at — nhưng tour
   mới nhất có thể có UUID rơi vào vị trí rất xa, không bao giờ lọt vào
   150 dòng đầu.
3. **Số liệu thật (query trực tiếp DB dev qua ECS exec, không giả lập)**:
   24 tour atomize "hôm nay" (13/8/2026). Mô phỏng ĐÚNG query
   `GET /admin/atoms` hiện tại (`ORDER BY ta.tour_id, ta.created_at LIMIT
   150 OFFSET 0`) → chỉ 10 tour distinct lọt vào trang đầu. Đối chiếu: **23
   / 24 tour atomize hôm nay HOÀN TOÀN VẮNG MẶT ở trang đầu** — bao gồm cả
   "One day Great Wall hike from Xishuiyu to Huanghuacheng" (tour mới
   nhất, atomize lúc 06:49:05 UTC hôm nay) chính là tour Nghiep báo cáo bị
   thiếu.
4. **Kiểm tra: có phải riêng "Newest first" hay TẤT CẢ sort đều lỗi?** —
   Đọc lại `orderedSections` (code cũ): MỌI nhánh `sortBy` (atoms_asc,
   atoms_desc, unreviewed_desc, name_asc, atomized_desc) ĐỀU sort trên
   CÙNG `combined` (đã bị lọc theo `atomsByTour.has(...)` TRƯỚC khi sort) —
   **cả 5 lựa chọn Sort đều mang cùng lỗi này**, "Newest first" chỉ là lựa
   chọn Nghiep tình cờ test và phát hiện ra.

**Kết luận: 1 nguyên nhân gốc duy nhất — thứ tự PHÂN TRANG (atom-row,
`ORDER BY tour_id`) quyết định tập con tour nào được xét để SORT, thay vì
SORT quyết định thứ tự phân trang.** "Newest first" hiển thị sai vị trí
đầu và "Load more" bỏ sót tour thực chất là 2 TRIỆU CHỨNG của cùng 1 cơ
chế lỗi, không phải 2 lỗi độc lập.

## Sửa

`frontend/app/admin/curation/page.tsx` — đổi kiến trúc phân trang từ
**atom-row-based** (offset/limit trên `GET /admin/atoms`) sang
**tour-based**, dùng `summary.by_tour` (từ `GET /admin/atoms/summary` —
đã là danh sách ĐẦY ĐỦ, không phân trang, có sẵn mọi field mọi sort cần:
atom_count, unreviewed_count, tour_name, atomized_at, is_thin) làm nguồn
sự thật:

1. `sortedTours` — `useMemo` sort TOÀN BỘ `summary.by_tour` (không phải
   tập con đã load) theo `sortBy`, lọc theo `highlightTourIds` (deep-link)
   và `thinOnly` (field có sẵn per-tour) TRƯỚC khi sort.
2. `loadAtoms` — không còn offset/limit atom-row nữa. Lấy 1 BATCH tour_id
   từ đầu `sortedTours` (hàm `nextTourBatch`, gom tour cho đến khi tổng
   `atom_count` chạm ngưỡng `TOUR_BATCH_ATOM_BUDGET=180` — margin an toàn
   dưới trần `limit<=200` có sẵn của `GET /admin/atoms`), fetch atom của
   ĐÚNG batch đó qua `tour_ids=` (endpoint đã hỗ trợ sẵn từ round 5/6, đã
   được fix race condition ở các round đó — tái dùng, không đổi backend).
   "Load more" tiếp tục batch KẾ TIẾP trong `sortedTours`.
3. `orderedSections` — đơn giản hoá: chỉ còn lọc `sortedTours` theo tour
   đã có atom load (`atomsByTour.has(...)`), không cần re-sort nữa vì
   `sortedTours` đã đúng thứ tự từ đầu.
4. **Phát hiện + sửa 1 regression tự gây ra trong lúc làm round này**: gate
   `loadAtoms` bằng `if (!summary) return` (chờ summary load xong mới biết
   sort gì) làm hỏng đường honest-error-state khi `GET /admin/atoms/
   summary` chính nó fail (vd role `content` bị 401, gap AA-253 đã biết) —
   `summary` không bao giờ được set, `loadAtoms` return sớm MÃI MÃI, trang
   kẹt ở "Loading atoms…" vô thời hạn thay vì hiện thông báo lỗi/rỗng như
   trước. Bắt được qua chạy lại bộ E2E cũ (`aa300-curation.spec.ts`) — 2
   test fail ngay. Sửa: thêm `summaryReady` (true khi fetch summary HOÀN
   TẤT, dù thành công hay lỗi, tách biệt với `summary` — vốn chỉ true khi
   THÀNH CÔNG) — `loadAtoms` chờ đúng `summaryReady`, nếu `summary` vẫn
   null sau đó thì tắt loading, hiện "No atoms match the current filters."
   như hành vi honest-empty-state cũ.

## Test

`tests/e2e/aa345-round7-curation-sort-loadmore.spec.ts` — E2E thật (login
admin thật, `e2e-test-admin`), mô phỏng ĐÚNG kịch bản: atomize 1 tour thật
(đảm bảo mới nhất tuyệt đối tại thời điểm test) → chọn Sort "Newest first"
trên Curation → assert tour vừa atomize là section ĐẦU TIÊN → bấm "Load
more" đến hết → assert tổng số section render ra KHỚP CHÍNH XÁC với tổng
số "Y tours" mà nút tự báo cáo (chứng minh không tour nào bị bỏ sót/trùng
lặp qua toàn bộ quá trình phân trang).

**Verify test bắt đúng regression (bắt buộc theo quy trình các round
trước)**: `git stash` code fix → build production → chạy test → **FAIL**
đúng vị trí "tour đầu tiên" (`Expected: "Mutianyu Great Wall and Ming
Tombs"` [tour vừa atomize] `Received: "2 Days Amid the Greatest Scenery in
Japan"` [tour cũ, đúng gốc rễ đã mô tả]). `git stash pop` khôi phục fix →
build lại → PASS.

**Test qua production build (bài học round 6)**: chạy toàn bộ qua `BASE_URL`
trỏ vào `next build && next start`, không phải `next dev` — dù bug lần
này không liên quan router.push()/replace() như round 6 (nên về lý thuyết
không nhất thiết phải khác biệt dev/prod), vẫn verify qua production build
theo đúng yêu cầu để không lặp lại kiểu bỏ sót của các round trước.

`tests/e2e/aa345-round5-curation-deeplink.spec.ts` — sửa 1 chỗ: đợi cố
định `waitForTimeout(1000)` sau khi bấm "Clear filter" không còn đủ (round
7 khiến việc "Clear filter" fetch lại MỘT BATCH TOUR đầy đủ thay vì 1 trang
atom cố định như trước, chậm hơn ~1.5s thay vì ~1s) → đổi sang
`expect.poll(...)` chờ đúng điều kiện thay vì sleep cố định — sửa flakiness
thật (đã verify: fail 2 lần liên tiếp với timeout cũ, pass ổn định sau khi
đổi).

## Should know

- 9 test E2E cũ (`aa300-curation.spec.ts`, `aa300-curation-redesign.spec.ts`)
  + `aa345-round5-curation-deeplink.spec.ts` vẫn pass sau fix — không có
  regression khác ngoài `summaryReady` (đã tìm và sửa ở trên, KHÔNG phải
  regression còn sót lại).
- Full suite pytest: 1152 pass (không đổi — round này chỉ sửa frontend).
  `tsc --noEmit` sạch.
- `distinctiveness`/`unreviewedOnly` (filter theo atom, không phải theo
  tour) vẫn giữ nguyên làm query param khi fetch atom cho 1 batch tour —
  không thể pre-filter tour theo 2 field này từ `summary.by_tour` (field
  đó không có sẵn per-tour ở mức đủ chi tiết) — nghĩa là 1 "trang" có thể
  hợp lệ trả về ÍT atom hơn ngân sách dự kiến khi 2 filter này đang bật,
  cùng mức độ dung sai như cơ chế phân trang CŨ vốn đã có (không phải
  regression mới).
- Đã dọn script tạm trên S3 sau khi verify xong.
