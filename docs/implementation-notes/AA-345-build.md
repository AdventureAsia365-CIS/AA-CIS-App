# AA-345 — Build notes (UI chọn tour + trigger N2 decompose, sửa GET /admin/tours)

Ngày: 2026-08-13. Tiếp theo `AA-345-step0-investigation.md` (STEP 0, Phần 1-4,
đọc trước file này). Không chạy N2 decompose thật trong session này (đã chạy
20 tour ngẫu nhiên ở STEP 0 rồi) — chỉ build UI/API, không tự trigger cho 628
tour còn lại, đúng chỉ đạo.

---

## Decisions

1. **Không thêm field `is_published` / JOIN `published_tours` mới vào
   `GET /admin/tours`.** Đọc lại frontend trước khi build phát hiện
   `pipeline_status` (đã có sẵn trong response) đã được dùng để hiện
   `<Badge color="green">Published</Badge>` ngay tại
   `frontend/app/admin/s1-rewrite/page.tsx:168-169`, và
   `shared/services/export_service.py:103` xác nhận đây là cơ chế publish
   thật (`SET pipeline_status = 'published'`) — không phải cột chết kiểu
   `review_status` (AA-316). Thêm một JOIN thứ hai để phát hiện "đã publish"
   sẽ tạo ra 2 nguồn sự thật cho cùng một fact, có thể lệch nhau. Badge
   "đã publish" trên S1 Rewrite coi như đã tồn tại từ trước AA-345, không
   cần build thêm.

2. **`GET /admin/tours-for-atomization` đọc trực tiếp từ
   `acp_contract.v_trip_registry`**, không tự viết lại WHERE clause floor —
   view đó (migration 083) CHÍNH LÀ nguồn sự thật 763-tour mà STEP 0 đã xác
   nhận. `GET /admin/tours` (đã sửa ở Part A) vẫn query `raw_tours` trực
   tiếp vì nó cần `GROUP BY` với `generated_content` để tính
   `rewrite_count` — thứ `v_trip_registry` không có và không phải mục đích
   của nó.

3. **`include_atomized` query param (default `false`) thay vì chọn cứng một
   phía.** Prompt build tự mâu thuẫn giữa hai chỗ: STEP 0 Phần 3.1 nói
   "loại trừ 115 tour đã atom hoá" (để không cho chọn lại), nhưng phần thiết
   kế UI lại nói trả về kèm "cờ đã có atom" (ngụ ý hiện cả hai). Test spec
   ("763 − số đã atom hoá") khớp với hướng loại trừ. Giải quyết bằng một
   query param: mặc định loại trừ (đúng test + đúng lý do gốc — tránh chọn
   nhầm tour đã xong), bật `include_atomized=true` để xem đầy đủ kèm cờ
   `has_atoms`/`atom_count` khi cần (vd để soát lại badge THIN). Checkbox
   trên UI bị khoá (disabled) cho tour đã có atom ngay cả khi đang hiện —
   không chặn hoàn toàn re-run (idempotent qua `source_hash`, xem STEP 0),
   chỉ chặn thao tác vô tình.

4. **Percentile độ dài tính trên toàn bộ 763 tour, TRƯỚC khi lọc
   `include_atomized`.** Query dùng CTE `base` (percentile trên toàn view)
   rồi mới `LEFT JOIN` + lọc atom ở bước sau — để con số percentile không
   nhảy khi người dùng bật/tắt toggle, và khớp đúng phương pháp percentile
   STEP 0 đã dùng khi thử nghiệm 20 tour.

5. **Ranh giới sync/Batch hiện ngay trên UI trước khi bấm**, không chỉ phản
   ứng sau response — `INLINE_SYNC_MAX = 100` (khớp `v1_atoms.py`'s AA-305
   floor) hard-code trên frontend, hiện dòng cảnh báo "chạy đồng bộ, chờ
   ngay" hay "vào hàng đợi Batch, bất đồng bộ" ngay khi số tour được chọn
   thay đổi.

6. **Response inline path không có danh sách `tour_id` thành công**, chỉ có
   `succeeded` (số đếm) — đọc `_decompose_inline()` xác nhận (STEP 0). Vì
   vậy link "Xem trong Atom Curation" sau khi chạy chỉ deep-link
   `?tour_id=` khi đúng 1 tour được chọn (frontend tự giữ lại
   `submittedTourIds` từ trước khi gọi API); chọn nhiều tour thì link về
   trang Curation không lọc.

7. **Thêm hỗ trợ `?tour_id=` vào `/admin/curation` (frontend-only)** — đọc
   `window.location.search` trong `useEffect` thay vì `useSearchParams()`
   của Next để tránh yêu cầu bọc `<Suspense>` (không trang admin nào khác
   trong repo dùng hook đó). Không sửa `admin_atoms.py` — endpoint
   `GET /admin/atoms` đã hỗ trợ filter `tour_id` sẵn từ AA-300, chỉ cần nối
   dây ở frontend.

---

## Changed

- `api/routers/admin_pipeline.py`
  - `GET /admin/tours` (`get_all_tours`): thêm WHERE clause NULL-safe (copy
    nguyên văn pattern `v_trip_registry`, migration 083) — loại
    trashed/deleted/rỗng-itinerary, GIỮ tour đã publish.
  - Endpoint mới `GET /admin/tours-for-atomization` — trả tour từ
    `v_trip_registry` kèm `itinerary_length`, `itinerary_length_percentile`,
    `atom_count`, `has_atoms`, `is_thin` (dùng `THIN_TRIP_ATOM_MIN` có sẵn từ
    `services/acp_shared/atom_constants.py`, không viết logic mới), và
    `is_published` (đọc `vtr.aa_name IS NOT NULL`, có sẵn trong view — không
    JOIN thêm).
- `frontend/app/admin/atomize/page.tsx` (mới) — trang chọn tour + trigger
  decompose.
- `frontend/app/api/atoms/[...path]/route.ts` (mới) — proxy same-origin cho
  `/v1/atoms/*`, copy nguyên văn pattern `app/api/pipeline/[...path]/route.ts`
  (chưa có proxy nào cho `/v1/atoms` trước AA-345).
- `frontend/app/admin/curation/page.tsx` — đọc `?tour_id=` từ URL, truyền
  vào filter `GET /api/admin/atoms`, hiện banner "Filtering to one tour" +
  nút Clear.
- `frontend/middleware.ts` — thêm `/admin/atomize` vào `PROTECTED_ROUTES`
  (admin/reviewer/content, giống `/admin/curation`) — bài học AA-384: thiếu
  dòng này thì trang live-broken (redirect /login) dù code đúng, tsc/build
  không bắt được lỗi này.
- `frontend/app/admin/_components/AdminSidebar.tsx` — thêm mục nav "Atom hoá
  (N2)" giữa Master Content và Atom Curation.
- `tests/unit/test_aa345_atomize.py` (mới) — 11 test, xem Should know.

## Tradeoffs

- **Không tự chọn 1 con số threshold độ dài/ngày để chặn auto-decompose** —
  giữ nguyên kết luận STEP 0 Phần 4-5 (bằng chứng thực tế lật ngược giả
  định ban đầu của issue). UI không chặn tour nào trước khi atom hoá; chỉ
  gắn badge THIN sau khi atom hoá xong, dựa trên atom_count thật.
- **Auto-trigger có điều kiện (Phần 3.2 của investigation) KHÔNG được build
  trong session này** — issue AA-345 (phần "THIẾT KẾ + BUILD") chỉ yêu cầu
  UI chọn-tay + nút, không yêu cầu auto-trigger khi ingest tour mới. Phần
  3.2 vẫn là thiết kế treo, chưa build.
- **`include_atomized` mặc định `false` có thể không đúng ý người dùng cuối
  cùng** — đây là quyết định tự chọn để giải quyết mâu thuẫn trong chính
  issue (xem Decision 3), Nghiep cần xác nhận lại khi live-verify.

## Should know

- Test mock `pool.acquire()`/`conn.fetch` theo đúng convention
  `test_aa300_admin_atoms.py` — gọi thẳng hàm router (không qua HTTP client),
  kiểm tra WHERE clause bằng cách đọc chuỗi SQL trong `conn.fetch.call_args`.
  Không test N2 decompose thật (đã verify live ở STEP 0 Phần 4, 20/20 tour
  thành công) — chỉ test 2 endpoint UI-facing.
- `npx eslint`/`npm run lint` trên frontend hiện có ~13 lỗi TỒN TẠI SẴN
  trên `main` (xác nhận bằng `git stash` rồi lint lại) — chủ yếu
  `react-hooks/set-state-in-effect` (rule mới, code cũ set-state trong
  effect ở nhiều nơi) và `@typescript-eslint/no-explicit-any`. Không phải
  lỗi do AA-345 gây ra — CI's "Lint" job (`.github/workflows/ci.yml`) CHỈ
  chạy `flake8` trên `api/ services/ shared/`, không chạy eslint/tsc trên
  frontend, nên không chặn merge. `flake8` sạch trên
  `api/routers/admin_pipeline.py` (đã chạy với đúng config CI).
  `npx tsc --noEmit` sạch trên toàn bộ thay đổi.
- `docker`/pytest/`tsc` là live-verify TỰ ĐỘNG duy nhất đã chạy trong session
  này — CHƯA có live-verify qua browser thật của Nghiep (bài học AA-389,
  S140). Trước khi đóng Done, Nghiep cần tự bấm qua:
  1. `/admin/atomize` — load danh sách, checkbox chọn 1-2 tour, bấm
     "Atom hoá", xem kết quả sync hiện đúng (không phải Batch, vì <100 tour).
  2. Link "Xem trong Atom Curation" sau khi chạy → xác nhận
     `/admin/curation?tour_id=...` lọc đúng, filter clear hoạt động.
  3. `/admin/tours` (S1 Rewrite) — xác nhận tour trashed/deleted không còn
     hiện, tour rỗng itinerary không còn hiện, tour đã publish VẪN hiện với
     badge Published như trước.
  4. Middleware — vào `/admin/atomize` bằng role content/reviewer, xác nhận
     không bị redirect `/login`.
- Chưa chạy migration nào (không cần — cả 2 endpoint chỉ đọc). Latest
  migration trong repo lúc build là `100` (không phải `099` như header
  `AA-CIS-App/.claude/CLAUDE.md` ghi — file đó đang stale, chưa cập nhật
  theo migration 100/AA-397/AA-398, không thuộc phạm vi AA-345).

---

## Local live-verify (2026-08-13, sau session build ở trên)

Chạy thật: backend (`uvicorn api.main:app`) nối `cis-tunnel` (localhost:15432)
vào RDS dev thật, frontend (`next dev`) trỏ `API_URL` sang backend local qua
shell env (không sửa `frontend/.env.local`), Playwright headless (JWT admin tự
mint bằng `_create_admin_jwt()`, cùng `JWT_SECRET` mặc định với backend local
— không cần mật khẩu thật). Chi tiết đầy đủ + số liệu trong báo cáo cuối
session chat; tóm tắt các phát hiện có ảnh hưởng tới code:

1. **Race condition thật, ĐÃ SỬA** — `frontend/app/admin/curation/page.tsx`:
   đọc `?tour_id=` qua `useEffect` (chạy SAU lần render đầu) khiến
   `loadAtoms()` bắn 2 request (1 không filter tại mount, 1 có filter sau khi
   effect resolve) — nếu request KHÔNG filter (payload lớn hơn) trả về SAU
   request CÓ filter, nó ghi đè `atoms` state, làm trang lúc hiện đúng lúc
   hiện sai (đã tái hiện live nhiều lần, không phải test flake). Fix: đổi
   sang lazy `useState(() => ...)` đọc `window.location.search` NGAY tại lần
   render đầu (có guard `typeof window === "undefined"` cho SSR) — chỉ còn 1
   request duy nhất, luôn đúng filter. Verify lại 5 lần liên tiếp, ổn định
   48/48 atom (đúng CLASSIC LAOS, tour test thật, không lẫn tour khác).
2. **Minor fix** — nút "Clear filter" chỉ reset state, không xoá `?tour_id=`
   khỏi URL → refresh lại tự áp filter lần nữa. Thêm `router.replace(...)`.
3. **Không phải bug — giới hạn môi trường local**: chạy N2 decompose thật từ
   máy cá nhân LUÔN fail ở bước AssumeRole satellite (acc1)
   (`AA-Bedrock-Invoker` chỉ trust ECS task role, không trust identity người
   dùng cá nhân — đúng thiết kế bảo mật, không phải lỗi code AA-345 hay
   IAM sai cấu hình). UI vẫn hiện đúng: sync (không giả Batch), lỗi thật
   từng tour rõ ràng, không silent-fail — đúng yêu cầu. Happy-path thật (atom
   sinh ra) đã verify trong STEP 0 (chạy trong đúng context ECS task role,
   20/20 tour thành công) — không lặp lại ở đây vì không thể từ local.
4. **Idempotency (source_hash) xác nhận qua API trực tiếp** (bypass local
   Bedrock-permission gap ở mục 3): re-run tour cùng hash → `status:
   "completed"`, `skipped: 1`, `reason: "source unchanged (hash match)"` —
   rõ ràng, không silent-fail. Checkbox chặn chọn lại tour đã atom hoá qua UI
   là quyết định GIỮ NGUYÊN (hỏi trực tiếp Nghiep giữa session verify) —
   không phải gap, là thiết kế đã xác nhận.
5. Số liệu thật đối chiếu đúng dự đoán: `GET /admin/tours` → 763 (từ 793,
   loại đúng 30 tour rỗng itinerary; 0 trashed/deleted hiện tại nên nhánh
   NULL-safety chưa có dữ liệu để lộ diện, nhưng vẫn đúng phòng thủ).
   `GET /admin/tours-for-atomization` mặc định → 628 = 763 − 135 (135 tour
   đã atom hoá thật, khớp với `include_atomized=true` → 763, `has_atoms`
   count = 135, `is_thin` count = 13). Badge "Published" hiện rõ ràng (pill
   xanh, "● PUBLISHED") trên `/admin/s1-rewrite` cho tour publish thật
   ("Exploring South Korea").
