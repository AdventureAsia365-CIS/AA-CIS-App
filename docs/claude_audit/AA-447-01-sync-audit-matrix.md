# AA-447-01 — BE+FE+Hạ tầng Sync Audit Matrix (A0-A4, T0-T11)

Investigate + tổng hợp only, không sửa code. Branch `feature/aa-447-sync-audit-matrix`, worktree
`../aa-447-worktree`. Tổng hợp từ `AA-437-00→02`, `AA-438-00→04`, `AA-439-00→08`, `AA-440`,
`AA-441`, `AA-443`, `AA-444` (commit, không có implementation-notes file riêng — xem ghi chú),
`AA-445-01/02` — **không điều tra lại những gì các báo cáo đó đã xác nhận bằng live query/code
read**, chỉ verify lại phần ADR baseline nghi ngờ đã lỗi thời (đúng theo scope task) + đọc trực
tiếp code sidebar/route thật (2 file `Sidebar.tsx`/`AdminSidebar.tsx`, đọc toàn bộ, không suy
đoán) để xác nhận layer FE-navigation thật.

**⚠️ Giới hạn phiên này**: AWS session (`aa365-admin`) hết hạn giữa phiên, yêu cầu MFA tương tác
— không tự nhập được. **Không chạy được query DB/ECS-exec mới trong phiên này.** Mọi bằng chứng
"traffic/data thật gần đây" dưới đây kế thừa từ các live query đã chạy trong `AA-437→445` (tất cả
trong vòng 22-23/08/2026, rất mới) — trích dẫn rõ nguồn + ngày cho từng con số, không tự nhận là
query mới. Mọi bằng chứng **route/sidebar/code** dưới đây LÀ đọc trực tiếp trong phiên này (không
kế thừa), vì không cần DB.

**Headline: 12/16 stage đã ĐỒNG BỘ hoặc gần đồng bộ; 4 gap thật, lớn — T7 (0 FE dù BE có), T8
(quyết định viết lại từ đầu, chưa bắt đầu), T11 (BE chưa tồn tại), và 1 bug BE nghiêm trọng mới
xác nhận: N5/N6 (tiêu thụ chính của T7) không đọc được atom T5 của tour pool chung — đã có sẵn
trong tài liệu AA-440 §1c (22/08), giờ đã live-verify thật (AA-445-02, 23/08) — biến cả câu
chuyện "distinctiveness giờ tính thật" (AA-445-02) thành vô nghĩa với N5/N6 cho tới khi fix.**

---

## Bảng ma trận đầy đủ (16 stage)

| Stage | BE | FE | Hạ tầng | Kết luận | Ghi chú |
|---|---|---|---|---|---|
| **A0** Raw Ingest (S0) | ✅ Real, live — `admin_pipeline.py` upload handlers, `raw_tours` 793 rows | ✅ `/admin/upload`, sidebar "Upload (S0)" (AdminSidebar.tsx:38) | ✅ `raw_tours` table, no gaps | ✅ **ĐỒNG BỘ** | AA-438-01. 1 nghi vấn double-fire Lambda+in-process chưa confirm (không chặn dùng) |
| **A1** Generic Rewrite (S1) | ✅ Real, live — `_execute_run_tour`→`graph.py`, DFS wired (`admin_pipeline.py:474`) | ✅ `/admin/s1-rewrite`, sidebar "S1 Rewrite" | ✅ `generated_content` | ✅ **ĐỒNG BỘ** | AA-438-01 |
| **A2** Admin QA Gate (Review Queue) | ✅ Real, live — self-repair + hitl branch, reject status-reset fixed (AA-441 bug#5, live HTTP verified) | ✅ `/admin/review`, sidebar "Review Queue" | ✅ `review_queue` (41 N0-N6 rows) | ✅ **ĐỒNG BỘ** | AA-438-02; bug#5 (reject không reset status) đã fix + live-verify 23/08 |
| **A3** Master Content Pool | ✅ Real, live — partial-UPSERT bug đã fix (AA-441 bug#3, 18/18 cột) | ✅ `/admin/master-content`, sidebar "Master Content" | ✅ `published_tours` (71 rows) | ✅ **ĐỒNG BỘ** | AA-438-03; T1 filter gap (bug#6, master_status/deleted_at) cũng đã fix AA-441, live-verify |
| **A4** Cross-Tenant Oversight | ✅ Real, live — `admin_a4.py` (2 endpoint), post-deploy live HTTP verify 200 thật | ✅ `/admin/a4-oversight`, sidebar "Cross-Tenant Oversight" (AdminSidebar.tsx:222-224, đọc trực tiếp phiên này, xác nhận có) | ✅ Tái dùng `review_queue`+`packets`, không cần bảng mới | ✅ **ĐỒNG BỘ** | Baseline ADR nói "chưa" (21-22/08) — ĐÃ LỖI THỜI, build+deploy+live-verify xong 23/08 (AA-437-01/02), PR #196 merged |
| **T0** Brand Identity Setup | ✅ Real, live — `_resolve_brand_tenant_id()` fix + upload multipart fix, **live HTTP verify thật với tenant JWT thật, KHÔNG cần admin secret** (AA-441 post-deploy) | ✅ `/portal/t0-brand`, sidebar "Brand Identity" (Sidebar.tsx:28) — **PLUS tab "Competitors" mới (AA-445-02)** cùng route, cùng sidebar entry | ✅ `shared.tenant_brand_rules` + `acp_silver_s2.competitor_inputs` (tái dùng, không bảng mới) | ✅ **ĐỒNG BỘ** | Baseline "FE chưa test qua UI thật" — vẫn đúng nghĩa đen (không có headless browser trong môi trường này, AA-443/AA-437-02 đều tự nêu giới hạn này) nhưng route+sidebar+BE live-HTTP đã xác nhận tối đa có thể không cần trình duyệt thật |
| **T1** Tour Selection / Browse Pool | ✅ Real, live — `trigger_rewrite()` chạy full T2→T3→T5 1 job (AA-425/436), filter gap đã fix (AA-441 bug#6) | ✅ `/portal/t1-rewrite`, sidebar "Browse Pool" — **NHƯNG label vẫn "Rewrite"/"Rewrite N tours" cứng** (`PoolTab.tsx:141,444`, đọc trực tiếp phiên này, xác nhận 0 chữ nào nhắc T3/T5/QA) | ✅ `tenant_tour_versions` | ⚠️ **LỆCH TẦNG (nhẹ)** | BE+FE đều "có" và tenant tự thấy được — nhưng UI polish gap ADR nêu ("label cũ, không hiện kết quả T3/T5") **vẫn đúng, chưa ai sửa** — xác nhận bằng đọc code trực tiếp phiên này, không phải đoán |
| **T2** Tenant Rewrite | ✅ Real, live — `_rewrite_tour()`, cùng job T1, DFS giờ CÓ (AA-445-02, live-verify thật `quality_score=10.00`) | — (đúng thiết kế, chạy ẩn, không có route riêng) | ✅ `tenant_tour_versions.rewritten_content` | ✅ **ĐỒNG BỘ** (theo đúng thiết kế "1 job ẩn") | AA-439-01 + AA-445-02 live E2E |
| **T3** Tenant QA Gate | ✅ Real, live — escalate-continue (AA-436), `qa_auto_passed` cột thật, DFS giờ vào tới cả vòng repair (AA-445-02) | ✅ **ĐÚNG quyết định ADR §0.1 (22/08)**: KHÔNG có route riêng — badge nhẹ trên T4 (`QaAutoPassBadge`, `CatalogTab.tsx`, xác nhận AA-439-02) | ✅ `review_queue.tenant_tour_version_id`, `escalate_detail` jsonb | ✅ **ĐỒNG BỘ** | Baseline ADR mục 4/10.4 ("Build mới — tenant xem diagnosis") đã bị chính ADR mục 0.1 tự sửa thành "không route riêng" — code hiện tại khớp ĐÚNG quyết định mới, không khớp bản cũ (đúng là điều nên xảy ra) |
| **T4** Tenant Tour Pool / My Catalog | ✅ Real, live — edit/approve/reject, polling 5s | ✅ `/portal/t4-pool`, sidebar "My Catalog" | ✅ `tenant_tour_versions` (23 rows, 5 tenant) | ⚠️ **LỆCH TẦNG (nhẹ)** | AA-439-02: T4→T6 **0 nav 2 chiều** — tenant không biết rewrite tạo ra atom trừ khi tự tìm "Atom Curation" trong sidebar riêng. T5 atom-count cũng không hiện trên T4 |
| **T5** Atomize | ✅ Real, live, **giờ có scoring thật** (AA-445-02: `score_distinctiveness()` live-verify 7 atom = HIGH, không còn default) | — (đúng thiết kế, chạy ẩn cùng job T2-T4) | ✅ `acp_contract.tour_atoms` (owner_scope=tenant_id) + `acp_shared.competitor_index_cache` (migration 111, applied live) | ✅ **ĐỒNG BỘ** | Nâng cấp từ trạng thái "Live, unscored" (AA-439-03) — atom MỚI (sau AA-445-02) có distinctiveness thật; atom CŨ (15 atom tenant-scope trước đó) vẫn LOW mãi mãi, không backfill |
| **T6** Atom Curation | ✅ Real, live — owner_scope filter đúng, AA-431 | ✅ `/portal/t6-atoms`, sidebar "Atom Curation" (Sidebar.tsx:29) | ✅ `acp_contract.tour_atoms` | ✅ **ĐỒNG BỘ** | Baseline ADR mục 10.4 ("100% admin-only, 0 filter tenant") **ĐÃ LỖI THỜI ngay trong ADR** — `/portal/t6-atoms` là build thật AA-431, tenant-scoped, sidebar có, xác nhận AA-439-03 + đọc trực tiếp Sidebar.tsx phiên này |
| **T7** Content Planning / Quarter Plan | ⚠️ Real logic (`compute_quarter_plan`, `allocator.py`) NHƯNG **2 bug thật chặn dùng**: (1) Gate B hardcode "Ms. Thu" chưa gỡ (AA-440 §1b); (2) **`fetch_atoms_by_trip()` join sai `raw_tours.tenant_id` thay vì `owner_scope`** — đã biết từ AA-440 §1c (22/08), **live-verify thật 2 lần trong AA-445-02 (23/08): 0 trips/0 atoms cho tenant có 15 atom T5 thật** | ❌ **KHÔNG CÓ ROUTE NÀO** — xác nhận `find "frontend/app/(tenant)/portal" -iname "*t7*"` = rỗng, và `Sidebar.tsx` (đọc toàn bộ) không có mục nào tên "Content Planning"/"Quarter Plan"/T7 — khớp ĐÚNG ảnh chụp thật Nghiệp gửi | ✅ `acp_shared.quarter_plan`/`quarter_plan_version` (9 row thật, tenant_id có) — hạ tầng sẵn sàng, không phải vấn đề hạ tầng | ⚠️→❌ **LỆCH TẦNG NẶNG** (gần như CHƯA CÓ nếu tính từ góc nhìn tenant) | Admin-side "Quarter Plan (Gate B)" trong AdminSidebar CÓ (dòng 208-210) nhưng đó là admin duyệt CHO tất cả tenant, không phải tenant tự dùng. **Tenant hoàn toàn không có cách nào chạm vào T7** — không route, không link từ T6, không gì cả |
| **T8** Angle Generation + Selection Gate | ⚠️ Code thật, ĐẦY ĐỦ tồn tại (`acp_s4_social/angles.py`+`handler.py`+`formula.py`) NHƯNG **quyết định viết lại HOÀN TOÀN, không dùng code này** (ADR §0.5, 22/08) — 0 caller, 0 row `social_content`, ever | ❌ 0 — route cũ (`v1_s4_social.py`) 100% admin-secret-only, và **chính admin sidebar cũng ẩn nhóm ACP v1 này đi** (`AdminSidebar.tsx:241-244` comment "AA-390... hidden... reachable directly by URL if ever needed again") — kể cả admin cũng không tự thấy | ✅ `acp_silver_s4.social_content` table tồn tại nhưng 0 row | ❌ **CHƯA CÓ** (đúng nghĩa, kể cả code cũ cũng coi như không tồn tại theo quyết định) | AA-439-06/07 + ADR §0.5: build T-series mới từ đầu, tham khảo không copy. 8 goal đã chốt (bỏ goal thứ 9), `Channel Output Structures.xlsx` chưa port |
| **T9** Final Content Write | ✅ Real, live-capable — E1/E2/E3 (`generation.py`/`adapt.py`), Sonnet thật, chỉ 2/7 kênh (fb/tiktok) có adapt | ❌ 0 — chỉ chạy qua N7 admin trigger (`admin_produce.py`), không path tenant nào | ✅ `acp_deliver.pieces` (135 row thật, 10 passed) | ⚠️ **LỆCH TẦNG** | AA-439-08: docstring cũ nói "chưa tồn tại" — LỖI THỜI, code thật hoạt động. Nhưng bị khoá sau T8 (chưa rebuild) nên tenant không chạm được |
| **T10** Quality/Editor Pass | ✅ Real, live, đang giữ pieces thật — F1-F9 gate stack (`gates.py`), held_reason có bằng chứng cụ thể (F8=24, F2=3, F3=5, F9=2, F1=1) | ❌ 0 — cùng lý do T9 | ✅ Cùng bảng `acp_deliver.pieces` | ⚠️ **LỆCH TẦNG** | AA-439-08. Xác nhận KHÁC hệ thống T3 (chỉ share 1 hàm grounding nhỏ, không phải cùng gate stack) |
| **T11** Publish/Distribute | ❌ **Xác nhận không tồn tại, bằng chính docstring code**: `deliver_packet()` chỉ `UPDATE packets SET status='delivered'` — không có tích hợp API mạng xã hội nào, grep toàn repo 0 hit | ❌ 0 | ⚠️ `acp_shared.usage_log` (bảng kế toán delivery) **không tồn tại trong DB** — xác nhận thêm 1 lớp nữa T11 chưa từng chạy | ❌ **CHƯA CÓ** | AA-439-08 §3-4. Khớp CHÍNH XÁC ADR (T11 "= N8, vẫn chưa tồn tại") |

---

## Sidebar thật — full enumeration, cả 2 portal (đọc trực tiếp code phiên này, không suy đoán)

### Tenant portal (`frontend/app/(tenant)/portal/_components/Sidebar.tsx`, đọc toàn bộ 171 dòng)

| Group | Label | Route | Map vào stage nào |
|---|---|---|---|
| Workspace | Dashboard | `/portal/dashboard` | — (tổng quan, không phải T-stage) |
| Workspace | Browse Pool | `/portal/t1-rewrite` | **T1** |
| Workspace | My Catalog | `/portal/t4-pool` | **T4** (badge T3 hiện ở đây) |
| Workspace | Brand Identity | `/portal/t0-brand` | **T0** (+ tab Competitors, AA-445-02) |
| Workspace | Atom Curation | `/portal/t6-atoms` | **T6** |
| Workspace | Marketplace | `/portal/marketplace` | Không phải T-stage — xem mục riêng bên dưới |
| Workspace | API Access | `/portal/api` | — (utility, không T-stage) |
| Account | Activity Log | `/portal/activity` | — (utility) |
| Account | Billing | `/portal/billing` | — (utility) |
| Account | Settings | `/portal/settings` | — (utility) |

**KHÔNG có mục nào cho T7, T8, T9, T10, T11** — xác nhận bằng đọc toàn bộ file, không phải đếm
thiếu. T2/T3/T5 đúng thiết kế không cần mục riêng (chạy ẩn trong job T1). **T7 là stage DUY NHẤT
có business logic thật (BE) mà hoàn toàn không có route/link nào ở tầng tenant** — T8-T11 ít
nhất "có lý do" (chưa build/chưa quyết định xong); T7 thì BE đã sẵn sàng dùng được (theo AA-440,
chỉ cần gỡ 2 chỗ) nhưng FE = 0 tuyệt đối.

### Admin portal (`frontend/app/admin/_components/AdminSidebar.tsx`, đọc toàn bộ 263 dòng)

| Group (gate) | Label | Route | Map vào stage nào |
|---|---|---|---|
| ACP v2 — Setup & Approval (admin-only) | Dashboard | `/admin/dashboard` | — |
| ACP v2 — Setup & Approval (admin-only) | Tenants | `/admin/tenants` | N1 (không phải A/T-stage) |
| ACP v2 — Setup & Approval (admin-only) | Marketplace | `/admin/marketplace` | Admin-side catalog build (khác `/portal/marketplace`) |
| ACP v2 — Setup & Approval (admin-only) | Quarter Plan (Gate B) | `/admin/quarter-plan` | **T7's admin-side** (không phải tenant self-service) |
| ACP v2 — Setup & Approval (admin-only) | Produce & Deliver (N7/N8) | `/admin/produce` | **T8-T11's admin-side trigger + Gate C** |
| ACP v2 — Setup & Approval (admin-only) | Run Health | `/admin/run-health` | — (observability) |
| ACP v2 — Setup & Approval (admin-only) | Cross-Tenant Oversight | `/admin/a4-oversight` | **A4** |
| ACP v2 — Atoms (mọi role) | Atomize (N2) | `/admin/atomize` | N2 platform-scope, KHÔNG phải T5 (khác owner_scope, xem AA-438-00 phần "confirmed NOT bugs") |
| ACP v2 — Atoms (mọi role) | Atom Curation | `/admin/curation` | Admin-side superset của T6 |
| AA Internal Content (mọi role) | Upload (S0) | `/admin/upload` | **A0** |
| AA Internal Content (mọi role) | S1 Rewrite | `/admin/s1-rewrite` | **A1** |
| AA Internal Content (mọi role) | Review Queue | `/admin/review` | **A2** |
| AA Internal Content (mọi role) | Brand Identity | `/admin/brand` | Admin-side brand (aa_internal), khác `tenant_brand_rules` |
| AA Internal Content (mọi role) | Master Content | `/admin/master-content` | **A3** |
| (admin-only, riêng) | Settings | `/admin/settings` | — |

**Ghi chú quan trọng**: `AdminSidebar.tsx:241-244`'s comment tự thừa nhận nhóm ACP v1 cũ (S2
Research/S3 Calendar/S4 Blog/**S4 Social — đây chính là code T8 thật**) đã bị **ẩn khỏi sidebar
admin luôn**, theo quyết định Nghiệp ("AA-390... nobody needs ACPv1 access anymore"). Route/BE
vẫn còn, "reachable directly by URL" — nhưng đây đúng là cùng loại "có trang nhưng phải tự tìm"
task prompt nhắc tới ở Marketplace/Competitors, chỉ khác là ở đây THẬM CHÍ ADMIN cũng không tự
thấy được nữa, kể cả biết đường link cũng phải nhớ chính xác URL cũ, không có gợi ý nào.

---

## Marketplace — liên kết với T7 có thật chưa?

**Trả lời: KHÔNG — Marketplace (`/portal/marketplace`, AA-444) và Content Planning (T7) là 2
nguồn dữ liệu độc lập, không nối nhau.**

Bằng chứng (từ commit `30b57ae`/PR #197's own message, đọc trực tiếp `git show`):
> "New GET /v1/marketplace (api/routers/v1_marketplace.py): tenant-scoped rollup of
> `gold_aa_internal.tenant_tour_versions` JOIN `acp_contract.tour_atoms` (owner_scope), per
> ADR-2026-038 §0.3."

Marketplace đọc trực tiếp **T4 (tenant_tour_versions) × T6 (tour_atoms)** — tức là "những tour
tenant đã tự rewrite + atom của chúng", KHÔNG phải output của T7 (`quarter_plan`/`quarter_plan_
version`/slot allocation). Grep xác nhận: `v1_marketplace.py` không import gì từ
`services.acp_planning.*`. Hai khái niệm "Marketplace" (T4×T6 rollup, xem những gì mình đã có) và
"Content Planning" (T7, kế hoạch NÊN viết gì tiếp theo dựa trên runway/richness/distinctiveness)
là 2 tính năng khác nhau về bản chất, hiện KHÔNG có cầu nối code nào — không phải bug, chỉ là 2
tính năng độc lập chưa ai quyết định có cần nối hay không.

Ghi chú phụ: `docs/implementation-notes/AA-444-*.md` được CLAUDE.md trước đó trích dẫn nhưng
**không tồn tại trên đĩa** (`find` xác nhận 0 kết quả) — có khả năng chưa từng được `git add -f`
(giống trường hợp mọi file `docs/claude_tasks`/`docs/implementation-notes` khác trong repo này,
bị `.gitignore` chặn mặc định). Bằng chứng cho mục này dựa vào commit message + code thật, không
phải file ghi chú bị thiếu.

---

## Chi tiết theo stage — chỉ những gì MỚI/THAY ĐỔI so với báo cáo gốc (không lặp lại nguyên văn)

### A4 — từ "chưa" thành ĐÃ CÓ, đầy đủ
`AA-437-01` (STEP0, 23/08) → `AA-437-02` (build, 23/08, PR #196 merged `6652a66`) trong cùng
ngày. `api/routers/admin_a4.py` (`/admin/a4/review-log`, `/admin/a4/trust-ramp`), FE
`/admin/a4-oversight`, sidebar item thêm ngay cạnh Run Health (xác nhận đọc code, dòng
219-224). Post-deploy live HTTP verify: `GET /admin/a4/review-log?limit=200` → 200, 12 rows
thật; `GET /admin/a4/trust-ramp` → 200, 4 packets thật. Không cần migration mới.

### T0 — nâng cấp thêm cả Competitors (AA-445-02), không chỉ Brand
Baseline chỉ nói tới Brand Identity. Phiên 23/08 (AA-445-02, chính task trước của tôi) thêm hẳn
1 tab "Competitors" trong CÙNG route `/portal/t0-brand` — gọi thẳng `/v1/competitors` (AA-88, đã
có sẵn từ lâu nhưng 0 UI trước AA-445-02). Live E2E đã verify: mint JWT thật → thêm domain qua
API thật → distinctiveness atom mới ra HIGH thật (xem báo cáo AA-445-02 trong Linear AA-445).

### T7 — bug then đã biết trước, giờ mới live-verify thật
`AA-440` (22/08, §1c) đã ĐỌC RA chính xác bug này qua code + đếm row — nhưng chưa từng GỌI THẬT
hàm `fetch_atoms_by_trip()` để xem nó trả về gì. `AA-445-02`'s verify (23/08) là lần đầu tiên gọi
thật hàm này với 1 tenant có atom T5 thật — xác nhận **0 trips, 0 atoms**, đúng như AA-440 dự
đoán từ đọc code. Đây không phải finding mới về BẢN CHẤT bug, chỉ là bằng chứng THỰC THI mạnh hơn
cho 1 bug đã biết — không nên báo lại như thể là phát hiện lần đầu (đã sửa cách diễn đạt trong
comment Linear AA-445 trước đó, nhắc lại ở đây cho rõ nguồn).

### T8 — quyết định KHÔNG dùng code cũ, không phải "sẽ port"
ADR §0.5 (22/08) rất rõ: viết lại hoàn toàn, không mượn `acp_s4_social`. Điều này thay đổi ý
nghĩa của cột "BE" trong bảng — code `acp_s4_social` "tồn tại" theo nghĩa đen (files thật, chạy
được) nhưng theo quyết định sản phẩm thì coi như KHÔNG dùng được cho T8 — vì vậy tôi xếp T8 vào
❌ CHƯA CÓ, không phải ⚠️ LỆCH TẦNG, dù về mặt code thuần tuý có nhiều hơn T7.

---

## Đối chiếu AA-446 (sổ cái 40 bug/gap) — chưa làm trong phiên này

Task prompt yêu cầu Claude Chat (không phải phiên investigate này) đối chiếu ma trận này với
AA-446 để quyết định thứ tự ưu tiên cùng Nghiệp — việc đó nằm ngoài scope AA-447-01, không làm ở
đây.

## Open items — ngoài phạm vi phiên này

- Không re-run được live DB query mới (AWS MFA hết hạn giữa phiên) — mọi con số "traffic thật"
  kế thừa từ AA-437→445 (22-23/08), đã trích rõ nguồn từng chỗ, không phải suy đoán nhưng cũng
  không phải query mới của chính phiên này.
- Không có headless browser trong môi trường này (giới hạn đã nêu lặp lại ở AA-437-02/AA-443) —
  không xác nhận được UI render thật qua trình duyệt cho bất kỳ stage nào, chỉ xác nhận qua code
  + live HTTP response + build output.
- `docs/implementation-notes/AA-444-*.md` không tồn tại trên đĩa dù được CLAUDE.md trích dẫn —
  bằng chứng AA-444 dựa vào commit message + code thật thay thế, không chặn kết luận nhưng đáng
  lưu ý cho lần dọn dẹp docs tiếp theo.
