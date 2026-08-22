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
- **Bug tìm thấy + fix trong lúc verify live:** `cis_tenant_name` bị double percent-encode
  (`%2520` thay vì `%20`) ở version code đầu tiên — do tôi tự `encodeURIComponent()` giá trị TRƯỚC
  khi đưa vào `response.cookies.set()`, trong khi Next.js's `ResponseCookies.set()` (edge-runtime
  cookies, `stringifyCookie`) đã tự `encodeURIComponent` một lần khi serialize ra header
  `Set-Cookie`. Sửa: bỏ `encodeURIComponent()` thủ công, để Next tự encode. Xác nhận lại bằng
  `next build && next start` local + curl thật (xem log verify bên dưới) — trước fix:
  `cis_tenant_name=AA-427%2520Verify%2520Tenant`, sau fix:
  `cis_tenant_name=AA-427%20Verify%20Tenant`. Không ảnh hưởng bảo mật (giá trị này không server
  code nào đọc lại — xem Decisions), nhưng vẫn là bug thật, đã fix trước khi coi Done.

## Verify (thật — 22/08/2026, live)

Không verify được trực tiếp qua Vercel preview URL của PR #184 vì Vercel Deployment Protection
(SSO) chặn `curl` (401 "Protected deployment", cần đăng nhập Vercel SSO qua browser — không có
cách bypass bằng CLI trong phiên này). Thay vào đó verify bằng `next build && NODE_ENV=production
next start` chạy LOCAL, trỏ thẳng `API_URL` thật (`https://api-cis.lumiguides.it.com`, từ
`.env.local` sẵn có) — cùng 1 code Next.js vừa build từ branch AA-427, chỉ khác hạ tầng host
(local Node thay vì Vercel edge), backend/DB là thật 100%, không mock.

**Setup:** tạo 1 tenant test thật trong `shared.tenants` (qua S3-mediated ECS exec pattern, script
xoá sau khi xong) — `slug=aa427-verify-tenant`, `api_key_hash` = sha256 của
`cis_live_sk_aa427_verify_test_key_2026`, `is_active=true`. tenant_id: `640472c2-e52b-4432-b2ca-
712f9aa7fef5` (đã DELETE khỏi DB sau verify).

**1. POST /api/auth/tenant-login (đúng key) → response header:**
```
HTTP/1.1 200 OK
set-cookie: cis_role=tenant; Path=/; Expires=...; Max-Age=86400; Secure; HttpOnly; SameSite=lax
set-cookie: cis_tenant_token=eyJhbGci...; Path=/; Expires=...; Max-Age=86400; Secure; HttpOnly; SameSite=lax
set-cookie: cis_tenant_id=640472c2-e52b-4432-b2ca-712f9aa7fef5; Path=/; ...; Secure; HttpOnly; SameSite=lax
set-cookie: cis_tenant_name=AA-427%20Verify%20Tenant; Path=/; ...; Secure; HttpOnly; SameSite=lax
set-cookie: cis_tenant_plan=growth; Path=/; ...; Secure; HttpOnly; SameSite=lax

{"ok":true}
```
→ cả 5/5 cookie có `HttpOnly` + `Secure` + `SameSite=lax`. Response body chỉ `{"ok":true}` — JWT
KHÔNG xuất hiện ở đâu ngoài Set-Cookie header (khác admin flow cũ — xem "Should know" trên).
`HttpOnly` trên Set-Cookie header = trình duyệt CHẮC CHẮN loại cookie này khỏi `document.cookie`
theo spec (không có browser nào vi phạm điều này) — đây là bằng chứng tương đương, không cần chạy
thêm devtools để xác nhận riêng phần "document.cookie không thấy nữa".

**2. POST /api/auth/tenant-login (sai key) → 401**, body `{"detail":"Invalid API key"}`, KHÔNG có
`Set-Cookie` header nào — xác nhận không set cookie khi login thất bại.

**3. GET /api/tenant/me (dùng cookie httpOnly từ bước 1, mô phỏng đúng cách FE gọi):**
```
HTTP/1.1 200 OK
{"tenant_id":"640472c2-e52b-4432-b2ca-712f9aa7fef5","tenant_name":"AA-427 Verify Tenant","plan_tier":"growth"}
```
→ đúng field portal/page.tsx cần (`tenant_name`, `plan_tier`), không có `token`.

**4. GET /portal (qua middleware.ts) với cookie hợp lệ → 200** (không bị redirect) — xác nhận
middleware vẫn đọc được `cis_role`/`cis_tenant_token` từ `request.cookies` dù cookie httpOnly (đúng
như kỳ vọng: httpOnly chỉ chặn JS phía client, không chặn server đọc cookie đến từ request).

**5. GET /portal KHÔNG có cookie → 307 → Location: /tenant-login** — luồng chưa đăng nhập vẫn đúng.

**6. POST /api/auth/tenant-logout → Set-Cookie cả 5 cookie về rỗng + Max-Age=0**, sau đó gọi lại
GET /portal với cookie jar cũ → 307 redirect (xác nhận logout thật sự vô hiệu hoá session, không
chỉ xoá được ở phía client như code cũ).

**Kết luận:** luồng login → set cookie httpOnly → /me → middleware gate → logout hoạt động đúng
end-to-end với JWT thật, DB thật, backend live thật. FE build (`next build`) sạch, `tsc --noEmit`
0 lỗi, ESLint không phát sinh lỗi mới (3 lỗi pre-existing không liên quan, không sửa — ngoài
scope).
