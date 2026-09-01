# AA-510 STEP0 — Route/Hub schema + phát hiện hành trình

Read-only investigation. No code changed. Epic: AA-507 (T5-T11 redesign theo repo
aa-social-media của Ms. Thư). Sub-issue, trả lời AA-504 (Blog multi-atom/pillar). Builds on
AA-508 (atom identity) + AA-509 (Segment, vừa Done) — both already live.

## Q1 — route.tour_id: join thẳng raw_tours (Master Content) hay qua tenant_tour_versions?

**Kết luận: join thẳng `silver_aa_internal.raw_tours(tour_id)` — đúng như mô tả gốc. KHÔNG qua
`tenant_tour_versions`.** Đây không phải giả định — code hiện tại đã tự trả lời câu này, bằng
chữ, cho chính lớp atom mà Route sẽ đọc:

`services/acp_produce/tenant_pipeline.py:266-269`, docstring của `run_t5_atomize()`:
> `tour_id` here MUST be `silver_aa_internal.raw_tours.tour_id` (`acp_contract.tour_atoms.tour_id`'s
> FK target) — the caller passes `published_tours.tour_id` (from `trigger_rewrite()`), not
> `tenant_tour_versions.id` or `published_tours.id`.

Và schema thật (`api/migrations/079_acp_contract_tour_atoms.sql:26`):
```sql
tour_id  UUID NOT NULL REFERENCES silver_aa_internal.raw_tours(tour_id),
owner_scope  TEXT NOT NULL DEFAULT 'platform',   -- tenant_id::text cho atom T5 của tenant
```

Tức là **atom (và do đó Segment, và do đó Route) không hề mang khái niệm "version"** — chúng gắn
vào `(raw_tours.tour_id, owner_scope)`, không phải vào một `tenant_tour_versions.id` cụ thể. Có
một bảng fingerprint riêng, `acp_contract.atomize_day_fingerprint`, khoá theo
`tenant_tour_version_id` (migration 128) — nhưng đó chỉ là cơ chế skip/re-atomize theo ngày, atom
thật sự (`tour_atoms`) vẫn UPSERT vào đúng row cũ theo `(owner_scope, tour_id, day, place, action)`
content-hash (AA-508/509). Nếu một tenant rewrite lại cùng một tour lần thứ 2
(`tenant_tour_versions.version_number` tăng), atom hoá lại sẽ UPSERT đè lên atom cũ của
`(tenant, tour_id)` đó, không tạo bản atom riêng cho version 2 — Route thừa hưởng đúng giới hạn
này (xem "Should know" bên dưới).

Route đại diện cho hành trình của **tour tenant sở hữu thật** (owner_scope = tenant), KHÔNG phải
Master Content trung lập — chỉ là identity cột `tour_id` của nó trỏ vào `raw_tours` (cùng PK với
bản gốc), giống hệt cách `tour_atoms.tour_id` đã làm. Phân biệt tenant nằm ở cột riêng
(`tenant_id`/`owner_scope`), không nằm ở `tour_id` — xem Q4.

**Gap có thật, chưa từng được ghi nhận ở đâu khác trong repo mà tôi tìm thấy**:
`gold_aa_internal.tenant_tour_versions` (bảng T2 rewrite thật đang dùng sống — `v1_tours.py`,
migrations 107/108/109 đều `ALTER`/query nó) **không có `CREATE TABLE` trong bất kỳ file migration
nào** (`003_schema_v3.sql` chỉ `CREATE SCHEMA gold_aa_internal`, không tạo bảng này; bảng
`gold.tenant_tour_versions` trong `001_initial_schema.sql` là schema `gold` — khác, đã bị
`DROP TABLE tenant_tour_versions CASCADE` ở `002`/`003`). Bảng sống chắc chắn được tạo tay ngoài
migration tracking — cùng loại tech debt với `AA-Bedrock-Invoker` (đã ghi trong CLAUDE.md). Không
chặn AA-510 (Route không cần bảng này), nhưng đáng một dòng riêng nếu có phiên dọn migration.

## Q2 — CONTEXT.md Route/Hub + channels.toml takes_route: cơ chế thật

**CONTEXT.md** (dòng 69-85, definitions thật, không phải diễn giải):

- **Route**: "An ordered run of Segments a trip walks through — Kyoto, Magome, Tsumago, Matsumoto.
  Routes that tell the same journey by different names collect into a **family**."
- **Hub**: "The journey a marketer chooses, named as a traveller would say it: 'Nakasendo Way: The
  Kiso Valley from Kyoto'. A Hub is the unit of choice and the Segments inside it are the material
  for that piece, not pieces of their own." `most_per_hub` (per-Channel cap, hiện tắt = 99 mọi
  Channel) là cơ chế duy nhất Hub tham gia vào — không có bảng `hubs` riêng trong repo tham chiếu
  (xem dưới).

**`reference/channels.toml`**: chỉ đúng 1 Channel có `takes_route = true` — `[Blog]` (dòng 19),
kèm comment giải thích tại sao (dòng 15-18): "A Blog piece has room for a journey... Every other
Channel takes one moment." Không có field `takes_route` nào khác trong 7 Channel còn lại (LinkedIn
đã đọc tới dòng 70, không có route). Xác nhận đúng brief AA-510: chỉ Blog dùng Route, 7 channel
còn lại đi thẳng Segment → Slate.

**Cơ chế dựng `ordered_segment_ids` thật** — không phải suy luận, đọc thẳng
`src/aa_social/stages/score.py:288-319` (`_routes()`, gọi từ stage `score`, sau khi ranking chạy
xong):

```python
moments = [Moment(atom_id=row["atom_id"], trip_code=row["trip_code"], day=row["day"],
                   place=row["place"], score=row["score"]) for row in
           db.execute("SELECT s.atom_id, a.trip_code, a.day, a.place, s.score"
                       " FROM atom_scores s JOIN atoms a USING (atom_id)")]
ranked: dict[str, set[str]] = {}
for row in db.execute("SELECT DISTINCT a.trip_code, m.segment_id FROM segment_members m"
                       " JOIN atoms a USING (atom_id) JOIN atom_scores s ON s.atom_id = a.atom_id"):
    ranked.setdefault(row["trip_code"], set()).add(row["segment_id"])
named = families(ranked)
return [replace(route, family=named.get(route.trip_code)) for route in derive_routes(moments)]
```

Tức thứ tự Segment trong một Route **không phải một thuật toán sắp xếp riêng** — nó chính là thứ
tự ngày (`day`) của các Atom đã được rank, theo `_runs()`/`_spans()` trong `routes.py` (xem Q3).
**Input là atom đã qua `score` (ranking theo search-demand)**, không phải mọi atom thô. AA-CIS
**chưa có khái niệm "atom_score"/ranking tương đương** — tìm không thấy bảng
`acp_contract.*score*` nào, `distinctiveness` (AA-445-02) là một trục khác (độ khác biệt so với
đối thủ, không phải nhu cầu tìm kiếm). Đây là câu hỏi thiết kế thật cần chốt trước khi build: Route
AA-CIS lấy atom nào làm input — mọi atom chưa xoá của tenant/tour, hay chờ một stage ranking tương
lai? Không tự quyết ở STEP0 này.

## Q3 — code dựng Route thật, port gần nguyên văn được không

**Có — `src/aa_social/routes.py` là pure function, không đụng DB, port gần như nguyên văn được**
(đã đọc toàn bộ file, 249 dòng). Ba cơ chế chính:

1. **`derive_routes(moments)`** — nhóm theo `trip_code`, cắt thành các "run" ngày liên tục
   (`_runs()`: gap = ngày ranking để trống, thường là ngày transfer), rồi cắt "run" dài thành các
   "span" ≤ `MOST_DAYS=5` ngày (`_spans()`), lọc bỏ span có `< LEAST_DAYS=2` ngày hoặc
   `< LEAST_PLACES=2` địa điểm khác nhau. `route_id = f"{trip_code}:{first_day}-{last_day}"` —
   deterministic theo trip + khoảng ngày, không phải content-hash.
2. **`families(trips, share=SHARED_ENOUGH=0.3)`** — union-find trên tỷ lệ Jaccard-kiểu:
   `|A ∩ B| / min(|A|, |B|) >= 0.3` trên tập `segment_id` mỗi trip đã rank được; family đặt tên
   theo trip_code nhỏ nhất (alphabet) trong nhóm — "một tour ingest lại giữ nguyên family cũ, chỉ
   thành viên mới sắp trước mọi thành viên cũ mới đổi tên".
3. **`stops()`** — presentation layer: gộp 2 Atom cùng `(day, place)` khác `action` thành 1 `Stop`
   nhiều `actions` (vd. "Itsukushima Shrine — visit, see the torii at high tide"), tránh Route bị
   "stammer" khi in ra.

**Điểm KHÔNG thể port thẳng — khác biệt kiến trúc buộc phải thích nghi**:

- `trip_code` trong repo tham chiếu = một lần ingest itinerary, **1 file SQLite = 1 brand**, không
  có khái niệm nhiều tenant. Trong AA-CIS, `trip_code` phải map thành **cặp `(tenant_id, tour_id)`
  composite**, không phải `tour_id` một mình — vì nhiều tenant khác nhau có thể cùng rewrite một
  `raw_tours.tour_id` gốc (Nakasendo tour X), mỗi tenant tạo Route riêng dưới `owner_scope` riêng.
  Dùng `tour_id` một mình làm khoá nhóm sẽ trộn Atom của tenant A và tenant B vào cùng một "trip".
- `families()` chạy trên `trips: Mapping[str, set[str]]` không lọc tenant — nhưng **an toàn tự
  nhiên**: vì `atom_segment.segment_id` đã fold `tenant_id` vào hash (AA-509, `_mint()`), hai
  tenant không bao giờ có `segment_id` trùng nhau, nên `families()` chạy toàn cục (không lọc
  tenant) vẫn không bao giờ merge Route của 2 tenant khác nhau — Jaccard giữa 2 tập segment_id
  không giao nhau luôn = 0. Vẫn nên scope theo tenant ở tầng query (đúng pattern
  `run_segment_matching(tenant_id)` đã có) để tránh so sánh toàn bộ platform mỗi lần chạy, không
  phải vì đúng/sai mà vì hiệu năng — không phải blocker.
- **`atom_scores`/`atom_score` KHÔNG tồn tại trong AA-CIS** (xem Q2) — `derive_routes()` port
  nguyên văn cần input `Moment.score`; nếu chưa có ranking stage, build prompt cần quyết định giá
  trị `score` giả định gì (vd. `1` cho mọi atom, hoặc dùng `distinctiveness` làm proxy tạm) — đây
  là quyết định thiết kế, không tự chốt ở đây.
- **`itinerary_day` (Atom.day) chỉ có giá trị từ migration 093 trở đi, `place`/`action` chỉ có
  giá trị từ migration 129 trở đi — cả hai đều "no backfill" theo đúng tiền lệ đã dùng** (migration
  093/129 comment). Route cần CẢ HAI mới dựng được — atom atomize trước cả 2 migration này (nếu
  còn tồn tại, không re-atomize) sẽ có `place`/`action`/`itinerary_day` NULL và tự động bị loại
  khỏi Route (không phải bug, chỉ là dữ liệu chưa refresh).

**Bảng schema thật trong repo tham chiếu** (`src/aa_social/workspace.py:318-335`, SQLite) —
tương ứng 1:1 với thiết kế Postgres cần cho AA-510:
```sql
CREATE TABLE routes (route_id TEXT PRIMARY KEY, trip_code TEXT NOT NULL,
    first_day INTEGER NOT NULL, last_day INTEGER NOT NULL, score INTEGER NOT NULL, family TEXT);
CREATE TABLE route_members (route_id TEXT REFERENCES routes(route_id) ON DELETE CASCADE,
    atom_id TEXT REFERENCES atoms(atom_id) ON DELETE CASCADE, position INTEGER NOT NULL,
    PRIMARY KEY (route_id, atom_id));
```

**Phát hiện quan trọng nhất của mục này — cơ chế PERSIST khác hẳn `atom_segment`**:
`_store_routes()` (`score.py:322-341`) — *"Rebuilt whole, like the ranking: a Route is derived,
never accumulated"* — `DELETE FROM route_members; DELETE FROM routes;` rồi INSERT lại toàn bộ mỗi
lần `score` chạy. **Route/route_members KHÔNG dùng pattern append-only + alias như
`atom_segment`/`atom_segment_alias`** (AA-509) — đây là 2 tầng khác nhau, xử lý churn khác nhau, cả
hai đều có evidence rõ ràng (xem Q5).

## Q4 — kiểu dữ liệu JOIN: route.tenant_id (UUID) vs owner_scope (TEXT)

Xác nhận pattern thật, đã dùng ở AA-509 (`services/acp_contract/segment_matching.py:387,394-395`):
```python
"SELECT ... FROM acp_contract.tour_atoms WHERE owner_scope = $1 AND NOT deleted ..."  # $1 = tenant_id (str)
"SELECT ... FROM acp_contract.atom_segment WHERE asg.tenant_id = $1::uuid"            # cast
```
`tour_atoms.owner_scope` là **TEXT** (chứa `tenant_id::text` hoặc `'platform'`); `atom_segment.tenant_id`
là **UUID** thật (FK `shared.tenants(tenant_id)`). Route cần theo đúng pattern `atom_segment` đã
lập — **`route.tenant_id UUID NOT NULL REFERENCES shared.tenants(tenant_id)`**, không phải TEXT —
vì Route join xuống `atom_segment`/`atom_segment_member` (đã UUID), không join trực tiếp xuống
`tour_atoms.owner_scope` nữa. Chuỗi JOIN thật Route cần:
```
route_members.atom_id → atom_segment_member.atom_id (lấy segment_id)
                       → atom_segment.segment_id (đã lọc theo tenant_id UUID)
                       → tour_atoms.atom_id (lấy day/place/action/tour_id thật để dựng Moment)
```
Không cần re-filter `owner_scope` một lần nữa ở tầng `tour_atoms` — đã lọc đúng tenant từ tầng
`atom_segment` rồi (segment_id không giao nhau giữa 2 tenant, xem Q3). `route.tour_id` giữ UUID
(khớp `raw_tours.tour_id`), tách biệt hoàn toàn với `route.tenant_id` — đúng 2 cột riêng, không
gộp.

## Q5 — family_id: cơ chế merge có thật trong repo, hay tự thiết kế?

**Có thuật toán cụ thể, đã đọc toàn bộ — không cần tự thiết kế phần lõi.** `families()`
(`routes.py:153-190`, xem Q3) — union-find trên độ trùng Segment ≥ `SHARED_ENOUGH=0.3` (tỷ lệ trên
tập NHỎ HƠN trong 2 trip, không phải tập lớn hơn — chọn có chủ đích, comment dòng 47-53 giải thích:
ở 0.3 tách đúng 4 trip Hokkaido + 2 trip Nakasendo trên bộ dữ liệu Nhật thật, thấp hơn sẽ kéo cả
`shoguns-and-samurai-imperial-kyoto-and-nara` vào vì share Kyoto). Ngưỡng `0.3` là **hằng số đo
trên bộ dữ liệu Nhật thật của Ms. Thư**, không phải suy ra từ lý thuyết — build prompt cần cân
nhắc có giữ nguyên `0.3` hay phải đo lại trên dữ liệu tour AA-CIS thật (khác brand, khác itinerary
shape) — không tự chốt ở STEP0.

`family` là **TEXT** (tên = trip_code nhỏ nhất trong nhóm, không phải UUID/hash riêng) — không có
"family_id" độc lập trong repo tham chiếu, chỉ là 1 cột `family` trên chính bảng `routes`. Nếu
AA-CIS muốn 1 bảng `route_family` riêng (tách khỏi cột trên `routes`) thì đó là mở rộng thêm, không
phải port nguyên văn.

**`families()` chạy TRÊN dữ liệu ĐÃ RANK** (`ranked: dict[trip_code, set[segment_id]]` chỉ lấy
segment của atom đã qua `atom_scores`, không phải mọi Segment thô) — cùng câu hỏi mở ở Q2/Q3 (AA-CIS
chưa có ranking stage): nếu Route AA-CIS phải dùng TOÀN BỘ Segment (chưa rank) làm input cho
`families()`, ngưỡng `0.3` có thể cho kết quả khác hẳn — càng cần đo lại trên dữ liệu thật trước
khi build, không đoán.

## Should know — tổng hợp cho vòng chốt thiết kế

1. **Route/route_members nên rebuild-whole (DELETE+INSERT) mỗi lần T5/Segment chạy xong cho một
   tenant** — theo đúng pattern đã có bằng chứng (`_store_routes()`), KHÁC với `atom_segment`
   (append-only + alias). Lý do 2 tầng khác nhau xử lý churn khác nhau nằm ở **ADR 0024**
   (`docs/adr/0024-a-subject-outlives-the-segment-it-came-from.md`, đọc toàn văn): repo tham chiếu
   từng thử giữ Subject (= tương đương "Subject/Hub" tầng chọn lựa của AA-CIS) sống nhờ FK vào
   Segment/Route rồi phát hiện **CASCADE xoá mất quyết định của con người** khi ranking đổi (run
   2026-08-29 thật: chạy lại đúng 206 ngày, đúng prompt, đúng model — 383/931 atom_id sống sót,
   208 Segment mất, 222 Segment mới) — sửa bằng cách làm **Subject SNAPSHOT nội dung Route** (place/
   action/day tại thời điểm chọn, bảng `subject_route`) thay vì FK sống vào `route_id`, comment
   dòng 292-294 nói thẳng: *"the Route is rebuilt from whatever `score` last ranked, and a Subject
   somebody picked has to still know the journey it was picked for"*. **Kết luận trực tiếp cho
   AA-510**: bất kỳ bảng downstream nào (Hub/Subject/AA-511 sau này) "chọn" một Route đều PHẢI
   snapshot nội dung, không được FK cứng vào `route_id` rồi kỳ vọng nó ổn định qua lần chạy sau —
   đây là rủi ro thiết kế thật, không phải lý thuyết, đã có số liệu chứng minh trong chính repo
   nguồn.
2. **AA-CIS chưa có "score"/ranking stage** (nhu cầu tìm kiếm, DataForSEO) — cả `derive_routes()`
   lẫn `families()` trong repo gốc đều lấy input từ atom ĐÃ RANK, không phải atom thô. Đây là câu
   hỏi mở thật sự cần chốt trước build, không phải thiếu sót của STEP0 này.
3. **`SHARED_ENOUGH=0.3` là hằng số đo trên dữ liệu Nhật thật của Ms. Thư** — nên coi là điểm khởi
   đầu, không phải giá trị đúng sẵn cho catalog AA-CIS.
4. **Câu hỏi STEP0 chỉ hỏi về Route + family — không có câu nào về Hub** dù tiêu đề issue nhắc
   "Route/Hub schema". Theo CONTEXT.md, Hub là "unit of choice" (tầng con người chọn, gần với
   Subject/AA-511 hơn) — không có bảng `hubs` riêng trong repo tham chiếu, chỉ là 1 field
   `most_per_hub` trong `channels.toml` dùng để cap số Subject mỗi Hub. Đề xuất: AA-510 tự nó chỉ
   nên dựng `route`/`route_family` (thuần derive, đọc-only từ Segment); Hub/Subject (tầng con
   người chọn + cần snapshot theo ADR 0024) nên là issue riêng kế tiếp — khớp cách AA-508/509 đã
   tách nhau theo lớp.
5. **Gap migration `gold_aa_internal.tenant_tour_versions` không có `CREATE TABLE`** — xem Q1,
   không chặn AA-510, ghi nhận riêng.
6. **`route.tour_id` KHÔNG cần bảng `tenant_tour_versions`** — dùng thẳng `raw_tours.tour_id`,
   thêm cột `tenant_id UUID` riêng để phân biệt tenant, đúng pattern `atom_segment` đã lập
   (Q1 + Q4).
