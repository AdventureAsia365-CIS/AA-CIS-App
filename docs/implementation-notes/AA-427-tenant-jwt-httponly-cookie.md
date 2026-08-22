# AA-427 — httpOnly cookies cho tenant JWT (chống XSS token theft)

## Decisions

- **httpOnly Set-Cookie được mint ở Next.js BFF route mới (`/api/auth/tenant-login`), KHÔNG phải
  ở FastAPI `main.py`** — khác với chữ "sửa backend" literal trong issue. Lý do kỹ thuật bắt buộc:
  `tenant-login/page.tsx` (trước fix) gọi thẳng `https://api-cis.lumiguides.it.com` từ browser —
  khác origin với `https://aa-cis.lumiguides.it.com` (nơi `middleware.ts` chạy và đọc
  `request.cookies`). Nếu FastAPI set `Set-Cookie` trên response của nó, cookie đó chỉ thuộc domain
  `api-cis.lumiguides.it.com` — middleware.ts trên `aa-cis.lumiguides.it.com` KHÔNG BAO GIỜ thấy
  được (trừ khi set `Domain=.lumiguides.it.com` + `SameSite=None` — làm yếu CSRF posture so với
  `Lax`, và cần đổi CORS/fetch credentials — không có tiền lệ trong repo). Codebase đã có sẵn đúng
  pattern này cho admin (AA-232, `/api/auth/login/route.ts`): Next.js route cùng-origin với browser
  là nơi mint httpOnly cookie, FastAPI chỉ trả JWT qua JSON body cho lời gọi server-to-server (CORS
  không áp dụng cho server-to-server nên không bị chặn). AA-427 mirror đúng pattern đó cho tenant
  thay vì tạo cơ chế cookie cross-subdomain mới, rủi ro hơn và không nhất quán với AA-232/AA-252.
  → `api/main.py` (`/auth/tenant-login`, `/auth/verify-tenant`) **không đổi gì** — chúng vẫn chỉ
  được gọi server-to-server (từ middleware.ts, từ lib/auth-server.ts, và giờ từ BFF route mới), như
  trước giờ.
- **Response body của `/api/auth/tenant-login` KHÔNG chứa raw JWT** — chỉ trả `{ok:true}`. Nếu trả
  `token` trong JSON body (như `/api/auth/login/route.ts` admin vẫn làm, xem "Should know" bên
  dưới) thì httpOnly vô nghĩa: page JS/XSS đọc được response body dễ như đọc cookie thường. Đây là
  khác biệt có chủ đích so với pattern admin, không phải thiếu sót.
- **`/me` = `/api/tenant/me` (Next.js route), gọi lại `/auth/verify-tenant` sẵn có** — không thêm
  endpoint FastAPI mới, vì `/auth/verify-tenant` đã trả đúng field FE cần (`tenant_id`, `name`,
  `plan_tier`). Route mới chỉ là lớp mỏng: đọc cookie `cis_tenant_token` (httpOnly, chỉ server đọc
  được), verify, trả về profile — không bao giờ trả token ra ngoài.
- Cả 5 cookie (`cis_role`, `cis_tenant_token`, `cis_tenant_id`, `cis_tenant_name`,
  `cis_tenant_plan`) đều set httpOnly theo đúng yêu cầu issue, dù thực tế chỉ `cis_role` +
  `cis_tenant_token` được server code nào đó đọc lại (middleware.ts, `/api/tenant/[...path]`).
  3 cookie còn lại giờ "trơ" (không ai đọc, kể cả server) nhưng vẫn giữ để không đổi shape/behaviour
  ngoài phạm vi issue — sẵn sàng cho route BFF tương lai cần tenant context nhanh không phải gọi API.

## Changed

- **Mới** `frontend/app/api/auth/tenant-login/route.ts` — BFF login, set 5 cookie httpOnly.
- **Mới** `frontend/app/api/auth/tenant-logout/route.ts` — clear 5 cookie server-side (JS không
  còn xoá được cookie httpOnly bằng `document.cookie = "...; max-age=0"` nữa).
- **Mới** `frontend/app/api/tenant/me/route.ts` — `/me`, trả `{tenant_id, tenant_name, plan_tier}`.
- `frontend/lib/auth-server.ts` — `requireTenant()` mở rộng trả thêm `name`, `planTier` (BE
  `/auth/verify-tenant` vốn đã trả 2 field này, chỉ chưa surface ra type). Không có caller live nào
  khác của `requireTenant()` trước đây (dead code, xem grep lúc audit) nên không breaking.
- `frontend/app/tenant-login/page.tsx` — gọi `/api/auth/tenant-login` (same-origin) thay vì gọi
  thẳng `API_URL`; xoá toàn bộ 5 dòng `document.cookie = ...`.
- `frontend/app/(tenant)/portal/page.tsx` — xoá helper `getCookie()`; đọc `tenant_name`/`plan_tier`
  qua `fetch("/api/tenant/me")` thay vì `document.cookie`.
- `frontend/app/(tenant)/portal/_components/Sidebar.tsx` — `logout()` gọi
  `POST /api/auth/tenant-logout` thay vì vòng lặp `document.cookie = "...max-age=0"`.
- `frontend/app/(tenant)/portal/_components/PlaceholderTabs.tsx` — nút "Sign Out of All Sessions"
  cùng thay đổi như Sidebar.

## Tradeoffs

- Không đụng CORS / `SameSite=None` cross-subdomain cookie — đổi lại phải thêm 3 Next.js route mới
  thay vì "chỉ sửa 2 dòng trong main.py". Đánh giá: an toàn hơn (giữ `SameSite=Lax`), nhất quán với
  pattern admin đã audit (AA-232/AA-252/AA-253), và không cần đổi backend đang chạy production.

## Should know

- **Phát hiện ngoài phạm vi (KHÔNG fix ở đây):** admin login (`/api/auth/login/route.ts`, AA-232)
  vẫn trả `token` trong JSON body ("stored client-side too") và `login/page.tsx` vẫn tự set
  `cis_api_token` không-httpOnly từ giá trị đó — tức JWT admin thực chất vẫn bị lộ qua response body
  + 1 cookie plain, dù `cis_admin_token` (cookie thật middleware dùng) đã httpOnly từ AA-232. Đây là
  lỗ hổng tương tự AA-427 nhưng ở phía admin, chưa có issue riêng — nên báo Nghiệp cân nhắc mở issue
  follow-up.
- `components/LogoutButton.tsx` không được import ở bất kỳ đâu trong app (dead code, xác nhận bằng
  grep) — không đụng vào, không nằm trong 5 cookie tenant (`cis_tenant_key` không tồn tại trong
  scheme hiện tại).
- `app/(tenant)/portal/page.tsx.bak` và `.bak.old` là file backup cũ, Next.js không route tới
  (không phải `page.tsx`) — có đọc cookie tenant theo cách cũ nhưng là dead file, không sửa.
- TTL 24h: audit nhanh — hợp lý cho B2B tenant portal (không phải phiên nhạy cảm cao, khớp với
  admin JWT cũng 24h), giữ nguyên, không đổi.
- Verify thật (response header + document.cookie trước/sau + luồng FE) — xem cuối file này, phần
  "## Verify" (được điền sau khi chạy live).
