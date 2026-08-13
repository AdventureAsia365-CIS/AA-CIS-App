# AA-345 — Round 3 (Newest atomized sort + timezone bug)

Ngày: 2026-08-13. Branch `pqnghiep1354/aa-345-atomize-round3` từ `main` (sau
khi #131, #132, #133 đã merge). Bổ sung các file round trước, không thay thế.

## Việc 2 — Nguyên nhân thật của lệch ngày (điều tra TRƯỚC khi sửa)

1. **DB đúng**: `tour_atoms.created_at` là `timestamp with time zone`, lưu
   đúng UTC (xác nhận qua `now()` + dòng thật — vd tour atomize hôm nay lưu
   `2026-08-13 02:41:59+00:00`).
2. **Code hiển thị**: cả 2 trang dùng `new Date(iso).toLocaleDateString(
   undefined, {...})` — KHÔNG chỉ định `timeZone`, nghĩa là kết quả phụ
   thuộc hoàn toàn vào timezone của MÔI TRƯỜNG THỰC THI (có thể là trình
   duyệt của người xem, hoặc pha SSR phía server của trang "use client" này
   — không chắc chắn là cái nào, cả 2 đều khả dĩ).
3. **Rà soát convention chung TRƯỚC khi quyết định** (bắt buộc theo yêu cầu,
   không tự chọn timezone tuỳ ý): grep toàn bộ `toLocaleDateString`/
   `toLocaleString` trong `frontend/app/` → **61 chỗ gọi, 0 chỗ chỉ định
   `timeZone`** (đã kiểm tra run-health, review, quarter-plan,
   master-content, s1-rewrite, AdminSidebar, pipeline s1-s4, portal
   components, TourDetailPanelV2...). Ngay cả locale cũng không nhất quán
   (`"en-US"`, `"en-GB"`, `undefined` dùng lẫn lộn). **Kết luận: KHÔNG có
   convention chung nào tồn tại** — đây là 1 pattern hệ thống chưa được
   quản lý, không riêng 2 trang AA-345.
4. **Quyết định** (đúng nhánh fallback đã duyệt trước trong issue): dùng
   `Asia/Ho_Chi_Minh` (UTC+7) cố định cho CHỈ 2 trang Atomize/Curation —
   quyết định cục bộ, không phải sửa theo pattern có sẵn (vì không có).

**Chứng minh cơ chế lỗi thật** (không chỉ suy đoán lý thuyết): chạy cùng
timestamp thật (`2026-08-13T02:41:59Z`, dòng DB thật) qua `toLocaleDateString`
KHÔNG chỉ định `timeZone`, nhưng đặt `TZ=America/Los_Angeles` cho runtime Node
→ ra đúng **"Aug 12, 2026"** — tái hiện chính xác lỗi Nghiep thấy live. Cùng
timestamp đó qua bản đã sửa (`timeZone: "Asia/Ho_Chi_Minh"` tường minh) →
luôn ra đúng **"Aug 13, 2026"**, bất kể runtime timezone là gì. US timezone
là 1 giả thuyết khả dĩ cho môi trường Vercel SSR/Nghiep's browser cụ thể —
không khẳng định tuyệt đối ĐÂY là timezone thật đã gây lỗi (không thể kiểm
tra trực tiếp môi trường thật của Nghiep từ đây), nhưng cách sửa (chỉ định
tường minh `timeZone`) đúng và loại bỏ hoàn toàn phụ thuộc vào timezone môi
trường thực thi — vá đúng gốc rễ bất kể cơ chế cụ thể là gì.

### ⚠️ Phát hiện lan rộng — CẦN issue riêng, KHÔNG tự sửa trong PR này

**61 chỗ gọi `toLocaleDateString`/`toLocaleString` khác trong toàn app đều
có cùng lỗ hổng tiềm ẩn này** (không chỉ định timezone, phụ thuộc môi
trường thực thi). Đây là phát hiện phụ trong lúc điều tra Việc 2, KHÔNG
trong phạm vi PR này (đúng chỉ đạo "KHÔNG LÀM"). Đề xuất Nghiep tạo issue
riêng để rà soát + quyết định 1 convention chung (vd hàm dùng chung
`formatDate(iso, {timeZone: "Asia/Ho_Chi_Minh"})` export từ 1 module, thay
vì mỗi trang tự viết) cho toàn bộ 61+ vị trí.

## Việc 1 — "Newest/Oldest atomized first" trên trang Atomize

- Backend: thêm `atomized_desc`/`atomized_asc` vào `_SORT_COLUMNS`
  (`a.atomized_at DESC/ASC NULLS LAST`) — cùng field `atomized_at` đã thêm ở
  PR #133 (`MAX(tour_atoms.created_at)` per tour).
- **Quyết định UX** (đã cân nhắc theo đúng yêu cầu issue): ẩn 2 option này
  khỏi dropdown Sort khi `status=pending` — mọi tour ở view đó có
  `atomized_at=NULL` (chưa có atom nào), sort theo giá trị NULL toàn bộ là
  no-op vô nghĩa, ẩn thay vì hiện 1 lựa chọn "bấm không thấy gì đổi". Khi
  chuyển status từ khác về "pending" trong lúc đang chọn 1 trong 2 sort này,
  tự động reset về sort mặc định (tránh 1 lựa chọn bị ẩn khỏi dropdown
  nhưng vẫn "dính" ở state, người dùng không có cách bỏ chọn qua UI).

## Should know

- Repo này **chưa có bất kỳ JS/TS unit-test runner nào** (không jest,
  không vitest — xác nhận qua `package.json` chỉ có
  dev/build/start/lint, và không file `*.test.ts(x)` nào tồn tại). CI's
  "Lint" job (`.github/workflows/ci.yml`) chỉ chạy `flake8` trên Python.
  Vì vậy test cho Việc 2 (timezone) là 1 script Node thuần
  (`tests/verify_scripts/aa345_round3_timezone_verify.mjs`, đặt cùng chỗ
  quy ước `tests/verify_scripts/` đã có sẵn cho các script Python verify
  khác) — chạy tay bằng `node tests/verify_scripts/
  aa345_round3_timezone_verify.mjs`, KHÔNG được CI tự động chạy (không có
  gì để wire vào). Đây là hạn chế thật của hạ tầng test repo, không phải
  lựa chọn tuỳ tiện — ghi rõ để Nghiep biết, không phải 1 test "đầy đủ" như
  pytest.
- Test pytest mới (Việc 1, backend sort logic): 5 test trong
  `test_aa345_atomize.py` — cả 2 hướng sort + xác nhận thứ tự dữ liệu thật.
- Full suite: 1151 pass (tăng từ 1148 — +3 test mới: 2 sort direction +
  1 order-verify), flake8 sạch, `tsc --noEmit` sạch.
- Live-verify qua Playwright: dropdown Sort đúng ẩn/hiện theo status, sort
  "Newest atomized first" trả đúng thứ tự dữ liệu thật (khớp curl trực
  tiếp), auto-reset về "" khi chuyển status=pending trong lúc đang chọn sort
  atomized, cả 2 trang hiện đúng "Atomized Aug 13, 2026" cho 2 tour atomize
  thật hôm nay (trước fix sẽ có nguy cơ hiện "Aug 12" tuỳ môi trường).
