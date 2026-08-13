# AA-345 — Round 2 (Bug 5 regression + Việc 1-4)

Ngày: 2026-08-13. Branch `pqnghiep1354/aa-345-atomize-round2` từ `main` (sau
khi #131 và #132 đã merge). Bổ sung `AA-345-build.md` + `AA-345-fixes.md`,
không thay thế.

## Bug 5 (regression từ #132) — nguyên nhân thật

`frontend/app/admin/atomize/page.tsx`: `if (statusFilter)
params.set("status", statusFilter);` — `statusFilter === ""` (lựa chọn "All
tours") là giá trị falsy trong JS, nên điều kiện này coi nó là "không gửi
gì cả". Backend's `Query("pending", ...)` mặc định khi THIẾU param hoàn
toàn là `"pending"` — không phải `"all"` như curation's các filter khác
(nơi thiếu param = không lọc gì, khớp với ý nghĩa `""`). Vì vậy chọn "All
tours" im lặng rơi về đúng hành vi "Not yet atomized" — đúng y hệt mô tả
live.

**Fix**: luôn gửi `status` tường minh (bỏ điều kiện `if`), thay vì dựa vào
falsy-check. Đã verify qua network response thật (không chỉ đọc label UI,
vì label từng đọc nhầm do timing) — cả 3 giá trị đều đúng: `pending`→626,
`atomized`→137, `""`→763 (626+137=763, khớp).

## Việc 1 — Destination trống: KHÔNG phải bug code

Query thật xác nhận: `v_trip_registry.destination` = `raw_tours.country`
(đúng cột, đúng field, không JOIN sai). Tỷ lệ NULL thật trong DB (đếm trực
tiếp, không đoán):
- Toàn bộ 763-floor: **9/763 (1.2%)**
- Riêng trang mặc định "pending" (626 tour): **5/626 (0.8%)**
- 150 tour đầu tiên (trang 1, mặc định sort ngắn nhất trước): **3/150 (2.0%)**

Đây là data thật thiếu ở nguồn (`raw_tours.country IS NULL`), không phải lỗi
code — không tự bịa giá trị, giữ nguyên hiển thị "—". Tỷ lệ THẬT thấp hơn
nhiều so với ấn tượng "nhiều dòng trống" trong report gốc — báo lại rõ cho
Nghiep, không tự kết luận thay.

## Việc 2 — Filter/sort theo cột

- Backend: `GET /admin/tours-for-atomization` thêm `destination` (exact
  match, dropdown — chỉ 13 giá trị thật trong DB, không phải search box) và
  `sort` (`length_asc|length_desc|duration_asc|duration_desc`).
  `distinct_destinations` trả kèm trong response (tính trên toàn bộ
  763-floor, không phụ thuộc filter hiện tại — dropdown không tự co lại khi
  người dùng đang lọc).
- Duration sort: **alphabetic thô**, không parse ra số ngày — dữ liệu thật
  quá lộn xộn để parse tin cậy (`"12days 11nights"` không dấu cách,
  `"DAY TRIP"`, xuống dòng nhúng trong text, đơn vị lẫn lộn ngày/giờ/phút —
  xác nhận qua query mẫu thật). Đúng giới hạn đã được duyệt trước trong
  issue, không tự xây parser.
- Frontend: dùng lại đúng `FilterBar`'s `filters` prop (pattern đã có ở
  Atom Curation's Distinctiveness/Sort) — 3 dropdown Status/Destination/Sort,
  không tự vẽ UI mới.

## Việc 3 — Bỏ percentile khỏi cột chính

Cột "Source Length" giờ chỉ hiện số ký tự thô ("214 chars"), percentile
chuyển vào `title` attribute (tooltip khi hover) thay vì hiện luôn inline —
đúng quyết định đã chốt trong issue (bỏ hẳn khỏi hiển thị chính, giữ ở
tooltip vì dễ làm bằng `title=`, không cần build tooltip component riêng).

## Việc 4 — Timestamp + multi-tour deep-link

- Xác nhận thật qua `information_schema.columns`:
  `acp_contract.tour_atoms.created_at`/`updated_at` đã tồn tại sẵn
  (`timestamp with time zone`) — đúng như đã nêu, không cần migration mới.
- Chọn **MAX(created_at)** theo tour (không phải MIN) làm "atomized_at" —
  một tour có thể được atom hoá nhiều đợt qua thời gian (idempotency cho
  phép ADD thêm atom khi nguồn đổi, không thay thế), nên "lần chạm gần
  nhất" có ý nghĩa hơn "lần đầu tiên". Cùng field name + cùng lựa chọn ở cả
  2 endpoint (`GET /admin/tours-for-atomization` và
  `GET /admin/atoms/summary`).
- `GET /admin/atoms` thêm `tour_ids` (số nhiều, phân tách bởi dấu phẩy) —
  `tour_id = ANY($n::uuid[])`. Giữ nguyên `tour_id` (số ít) cho tương thích
  ngược; `tour_ids` thắng nếu cả 2 cùng có mặt.
- Trang Atomize: link "View in Atom Curation" giờ LUÔN truyền
  `?tour_ids=id1,id2,...` (không còn phân biệt 1 tour vs nhiều tour như
  round 1 — đơn giản hoá về đúng 1 code path).
- Trang Curation: đọc `tour_ids` (ưu tiên) hoặc `tour_id` cũ từ URL, filter
  ĐÚNG (không chỉ highlight-mà-không-lọc) — vì filter server-side không
  phức tạp hơn nhiều so với chỉ highlight, chọn làm CẢ HAI: filter thật +
  badge "Just atomized" màu vàng nổi bật + tự động mở rộng section đó khi
  trang load. Thêm "Sort: Newest first" vào đúng dropdown Sort đã có sẵn
  (không tạo dropdown mới), sort theo `atomized_at` giảm dần.

## Should know

- 2 file test cũ (`test_aa300_admin_atoms.py`) bị vỡ tạm thời do 2 thay đổi
  ở round này: (1) tham số `tour_ids` mới trên `list_atoms()` — khi gọi hàm
  trực tiếp (không qua FastAPI, như style test hiện có) tham số thiếu sẽ là
  chính đối tượng `Query(...)`, không phải `None` đã resolve, nên mọi call
  site cũ phải tự thêm `tour_ids=None` tường minh; (2) field `atomized_at`
  mới trong `by_tour` query — mock dict cũ thiếu key này. Cả 2 đã sửa (9
  test cũ), không phải lỗi logic mới, chỉ là hệ quả tất yếu của việc thêm
  tham số/cột vào hàm đã có test trực tiếp-gọi-hàm (không qua HTTP).
- Không sửa gì khác trong `/admin/curation` ngoài đúng phạm vi Việc 4 (đọc
  kỹ trước khi sửa `loadSummary`/`orderedSections`/section-header render,
  chỉ động đúng 3 chỗ: state đọc URL, sort thêm 1 case, header thêm
  badge+ngày).
- Live-verify đầy đủ qua Playwright + đọc trực tiếp response JSON (không
  chỉ label UI — bài học từ chính round 1, label có thể đọc sai do timing)
  cho: Bug 5 cả 3 giá trị, destination filter, sort, tooltip percentile,
  multi-tour filter+highlight+badge, Newest first sort. 66/66 test pass (26
  file AA-345 mới + 40 file AA-300 cũ+mới), full suite 1148 pass, flake8 +
  tsc sạch.
- 1 vụ nhiễu môi trường gặp lại (không phải bug code): `.next` cache bị hỏng
  sau khi kill cứng (`kill -9`) tiến trình `next dev` ở phiên trước — toàn
  bộ route admin trả 404 cho tới khi xoá `.next` và khởi động lại sạch.
