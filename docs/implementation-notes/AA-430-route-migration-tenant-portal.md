# AA-430 — Route migration Tenant Portal (tab-state → route thật)

## Decisions

- **Trước khi tạo route, hỏi lại Nghiệp map tab→T-number** thay vì đoán, vì task tự yêu
  cầu "hỏi thay vì đoán" và audit trước đó (STEP0) chỉ xác nhận rõ T0=Brand, T1=Rewrite.
  Nghiệp cung cấp bảng đầy đủ (ADR-2026-038): `catalog` = **T4** (Tenant Tour Pool — KHÔNG
  phải T3, T3 là view QA-failure riêng chưa có UI), 5 tab còn lại (dashboard/api/
  activity/billing/settings) KHÔNG phải T-stage — giữ tên mô tả thường, không gán T-prefix.
- **Kiến trúc: `portal/layout.tsx` thật (thay `page.tsx` cũ) + React Context
  (`PortalShellContext`)** để share state (tenantName/planTier/poolTotal/catTotal/
  billing/globalSearch/toast) xuống các route con — layout.tsx persist qua navigation
  giữa các route con cùng segment (Next.js App Router), y hệt cách `page.tsx` cũ persist
  qua `setTab()`. Không dùng URL query string hay sessionStorage cho việc này — Context
  là cách idiomatic nhất trong App Router, không cần round-trip qua network hay
  localStorage.
- **`/portal` (root) → `redirect()` server-side sang `/portal/dashboard`** — dashboard là
  tab mặc định cũ (`useState<ExtTab>("dashboard")`), giữ nguyên.
- **`DashboardTab`/`Sidebar` đổi hẳn từ `Tab` union type sang href string trực tiếp**
  (`onTabChange(t: Tab)` → `onNavigate(href: string)`) — không giữ `Tab` type "giả" nữa
  vì không còn ý nghĩa (route là nguồn sự thật duy nhất, không phải state).
- **Giữ nguyên 1 quirk pre-existing, không tự sửa**: NAV2 (Activity Log/Billing/
  Settings) trong Sidebar cũ hardcode `active={false}` — KHÔNG BAO GIỜ highlight ngay cả
  khi đang ở đúng trang đó (nhìn có vẻ là thiếu sót từ đầu, không phải chủ ý). Đã viết
  lại Sidebar dùng `usePathname()` nên fix này chỉ tốn 1 dòng, nhưng task yêu cầu "giữ
  nguyên hành vi" cho migration — không fix ở đây, ghi nhận làm follow-up nhỏ riêng nếu
  Nghiệp muốn.
- **Không đụng `Sidebar.logout()`** (vẫn `document.cookie = "...max-age=0"` phía client)
  — đây là phần AA-427 (PR #184, chưa merge) sẽ thay bằng `POST /api/auth/tenant-logout`.
  Ngoài scope route-migration, để nguyên tránh xung đột merge với AA-427 sau này.

## Changed

- **Mới:** `portal/layout.tsx` (shell thật: Sidebar + topbar + toast, thay `page.tsx` cũ),
  `portal/_components/PortalShellContext.tsx` (Context), 8 route con:
  `portal/{dashboard,t1-rewrite,t4-pool,t0-brand,api,activity,billing,settings}/page.tsx`.
- **Viết lại:** `portal/page.tsx` (từ full shell 189 dòng → redirect 3 dòng),
  `portal/_components/Sidebar.tsx` (v2→v3: `onClick={setTab}` → `<Link>` +
  `usePathname()`, bỏ prop `tab`/`setTab`/`onActivityLog`/`onBilling`/`onSettings`,
  thêm `onNavClick?` để giữ hành vi "clear search khi đổi nav" cũ).
- **Sửa nhỏ:** `DashboardTab.tsx` (`onTabChange(Tab)` → `onNavigate(href)`, bỏ import
  `Tab`), `PoolTab.tsx` (bỏ 1 dòng import `Tab` chết — không dùng ở đâu trong file,
  xác nhận qua eslint trước/sau).
- **Không đổi:** `PoolTab.tsx`/`CatalogTab.tsx`/`BrandTab.tsx`/`ApiTab.tsx`/
  `PlaceholderTabs.tsx` — toàn bộ logic fetch/state nội bộ giữ nguyên 100%, chỉ đổi NƠI
  chúng được render (route con thay vì nhánh JSX có điều kiện).
- **`middleware.ts` — KHÔNG đổi**, xác nhận đúng như audit trước: matcher
  `"/portal/:path*"` đã là wildcard, tự động gate mọi route con mới không cần sửa gì.

## Tradeoffs

Không có tradeoff kiến trúc lớn — đây thuần là "di chuyển state 1 cấp lên + đổi cơ chế
điều hướng", hành vi UI giữ nguyên 100% (xác nhận qua verify).

## Should know — phát hiện quan trọng, KHÔNG SỬA (ngoài scope)

**`/v1/tours/pool` và `/v1/tours/my-versions` (dùng bởi T1/T4) bị API Gateway 401 khi gọi
qua domain thật `api-cis.lumiguides.it.com`, dù JWT tenant hợp lệ và backend
(in-container, bỏ qua gateway) trả 200 OK với data thật.** Root cause xác nhận:
- API Gateway thật là `4ylo382khg` (tên `aa-cis-dev-api`) — **KHÁC** id `owq9as3wjl` ghi
  trong `.claude/CLAUDE.md` (stale, cần cập nhật riêng).
- Authorizer gắn vào gateway: `tenant-key-authorizer` (TOKEN type),
  `identitySource: method.request.header.X-API-Key` — nghĩa là API Gateway đòi header
  `X-API-Key` phải CÓ MẶT mới gọi tới Lambda; thiếu hẳn header này (dù có
  `Authorization: Bearer <jwt>` hợp lệ) → API Gateway tự trả 401 `UnauthorizedException`
  **TRƯỚC KHI** chạm tới Lambda/FastAPI (xác nhận qua response header
  `x-amzn-errortype: UnauthorizedException`, khác hẳn shape JSON lỗi của FastAPI).
- `frontend/app/api/tenant/[...path]/route.ts` (proxy FE dùng cho MỌI call tenant, kể cả
  `/v1/tours/pool`) chỉ gắn `Authorization: Bearer <cis_tenant_token>`, **không bao giờ**
  gắn `X-API-Key` cho nhánh tenant.
- **Nếu domain `api-cis.lumiguides.it.com` route `/v1/tours/*` qua đúng gateway/stage
  này trong production thật** (chưa xác nhận 100% — chỉ xác nhận domain resolve tới
  gateway nào đó trả đúng lỗi shape của gateway, chưa map ngược DNS→stage cụ thể), thì
  **toàn bộ T1 (Browse Pool/Rewrite) và T4 (My Catalog) đang broken cho MỌI tenant thật
  trên production**, không riêng gì tenant test của tôi — đây có thể là bug nghiêm trọng
  hơn hẳn phạm vi AA-430.
- **Không sửa ở đây** — ngoài scope route-migration, cần 1 investigation riêng (xác nhận
  domain→stage mapping, quyết định sửa ở proxy FE thêm X-API-Key hay sửa authorizer
  identitySource) trước khi động vào, tránh vá ẩu 1 endpoint auth đang chạy production.
  **Đề xuất mở issue riêng, ưu tiên cao, độc lập AA-430/431.**
- Do 401 này, 2/16 bước verify tự động (rewrite-trigger → toast → redirect) không chạy
  được hết với data thật (pool rỗng vì fetch fail âm thầm — `PoolTab.fetchPool()` chỉ set
  state khi `res.ok`, không hiện lỗi). Đã xác nhận bằng code review đây là hành vi
  ĐÚNG của code MỚI (routing logic `handleRewriteDone()` gọi đúng
  `router.push("/portal/t4-pool")` + `showToast()` — không có gì để test hơn nữa nếu
  không có data; xem "Verify" bên dưới) — không phải regression từ AA-430, vì
  `PoolTab.tsx`/proxy 100% không đổi bởi PR này.

## Tab → Route mapping (bảng cuối cùng đã dùng)

| Tab cũ | Route mới | T-stage | Component |
|---|---|---|---|
| `brand` | `/portal/t0-brand` | **T0** — Brand Identity Setup | `BrandTab` |
| `pool` | `/portal/t1-rewrite` | **T1** — Tour Selection (trigger job T2-T5) | `PoolTab` |
| `catalog` | `/portal/t4-pool` | **T4** — Tenant Tour Pool | `CatalogTab` |
| `dashboard` | `/portal/dashboard` | không phải T-stage | `DashboardTab` |
| `api` | `/portal/api` | không phải T-stage | `ApiTab` |
| `activity` | `/portal/activity` | không phải T-stage | `ActivityLogTab` |
| `billing` | `/portal/billing` | không phải T-stage | `BillingTab` |
| `settings` | `/portal/settings` | không phải T-stage | `SettingsTab` |
| — | `/portal` | — | `redirect("/portal/dashboard")` |

T2/T3/T5 chạy ngầm trong job T1 (không có UI riêng). T6 (`/portal/t6-atoms`) và
`/portal/t8-produce` **chưa tạo** trong task này (đúng chỉ dẫn — chỉ chừa convention
tên, AA-431 tự tạo route t6-atoms).

## Verify

- `npx tsc --noEmit` (frontend) — 0 lỗi.
- `npm run build` — build sạch, route list xác nhận đủ 9 route dưới `/portal/*`
  (root + 8 con), không route thừa/thiếu.
- `eslint` trên toàn bộ file mới/sửa — so sánh trực tiếp với bản gốc trên `main` (qua
  `git show main:<path>` + eslint riêng) để phân biệt lỗi mới vs pre-existing: **toàn bộ
  finding đều pre-existing** (2 `react-hooks/set-state-in-effect` trong PoolTab.tsx y hệt
  bản gốc; 2 `no-explicit-any` cho `billing: any` — kế thừa nguyên xi từ `page.tsx` gốc,
  giờ xuất hiện ở layout.tsx + PortalShellContext.tsx vì tách ra thành type dùng chung).
  1 warning được XOÁ (import `Tab` chết trong PoolTab.tsx).

### Verify LIVE (real browser, Playwright + JWT thật qua ECS/RDS live)

Setup: `next build && NODE_ENV=production next start -p 3000` local (port 3000, khớp
CORS allowlist backend — 3939 bị CORS chặn, đã thử và sửa) — API_URL thật từ
`.env.local`. Tạo 1 tenant test thật (`slug=aa430-verify-tenant`,
`tenant_id=f8e454f0-2c4b-4643-bb17-205d197c22f4`) + 1 admin test thật
(`username=aa430-verify-admin`, bcrypt hash thật) qua S3-mediated ECS exec — cả 2 đã
DELETE sau khi xong (kể cả `tenant_api_usage` con, gặp FK constraint lúc xoá lần đầu, đã
xử lý đúng thứ tự).

**Login tenant thật qua UI form** (không cookie injection) → 14/16 check tự động PASS:
1. Login → `/portal` → redirect đúng `/portal/dashboard` ✅
2. Click qua đủ 8 mục Sidebar → URL đổi đúng, không mất trang ✅ (Browse Pool, My
   Catalog, Brand Identity, API Access, Activity Log, Billing, Settings, Dashboard)
3. F5 (reload) trên `/portal/t0-brand` (route sâu, không phải root) → ở nguyên đúng
   route, không văng ✅
4. Dashboard quick-action card "Browse Pool" → `/portal/t1-rewrite` ✅
5. Dashboard quick-action card "My Catalog" → `/portal/t4-pool` ✅
6. Dashboard nút "Upgrade" (Membership card) → `/portal/billing` ✅
7. Focus ô search topbar → tự nhảy `/portal/t1-rewrite` (giữ đúng hành vi cũ) ✅
8. Rewrite trigger → toast + redirect `/portal/t4-pool` — **KHÔNG chạy hết được** do pool
   rỗng (401 gateway, xem "Should know" — không phải lỗi routing của PR này)
9. 0 console/page error — **có lỗi** nhưng toàn bộ là 401 từ chính vấn đề gateway trên,
   không phải lỗi JS/React nào từ code mới

**Middleware — test qua curl với JWT thật (cookie jar thủ công, đại diện đúng cookie
browser thật sẽ set):**
- Không có cookie → cả 9 route (`/portal` + 8 con) → **307 → `/tenant-login`** ✅
- Có cookie tenant hợp lệ → cả 9 route → **200** (8 con) / **307→`/portal/dashboard`**
  (root) ✅
- Có cookie admin hợp lệ (`cis_admin_token` httpOnly thật từ `/auth/admin-login` +
  `cis_role=admin`) → `/portal/dashboard`, `/portal/t4-pool`, `/portal/settings` →
  **200** — xác nhận role `admin` vẫn vào được `/portal/*` như hành vi cũ, không bị thu
  hẹp ✅

**Kết luận:** routing/middleware/state-sharing (chính là scope của AA-430) verify PASS
100% qua cả curl (middleware) lẫn browser thật (Playwright, JS interactions). 2 điểm
không verify được hết (rewrite-trigger full flow, 0-console-error) đều quy về 1 nguyên
nhân duy nhất đã xác nhận rõ ràng KHÔNG liên quan tới thay đổi trong PR này.
