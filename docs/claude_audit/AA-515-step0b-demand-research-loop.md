# AA-515 STEP0b — `_demand_ranks()`: keyword/market lựa chọn thế nào cho 1 Segment

Read-only investigation. No code changed. Bổ sung cho `docs/claude_audit/AA-515-step0-ranking-
investigation.md` (Q1/Q5) — làm rõ nguồn `search_demand` mà `_demand_ranks()` đọc trước khi thiết
kế research loop mới cho AA-CIS.

## Q1 — Ai quyết định keyword nào gắn với Segment nào, trước khi vào `search_demand`?

**Không ai quyết định trước — và đây là phát hiện quan trọng nhất của investigation này: nghiên
cứu chạy theo PLACE, không theo Segment, và việc gắn kết quả về đúng Segment xảy ra 2 LẦN, ở 2
NƠI KHÁC NHAU, bằng 2 CƠ CHẾ KHÁC NHAU** — không phải một pipeline tuyến tính đơn giản.

`src/aa_social/stages/research.py`, dòng 8-15 (docstring, trích nguyên văn):
> "One loop per **place**, not per Segment. Twenty-four Japan itineraries name Kyoto on
> twenty-two days, and Segment grouping needs a matching verb, so 'Kyoto — arrive', 'Kyoto —
> explore' and 'Kyoto — travel by train' are three Segments that would otherwise each pay for
> their own loop to rediscover the same Kyoto keywords. The loop is handed every activity at the
> place instead and spreads its keywords across them."

Cụ thể: `PROMPT` template (`research.py:151-160`) truyền `place` (1 chuỗi) + `actions` (TOÀN BỘ
hoạt động tại nơi đó, gộp) vào MỘT lần gọi LLM ReAct — không phải 1 lần gọi/Segment.

**Bước 2 — gắn kết quả về Segment xảy ra ở NƠI THỨ HAI, bằng CƠ CHẾ THỨ HAI, độc lập với bước 1**:
`score.py::_demand()` (dòng 703-750) — đọc **thẳng từ toàn bộ bảng `search_demand`** (mọi keyword
từng mua, của mọi place, mọi Segment), so khớp lại bằng **word-overlap thuần** giữa từ trong
keyword và `_claimable(place, action)` của Segment đang chấm điểm — **không dùng** kết quả
embedding-match (`atom_matches`) cho việc này. Trích nguyên văn lý do (dòng 711-715):
> "Read from everything the research loop bought rather than from what the matcher paired,
> because the matcher under-reaches as badly as it over-reaches: `nakasendo trail` at 6,600 was
> bought and landed on exactly one Atom, while thirteen Magome and Tsumago Segments took `magome
> to tsumago` at 210. Going by name instead lifts the Segments carrying any demand at all from
> 14% to 45%."

Tức: **có một cơ chế embedding-match riêng (`matching.py::match_queries_to_atoms()`), nhưng
`_demand_ranks()`/`_demand()` — thứ AA-515 cần port — cố ý KHÔNG dùng nó**, vì tự đo được nó bỏ
sót quá nhiều (14% → 45% khi đổi cách). Embedding-match phục vụ mục đích khác (gắn PAA
questions/`atom_matches` cho `_questions()`, không phải cho demand). **Kết luận: research loop
(bước 1) không hề gán keyword→Segment; việc gán chỉ xảy ra khi CHẤM ĐIỂM (bước 2), bằng so khớp
từ, tái tính mỗi lần `score` chạy — không lưu một mapping cố định nào giữa keyword và Segment.**

## Q2 — Research stage chọn keyword thế nào: LLM tự sinh, hay place/action nguyên văn?

**LLM tự chọn qua ReAct loop có công cụ thật, không phải sinh tự do và không phải lấy nguyên văn
place/action.** `SYSTEM` prompt (`research.py:118-149`) — model tự quyết mỗi lượt: nói ra kết
luận từ dữ liệu đã thấy, rồi chọn 1 trong 4 công cụ:
- `volumes` — tra khối lượng tìm kiếm cho các keyword tự chọn. Luôn bắt đầu bằng chính tên place
  (chưa qualify), rồi mới thêm hoạt động nếu place có volume.
- `serp` — trang kết quả đầu + People Also Ask, "expensive call", chỉ dùng cho keyword ĐÃ có
  volume đo được, tối đa 2 keyword/place (`MAX_SERPS = 2`).
- `suggestions` — keyword liên quan do search engine gợi ý, chỉ dùng khi mọi phrasing tự nghĩ ra
  đều volume=0, tối đa 1 lần/place (`MAX_SUGGESTIONS = 1`).
- `done` — dừng.

Ràng buộc rõ trong prompt: "Keywords are what a traveller types, not what a brochure says.
'nakasendo trail' and 'magome to tsumago hike', never 'unforgettable cedar forest journey'" — LLM
được huấn luyện để tránh vừa lấy nguyên văn place/action thô, vừa tránh ngôn ngữ marketing. Giới
hạn cứng: `MAX_STEPS = 4` lượt/place, `MAX_KEYWORDS = 8` keyword/place (hằng số module-level,
`research.py:81-82`). **Quan hệ place→keyword là 1-nhiều (tối đa 8), do LLM chọn động, không phải
1-1 cố định.**

## Q3 — "market" nghĩa là gì, đối chiếu khái niệm gần nhất ở AA-CIS

**Ms. Thư: market = mã quốc gia 2 ký tự (US/UK/AU), lấy từ Brand Audience, KHÔNG phải ngôn ngữ
hay vùng miền.** `brand.py`:
```python
MARKET_CODES = {"united states": "US", "usa": "US", "us": "US",
                 "united kingdom": "UK", "uk": "UK", "great britain": "UK",
                 "australia": "AU", "au": "AU"}
```
khớp đúng CONTEXT.md's Brand Audience ("United States, United Kingdom and Australia"). Và
research.py dòng 24-26 (docstring): *"The loop chooses keywords. It never chooses markets: every
keyword it asks for is looked up in **every market the brand sells to**"* — tức **fan-out**: 1
keyword × N market brand-level cố định, không phải LLM tự chọn market.

**AA-CIS hiện tại — khác về chất, không phải cùng khái niệm đổi tên:**
`services/seo_intelligence/seed_builder.py::resolve_buyer_market()` (dòng 84-97) — nhận
`target_market.countries` (danh sách quốc gia của TENANT, không phải brand cố định 3 nước), rồi
**CHỈ CHỌN 1 quốc gia ưu tiên cao nhất** (`min(present, key=lambda c: MARKET_RANK[c])`), trả về
đúng 1 `(location_code, location_name, language_code)` — **không fan-out**. `dataforseo_client.py`
gọi DataForSEO với đúng 1 `location_code`/lần (mặc định `2840` = United States,
`DEFAULT_LOCATION_CODE`). **Kết luận: AA-CIS hiện KHÔNG có khái niệm "1 keyword tra ở nhiều
market cùng lúc" — mỗi lần research chỉ nhắm 1 market/tenant, đã chọn sẵn theo ưu tiên.** Port
đúng thiết kế Ms. Thư (fan-out mọi market) đòi hỏi thay đổi thật ở tầng gọi DFS, không chỉ thêm
bảng — cần quyết định: giữ single-market hiện tại (đơn giản hơn, khớp kiến trúc per-tenant hiện
có) hay chuyển sang multi-market fan-out (khớp thiết kế gốc, tốn hơn N lần request cho N market
của tenant).

## Q4 — Chi phí thật, cache/dedupe

**Ước tính từ chính config đã tune của Ms. Thư** (`reference/search-spend.toml`, giá thật
DataForSEO, "checked 2026-08-28"):
- `volumes`: $0.09/request — **1 request chở tới 1000 keyword** (không tính theo đầu keyword) —
  đây là lý do các loop chạy song song được GOM chung 1 request/market
  (`CoalescingSearchDemand`, `research.py:252-...`, coalesce theo market, đợi tối đa
  `LINGER_SECONDS=5.0` hoặc tới khi đủ loop "park" xong).
- `serp`: $0.002/request (1 keyword/request, không gom).
- `suggestions`: $0.0144/request (1 keyword/request, không gom).
- **Ngân sách/place đã đo**: ~$0.068 volume + $0.012 serp + $0.014 suggestions ≈ **$0.10, làm tròn
  lên $0.12/place** để có margin. Đo thật trên export Nhật: 24 trip → 581 place riêng biệt, 495/581
  chỉ xuất hiện đúng 1 ngày — "mỗi trip thêm ~24 place mới, không có dấu hiệu chững lại."
- Throttle riêng: 12 volume request/phút (giới hạn tài khoản, `_Throttle`), 16 worker chạy song
  song để tối đa hoá số loop gộp chung 1 request (đo: 8 worker tốn 1.6 request/place, 16 worker
  tốn 1.1 request/place).

**Có cache thật, theo place (không phải theo Segment)**: dòng 107-116 (docstring) —
`FRESH_FOR = timedelta(days=182)` — "What was bought recently is read from the workspace rather
than bought again... A run that needs today's page has `retrieved_on` in `serp_harvests` to
clear." 6 tháng, đo trên chu kỳ thực tế nhu cầu du lịch thay đổi, không phải số tuỳ chọn.

**Dedupe giữa các Segment cùng địa điểm: CÓ, và đây chính là cơ chế Q1 đã mô tả** — "One loop per
place, not per Segment" nghĩa là 2 Segment khác nhau (vd. "Kyoto — arrive" và "Kyoto — explore")
**không bao giờ trigger 2 lần research riêng** — chúng cùng nằm trong `actions` list của 1 lần gọi
LLM duy nhất cho place "Kyoto". Việc phân bổ kết quả về đúng Segment xảy ra SAU, ở tầng chấm điểm
(`_demand()`, xem Q1) — không tốn thêm request nào.

**Suy ra cho AA-CIS (không tự quyết ở đây)**: port đúng "1 loop/place" cần một bước GOM Segment
theo `canonical_place` (đã có sẵn ở `atom_segment.canonical_place`, AA-509) trước khi research —
tức nhóm nhiều `atom_segment` row cùng `canonical_place`/tenant thành 1 lần research, không phải
research per-segment_id. Đây là điều kiện thiết kế quan trọng cho build prompt, không phải chi
tiết vặt.

## Should know

- 2 khái niệm dễ nhầm cần tách bạch khi viết build prompt: (a) **place-level research loop**
  (mua keyword, cache 6 tháng, dedupe tự nhiên qua gom actions) và (b) **Segment-level demand
  attribution** (`_demand()`, chạy lại mỗi lần `score`, word-overlap thuần, KHÔNG dùng embedding-
  match). Port thiếu 1 trong 2 sẽ không tái tạo đúng hành vi gốc.
- AA-CIS hiện chỉ query DataForSEO theo **1 market/tenant đã chọn sẵn**, không fan-out — cần
  quyết định rõ trước khi build: giữ single-market hay đổi sang multi-market fan-out (ảnh hưởng
  trực tiếp chi phí × N market).
- `_demand()`'s word-overlap thay vì embedding-match là quyết định có chủ đích, có số đo thật
  (14%→45%) — không nên "cải tiến" sang embedding-match khi port, trừ khi có lý do mới.
