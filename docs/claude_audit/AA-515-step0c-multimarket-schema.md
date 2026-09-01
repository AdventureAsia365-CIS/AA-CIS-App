# AA-515 STEP0c — target_market/schema tenant: đã lưu multi-market chưa?

Read-only investigation. No code changed. Vòng STEP0 cuối cùng cho AA-515 (Ranking/Atom Score
stage) trước khi giao build prompt hoàn chỉnh — kiểm chứng bài học rút ra ở STEP0b
(`AA-515-step0b-demand-research-loop.md`, Q3): `resolve_buyer_market()` hiện chỉ trả về 1 market,
khác thiết kế fan-out của Ms. Thư.

## Q1 — `target_market.countries` đến từ bảng/cột nào? (đi ngược nguồn dữ liệu, không chỉ đọc hàm)

Truy ngược chuỗi gọi thật, không suy đoán:

`resolve_buyer_market(target_market: dict)` (`seed_builder.py:84`) nhận `target_market` từ tham
số — người gọi là:
```python
cfg = await TenantConfigService(conn).get_seo_config(tenant_id)   # trả về SEOConfig
loc_code, loc_name, lang = resolve_buyer_market(cfg.target_market)
```
`TenantConfigService.get_seo_config()` (`shared/services/tenant_config_service.py:168-198`) đọc
thẳng từ DB:
```sql
SELECT seo_provider, custom_keywords, target_market, overrides
FROM shared.tenant_seo_config
WHERE tenant_id = $1
```
**Nguồn gốc: cột `target_market` của bảng `shared.tenant_seo_config`**, qua `_parse_json(row[
"target_market"], {})` thành dict, gán vào `SEOConfig.target_market` (dataclass field, dòng 62).
Có cache Redis 1 lớp phía trước (`config:seo:{tenant_id}`, TTL) nhưng nguồn gốc thật vẫn là cột DB
này, không phải nơi nào khác.

## Q2 — Kiểu cột thật, và dữ liệu thật đã multi-value chưa?

**Kiểu cột: `JSONB`**, xác nhận qua CHÍNH migration định nghĩa bảng (nhất quán qua cả 3 phiên bản
schema từng có trong repo — `002_schema_v2.sql:156`, `003_schema_v3.sql:169`,
`005_tenant_config.sql:33`):
```sql
target_market JSONB   -- {countries: [], age_range: [], language: "en"}
```
`countries` LÀ MỘT MẢNG ngay từ định nghĩa — không phải giá trị đơn.

**Dữ liệu thật, live-verified (đọc trực tiếp qua S3-mediated ECS exec, không suy đoán từ seed
migration)** — 3 tenant thật trong `shared.tenant_seo_config` join `shared.tenants`:
```
TENANT 'aa_internal'       countries=['AU', 'UK', 'US']  (n=3)
TENANT 'exploreasia-co'    countries=['DE', 'FR', 'NL']  (n=3)
TENANT 'wanderlux-travel'  countries=['US', 'UK', 'AU']  (n=3)
```
**Xác nhận đúng giả thuyết trong prompt: CẢ 3 tenant thật hiện có đều đã lưu sẵn 3 quốc gia,
không phải 1.** `resolve_buyer_market()` đang cắt bớt xuống còn 1 cho MỌI tenant hiện tại — không
phải dữ liệu thiếu, mà là code đang bỏ phí dữ liệu đã có sẵn.

**Phát hiện phụ, thật và có ảnh hưởng thiết kế**: `exploreasia-co` khai `['DE', 'FR', 'NL']` —
KHÔNG quốc gia nào nằm trong `DFS_LOCATION_MAP`/`MARKET_RANK` hiện tại (chỉ có US/UK/AU,
`seed_builder.py:18-25`). Với tenant này, `resolve_buyer_market()` hiện tại rơi vào nhánh
`present = []` (dòng 94) và **fallback về `US`** (`_DEFAULT_MARKET`) — một market **không hề nằm
trong danh sách tenant tự khai báo**. Đây không phải lỗi của AA-515, nhưng là một gap có thật, có
sẵn từ trước AA-515 (`DFS_LOCATION_MAP` chỉ phủ 3/nhiều market) — nên biết trước khi mở rộng sang
multi-market fan-out, vì fan-out cũng sẽ bỏ sót DE/FR/NL y hệt cho tới khi map được mở rộng.

## Q3 — Hàm mới trả về toàn bộ danh sách, không sửa `resolve_buyer_market()` cũ — xác nhận call site

**Grep toàn bộ call site thật của `resolve_buyer_market()`** (loại trừ file trong
`docs/AI-gent-for automation works/` — không phải code AA-CIS):

| File | Dòng | Cách dùng |
|---|---|---|
| `services/seo_intelligence/handler.py` | 58 | `location_code, location_name, language_code = resolve_buyer_market(cfg.target_market)` |
| `api/routers/admin_pipeline.py` | 2296 | `loc_code, loc_name, _lang = resolve_buyer_market(cfg.target_market)` |
| `api/routers/admin_pipeline.py` | 2507 | `_code, buyer_market, _lang = resolve_buyer_market(cfg.target_market)` |
| `tests/unit/test_aa197_dfs.py` | 70, 76, 81, 86 | unit test, unpack 3-tuple |

**Cả 3 call site thật đều destructure y hệt 1 tuple 3 phần tử `(location_code, location_name,
language_code)`** — đổi shape trả về (vd. sang `list[tuple]`) sẽ vỡ cả 3 ngay lập tức (unpacking
lỗi runtime, không phải lỗi kiểu tĩnh vì Python không check trước). **Xác nhận đúng đề xuất trong
prompt: cần hàm MỚI** (vd. `resolve_buyer_markets()` số nhiều, trả `list[tuple[int, str, str]]`)
**thay vì sửa `resolve_buyer_market()` hiện có** — 3 call site hiện tại (T2 seo_context handler,
2 chỗ trong admin_pipeline.py hiển thị buyer_market cho UI) đều chỉ cần ĐÚNG 1 market ưu tiên
nhất, đúng như thiết kế hiện tại của chúng — không có lý do phá vỡ chúng để phục vụ nhu cầu mới
của AA-515 (multi-market fan-out cho demand_rank).

## Q4 — DataForSEO có chấp nhận multi-location trong 1 request không?

**Không — xác nhận qua tài liệu chính thức DataForSEO (Google Ads Search Volume Live API), không
suy đoán:**
- Mỗi **task** chỉ mang đúng 1 vị trí (`location_name`/`location_code`/`location_coordinate`) —
  không được trộn nhiều vị trí trong 1 task.
- 1 task ĐƯỢC mang tới 1000 keyword, dùng chung 1 location đó.
- **Live API call chỉ chứa đúng 1 task/lần gọi** — nghĩa là **1 request = 1 location, luôn luôn**,
  đây là giới hạn thật của bản thân DataForSEO Live endpoint, không phải hạn chế riêng của code
  `dataforseo_client.py` hiện tại (dù code hiện tại cũng đang xây payload 1-task-1-location,
  khớp đúng giới hạn API — không phải chỗ code tự giới hạn thêm).
- **Giá tính theo REQUEST, không theo số keyword** ("the price for 1 or 1000 keywords will be the
  same") — xác nhận đúng con số Ms. Thư dùng ($0.09/request, `search-spend.toml`) và đúng lý do
  `CoalescingSearchDemand` gom nhiều keyword vào 1 request/market thay vì gom nhiều MARKET vào 1
  request (không thể — bị chặn ở tầng API).

**Ảnh hưởng trực tiếp tới thiết kế coalescing AA-515**: xác nhận kiến trúc đúng phải là — coalesce
theo `(market)` (nhiều Segment/keyword gộp vào 1 request/market, đúng cơ chế Ms. Thư đã có), KHÔNG
BAO GIỜ cố gộp nhiều market vào 1 request (API không cho phép). N market của 1 tenant = N request
riêng biệt, không có cách rút gọn. Chi phí multi-market fan-out cho AA-CIS = đúng N× so với
single-market hiện tại, N = số quốc gia thật tenant khai báo (3 cho cả 3 tenant thật hiện có).

## Should know

- Dữ liệu multi-market đã có sẵn, live, cho 100% tenant thật hiện tại (3/3) — không cần thu thập
  gì thêm trước khi build, chỉ cần đọc đúng field đã có.
- `DFS_LOCATION_MAP`/`MARKET_RANK` (hiện chỉ US/UK/AU) cần mở rộng nếu muốn multi-market fan-out
  phủ đúng tenant thật `exploreasia-co` (DE/FR/NL) — gap có sẵn từ trước, AA-515 sẽ làm gap này
  RÕ RÀNG hơn (hiện tại nó bị che bởi single-market fallback về US) chứ không phải AA-515 tạo ra
  gap này.
- Hàm mới, không sửa `resolve_buyer_market()` — bắt buộc theo bằng chứng call site, không phải
  tuỳ chọn phong cách.
- Multi-market fan-out = N HTTP request riêng biệt/market, xác nhận bằng tài liệu chính thức
  DataForSEO — không có cách gộp N market vào 1 request để tiết kiệm.
