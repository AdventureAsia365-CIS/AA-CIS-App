# AA-345 — STEP 0 Investigation (KHÔNG CODE, KHÔNG SỬA GÌ)

Ngày: 2026-08-12. Repo xác nhận: `AA-CIS-App` (origin =
`AdventureAsia365-CIS/AA-CIS-App`, đúng repo live, không phải AA-ACP-App đã
abandoned). Không có file/schema nào bị sửa trong session này — chỉ đọc code
(`git log`/`git show`), đọc Linear (AA-345, AA-386, AA-300), và query DB
read-only qua db-auditor (S3-mediated ECS exec, `SELECT`/`information_schema`
only, không `UPDATE`/`INSERT`/`DELETE`).

**File này KHÔNG được commit** — chờ Nghiep/Claude Chat review.

---

## PHẦN 1 — 50 tour publish hiện trên /admin/s1-rewrite: chủ ý hay bug?

### Bằng chứng đã tìm

**1. Vị trí thật của endpoint đã lệch so với issue.** Issue AA-345 ghi
`admin_pipeline.py:1594-1613`. Đọc file thật hôm nay: `GET /admin/tours`
(`get_all_tours`) nằm ở **`api/routers/admin_pipeline.py:1625-1662`**, không
có mệnh đề `WHERE` nào — xác nhận đúng phần lỗ hổng issue mô tả, chỉ lệch số
dòng (file đã có commit khác chen vào giữa từ lúc issue được viết 29/07 đến
nay 12/08).

**2. Commit gốc tạo endpoint: `1da2ce9` (AA-104, 25/05/2026), không qua PR**
(`gh pr list --search` không ra kết quả — commit này có trước thời điểm PR
bắt buộc). Message gốc ghi rõ:

> `Frontend S1: fetch all tours (not just ingested), status badges per pipeline_status + rewrite_count`

Đây là bằng chứng **có chủ ý ở mức rộng**: quyết định ban đầu là mở rộng từ
"chỉ tour đã ingest" sang "toàn bộ tour" để hiện badge theo `pipeline_status`
và cho phép xem/chạy lại. Nhưng message **không nhắc riêng đến tour đã
publish** — chủ ý ở đây là "hiện tất cả trạng thái", không phải một quyết
định tách riêng "cho phép re-run sau publish".

**3. Không tìm thấy PRD local nào nói rõ hơn.** `grep -rl "re-run\|rerun"
docs/` không ra tài liệu PRD nào bàn về việc re-run S1 sau publish — chỉ ra
các file implementation-notes khác không liên quan. Không có bản PRD nào
trong repo (Notion PRD ngoài tầm truy cập của session này).

**4. Issue AA-345 tự nó đã ghi nhận đây là điểm chưa chốt**, không phải giả
định của investigation này:

> "Hiện 50 tour đã publish. Chuyện này **có thể là chủ ý** (cho phép chạy lại
> S1) — **cần Nghiep xác nhận, không tự sửa**."

**5. Bằng chứng DB thật (query trực tiếp `gold_aa_internal.published_tours`
JOIN `silver_aa_internal.generated_content`):**

- Chỉ **3 dòng / 2 tour_id** có `generated_content.created_at` SAU
  `published_tours.published_at` — tức chỉ 2 trên 63 tour đã publish thật sự
  có bằng chứng "chạy S1 lại sau khi publish". Cả 3 lần đều cách publish
  **dưới 41 phút** (1 lần lúc 0:01:10, 2 lần lúc 0:04:20 và 0:40:46) — giống
  thao tác sửa nhanh/retry ngay sau khi publish hơn là một luồng làm việc
  chủ đích, lặp lại theo thời gian.
- **37 trên 63 tour đã publish chỉ có đúng 1 dòng `generated_content` duy
  nhất, không bao giờ bị chạy lại.**
- 26 tour đã publish có >1 dòng `generated_content` (tính mọi thời điểm, kể
  cả các bản nháp trước lúc publish) — nhưng đây không phải bằng chứng
  re-run **sau** publish, chỉ là multi-version soạn thảo trước đó.

### Kết luận Phần 1

**Chưa đủ bằng chứng để khẳng định "cho tour publish vẫn hiện trên S1
Rewrite để re-run" là một tính năng chủ ý, đang được dùng thật.** Bằng chứng
nghiêng nhẹ về hướng: đây là hệ quả phụ của quyết định AA-104 ("hiện tất cả
tour, không lọc theo status"), chứ không phải một quyết định riêng cho
trường hợp publish. Việc dùng thật cực kỳ hiếm (2/63 tour, gap <41 phút,
giống fix nhanh chứ không phải re-run có chủ đích lặp lại). Đúng như issue đã
tự ghi — **cần Nghiep xác nhận trực tiếp**, investigation này không tự kết
luận thay.

---

## PHẦN 2 — Ngưỡng chất lượng nguồn để atom hoá

### Phát hiện quan trọng: con số "26 tour có atom" trong issue có vẻ SAI

Issue AA-345 ghi "235 atom / 26 tour". Query thật vào `acp_contract.tour_atoms`
hôm nay (12/08) cho kết quả khác hẳn:

- **115 tour riêng biệt** có atom (không phải 26) — ổn định dưới mọi cách lọc
  (có/không loại `deleted=true`, theo `owner_scope`, theo `is_empty_marker`
  — luôn ra 115).
- **2279 dòng atom tổng** (2201 dòng `deleted=false` + 78 dòng `deleted=true`
  trên 7 tour có cả hai loại), không phải 235.
- Con số "26" trùng khớp chính xác với `published_tours_with_multiple_gc_rows`
  ở Phần 1 (mục 5) — **nghi ngờ hợp lý: issue đã nhầm hai con số không liên
  quan với nhau** (số tour publish có ≥2 lần rewrite S1, với số tour có
  atom). Con số "235" khớp với snapshot cũ trong ghi chú AA-300 (session
  22-23/07: "235 atoms, 0 HIGH/0 MED/235 LOW") — atom hoá đã tăng thêm đáng
  kể (235 → 2279, ~26 → 115 tour) từ lúc đó đến nay qua các job chạy tay
  khác, ghi chú AA-345 chưa cập nhật theo state mới nhất.

→ **Khoảng cách thật là 763 − 115 = 648 tour chưa atom hoá**, không phải 737
như issue tính (763 − 26).

### Phân bố `length(itinerary_source)` — toàn bộ 763 tour (`v_trip_registry`)

```
n = 763        min = 80        p10 = 760
p25 = 1,482    p50 = 2,785     p75 = 6,027
p90 = 9,706    max = 27,409
```

(Lưu ý: view `v_trip_registry` đặt tên cột là `itinerary_source`, KHÔNG phải
`src_itineraries` — cột đó chỉ tồn tại đúng tên trên bảng gốc
`silver_aa_internal.raw_tours`. Query đầu tiên viết theo tên trong issue đã
fail `UndefinedColumnError`, phải sửa lại.)

### 115 tour đã atom hoá nằm ở đâu trong phân bố đó

```
< p10   : 13 tour        p10–p25 :  2 tour       p25–p50 : 18 tour
p50–p75 : 35 tour         p75–p90 : 23 tour       ≥ p90   : 24 tour
```

Percentile trải từ **0.13th đến 100th** (median 62.1st) — tập 115 tour KHÔNG
tập trung ở một cực nào. Nó lệch nhẹ về nửa dài hơn (58/115 ≥ median 2,785
ký tự) nhưng vẫn bao gồm cả tour ngắn nhất (80 ký tự → 3 atom) lẫn tour dài
nhất (27,409 ký tự → 23 atom) của toàn bộ 763 tour.

### Tín hiệu chất lượng atom kém (Phần 2.3)

Kiểm tra `length(trim(text)) < 20` trên toàn bộ 2279 dòng atom: **0 dòng**
nào rỗng/quá ngắn, ở bất kỳ tour nào trong 115 tour. **Không tìm được tương
quan giữa độ dài nguồn và tín hiệu chất lượng atom kém** — kết quả âm tính
thật, không phải thiếu dữ liệu.

### Kết luận Phần 2 — KHÔNG chốt được 1 con số threshold đáng tin

Theo đúng yêu cầu "không bịa số nếu dữ liệu không đủ", investigation này
**không đề xuất một ngưỡng ký tự/số ngày cụ thể**, vì ba lý do có bằng chứng:

1. **115 tour này là mẫu chạy tay, không phải mẫu ngẫu nhiên** — ai chạy job
   đó có thể đã chọn tour có sẵn (theo lô ingest, theo yêu cầu cụ thể), không
   đại diện cho việc atom hoá tự động không chọn lọc trên phần còn lại của
   763 tour. Phân bố percentile ở trên mô tả "tour nào đã được chọn", không
   chứng minh "tour ngắn thì atom sẽ tệ".
2. **Không có tín hiệu chất lượng nào tương quan với độ dài** (Phần 2.3) —
   nếu độ dài không dự đoán được chất lượng atom (theo thước đo duy nhất
   kiểm tra được: độ dài text), thì một ngưỡng thuần theo ký tự thiếu cơ sở.
3. **Số ngày detect được trong itinerary chưa được đo** — mẫu `src_itineraries`
   xác nhận đây là text tự do dạng `"Day 1 : ..."`, `"Day 2 : ..."`, không có
   cấu trúc field ngày rõ ràng. Đếm số ngày cần regex `Day \d+` trên toàn bộ
   763 tour — **chưa chạy trong investigation này**, cần một bước riêng
   trước khi chốt threshold theo issue yêu cầu ở mục 4.

**Quan sát định hướng (không phải threshold chính thức):** atom_count tuyệt
đối của các tour rất ngắn trong mẫu 115 khá thấp — 6 tour dưới 500 ký tự chỉ
sinh 1–14 atom (trung vị thấp), trong khi tour dài hàng chục nghìn ký tự có
thể sinh tới 47-48 atom. Nhưng n=6 cho nhóm ngắn là quá nhỏ để tin cậy.
**Đề xuất bước tiếp theo cụ thể**: chạy đếm `Day \d+` trên toàn bộ 763 tour +
chạy N2 decompose thử nghiệm có kiểm soát trên một mẫu ngẫu nhiên (không
chạy tay chọn lọc) 15-20 tour trải đều theo percentile độ dài, rồi đo lại
tương quan atom_count/length và số ngày detect — trước khi chốt 1 con số.

---

## PHẦN 3 — Phác thảo thiết kế (KHÔNG BUILD)

### 3.1 — UI chọn tour để atom hoá (nguồn: `v_trip_registry`, không phải `raw_tours` thô)

Cột cần hiển thị để Nghiep/Trang quyết định (dựa trên view definition thật,
xem Phần 3.3):

- `name` (`src_name`), `destination` (`country`), `duration_raw`
- độ dài `itinerary_source` (ký tự) — tín hiệu duy nhất hiện có, hiển thị kèm
  percentile trong 763 tour (vd "2,140 ký tự — p48")
- **đã có atom chưa** — JOIN `DISTINCT tour_id FROM acp_contract.tour_atoms`,
  để không cho chọn lại tour đã atom hoá (loại trừ 115 tour hiện có)
- `lifecycle_stage`, và nếu đã publish: `quality_score`, `trip_url`/`url_alive`
  (đã có landing page thật chưa, theo ADR-2026-030)
- Sort/filter theo độ dài tăng dần — để mắt soát nhanh nhóm mỏng nhất trước
  khi có threshold chính thức từ Phần 2

### 3.2 — Luồng auto-trigger có điều kiện

```
tour mới ingest (raw_tours, pipeline_status)
        │
        ▼
   qua v_trip_registry filter (không trashed/deleted/rỗng)
        │
        ▼
   [ngưỡng độ dài/ngày — CHƯA CHỐT, xem Phần 2]
        │
   ┌────┴─────┐
   ▼ trên ngưỡng        ▼ dưới ngưỡng
auto N2 decompose      queue "cần review tay"
(Claude Bedrock,       (màn hình mới — chưa
KHÔNG Palmyra,          có UI, đây là gap
per AA-308B)            chính AA-345 nêu)
   │                       │
   ▼                       ▼
tour_atoms rows        Nghiep/Trang chọn tay
(owner_scope=platform) từ đây → chạy decompose
   │                    thủ công qua cùng nút
   └──────────┬─────────┘
              ▼
     acp_contract.tour_atoms
     (atom mới xuất hiện trong
      /admin/curation — AA-300,
      ĐÃ CÓ, không xây lại)
```

Vì Phần 2 chưa chốt được ngưỡng, đề xuất **tạm thời**: mọi tour mới ingest
đều rơi vào queue "cần review tay" (không auto-decompose ngay), cho đến khi
chạy xong bước thử nghiệm 15-20 tour đề xuất ở Phần 2 và có số liệu tin cậy
để bật auto-trigger.

### 3.3 — Sửa `GET /admin/tours` (`api/routers/admin_pipeline.py:1625-1662`, dòng thật đã lệch so với issue)

Tên cột đã xác nhận qua `information_schema.columns` trên
`silver_aa_internal.raw_tours` (không tin theo issue mà tra lại thật):
`source_status` (enum), `deleted_at` (timestamptz), `src_itineraries` (text)
— cả ba tồn tại đúng như issue giả định.

**Nhưng WHERE clause issue đề xuất có một lỗ hổng NULL-safety:**
`source_status != 'trashed'` sẽ **âm thầm loại bỏ mọi dòng có
`source_status IS NULL`** (SQL three-valued logic: `NULL != 'trashed'` →
`NULL`, không phải `true`). View `v_trip_registry` — chính là nguồn dữ liệu
"đúng" mà issue muốn đối chiếu — đã tự xử lý đúng việc này:

```sql
WHERE (rt.source_status IS NULL OR rt.source_status::text <> 'trashed'::text)
  AND rt.deleted_at IS NULL
  AND rt.src_itineraries IS NOT NULL
  AND TRIM(BOTH FROM rt.src_itineraries) <> ''::text
```

**Đề xuất copy đúng pattern này** (không dùng bản đơn giản trong issue) để
`GET /admin/tours` sau khi sửa khớp chính xác với filter 763-tour của
`v_trip_registry`, trừ câu hỏi tour-đã-publish còn treo ở Phần 1.

Vì Phần 1 chưa đủ bằng chứng chốt chủ ý/bug, đề xuất: áp filter
trash/delete/rỗng-itinerary ngay (đúng phần "tối thiểu phải thêm" issue đã
tự nêu, không tranh cãi) — nhưng **giữ nguyên việc hiện tour đã publish**
(thêm badge/toggle "đã publish" thay vì ẩn hẳn) cho đến khi Nghiep xác nhận
trực tiếp, thay vì tự quyết định ẩn.

### 3.4 — Đối chiếu AA-300 (Curation UI, N3) — có chồng lấn không?

**Không chồng lấn phạm vi.** AA-300 (Done, PR #83-93, merged) xây
`/admin/curation` — 3 endpoint (`GET /admin/atoms`, `PATCH
/admin/atoms/{atom_id}`, `GET /admin/atoms/preview-slotgrid`) đọc/sửa atom
**đã tồn tại sẵn** trong `acp_contract.tour_atoms`. Không endpoint nào trong
AA-300 chọn tour từ `raw_tours`/`v_trip_registry` hoặc gọi N2 decompose để
**tạo** atom mới — xác nhận qua đọc `admin_atoms.py` (3 route trên) và toàn
bộ 7 addendum trong `docs/implementation-notes/AA-300.md`, không route nào
trigger decompose. Chính issue AA-345 cũng đã tự ghi nhận đúng ranh giới này:

> "Sidebar có 'Atom Curation' (N3 — sửa atom đã có), nhưng không có màn hình
> nào chọn tour từ raw_tours để chạy N2 decompose."

**Ranh giới đề xuất**: AA-345 phụ trách **trước-decompose** (chọn tour →
trigger N2 → atom được tạo), AA-300 phụ trách **sau-decompose** (curate atom
đã có — star/xoá/sửa text/preview slot). Khi decompose của AA-345 chạy xong
cho một tour, UI nên link thẳng sang `/admin/curation` (lọc theo tour đó)
thay vì xây một màn hình review atom thứ hai.

---

## Việc CHƯA làm (theo đúng chỉ đạo)

Không sửa `admin_pipeline.py`. Không tạo UI mới. Không chạy N2 decompose thử
nghiệm. Không tự chọn số threshold. Dừng ở đây, chờ Nghiep/Claude Chat xác
nhận trước khi sang bước implement — bao gồm cả việc quyết định lại con số
"115 tour / 648 gap" (thay vì "26/737") có cần cập nhật lại vào issue AA-345
trên Linear hay không.

---

## PHẦN 4 — Thử nghiệm N2 decompose trên mẫu ngẫu nhiên (12/08, tiếp theo STEP 0)

**Ghi chú quan trọng**: khác STEP 0 (chỉ đọc), phần này **ghi dữ liệu thật** vào
`acp_contract.tour_atoms` (Bedrock Claude Sonnet thật, tốn phí thật). Đã xác nhận
rõ với Nghiep trước khi chạy theo đúng yêu cầu prompt.

### Bước 1+2 — Mẫu ngẫu nhiên có kiểm soát + đo số ngày detect được (toàn bộ 648 tour)

**Cơ chế thật đã đọc trước khi chạy** (không đoán): `POST /v1/atoms/decompose`
(`api/routers/v1_atoms.py`) — dual-path AA-305, <100 tour dùng
`_decompose_inline()`: gọi `invoke_claude(..., model="sonnet", ...)` tuần tự
(không song song) qua satellite chain AA-296 (`shared/llm_client/bedrock_satellite.py`,
acc2→acc1 AssumeRole, model = Claude Sonnet 4.6 — **đúng yêu cầu AA-308B, không
phải Palmyra**), ghi `acp_contract.tour_atoms` với `owner_scope='platform'`,
đúng convention 115 tour cũ. Thử nghiệm này gọi thẳng hàm `_decompose_inline()`
thật (không viết lại logic riêng) để đảm bảo đúng 100% code production, tránh
lệch hành vi.

**Regex số ngày** (chốt sau khi đọc thật 10 mẫu itinerary trải đều theo độ dài,
bucket 1-8 theo `ntile(8)`): các biến thể quan sát được — `"Day 1"`, `"Day 01:"`,
`"DAY 1 –"`, `"Day 01: "` (khoảng trắng/dấu câu sau số ngày không cố định, chữ
hoa/thường không cố định). Không tìm thấy biến thể tiếng Việt ("Ngày") trong
648 tour (`ILIKE '%ngày%'` → 0 kết quả — dữ liệu 100% tiếng Anh ở tầng này).
Regex chốt: `\bday\s*0*\d{1,2}\b` (case-insensitive), đếm SỐ NGÀY PHÂN BIỆT
(distinct số sau "day"), không đếm số lần xuất hiện thô.

**Phân bố day_count trên toàn bộ 648 tour (chưa atom hoá)**:
```
n = 648          zero_day_count_tours = 133 (20.5%)
p10 = 0    p25 = 1    p50 = 7    p75 = 11    p90 = 15
min = 0    max = 28   mean = 7.15
```
133/648 tour (20.5%) không detect được ngày nào — đọc thật 5 mẫu xác nhận đây
là **tour 1 ngày thật** ("Day tour program", excursion trong ngày) hoặc
**itinerary viết dạng văn xuôi liên tục không có nhãn ngày rõ ràng** (vd
"Start your tour at 6:30 AM..." không chia theo Day N), không phải lỗi regex.

**Tương quan Pearson length vs day_count trên 648 tour: 0.70** (khá mạnh, dương)
— độ dài ký tự và số ngày detect được có xu hướng tăng cùng nhau, nhưng không
tuyệt đối (r=0.70, không phải 1.0) — vẫn có tour dài mà ít ngày (văn xuôi dài
dòng cho 1 ngày) và tour ngắn mà nhiều ngày (liệt kê súc tích).

### Mẫu ngẫu nhiên đã chọn (20 tour, `random.seed(20260812)` để tái lập được, 4-4-3-3-3-3 theo 6 bucket percentile từ STEP 0)

| # | tour_id | length | day_count | bucket |
|---|---|---|---|---|
| 1 | 59b776f2-a160-48e4-8771-30f33892195e | 613 | 0 | <p10 |
| 2 | a1dcfe8d-3db5-4065-8e48-b25ba4f49aa9 | 642 | 0 | <p10 |
| 3 | 81e811f9-8bb3-4c8a-a478-d0a2a200f003 | 422 | 0 | <p10 |
| 4 | 2d0c76a8-8fc0-42be-9286-dc6aa31127ba | 335 | 0 | <p10 |
| 5 | cbb66854-8066-405e-b83b-7458693b2a3e | 1308 | 2 | p10-p25 |
| 6 | 66ebe919-3bbc-423a-a695-005ddf53781f | 1224 | 0 | p10-p25 |
| 7 | 70553197-0ed6-4205-910e-90b8b21850bf | 878 | 6 | p10-p25 |
| 8 | c2681a4d-7215-4954-9e3f-6af7f1aa323a | 1410 | 0 | p10-p25 |
| 9 | c31ed889-1914-4057-bb28-853ceb885d07 | 2486 | 0 | p25-p50 |
| 10 | 08960b8d-c453-4a61-9c2f-b3e4e8d99ff9 | 1615 | 10 | p25-p50 |
| 11 | 687b7440-e872-4c6d-aed3-9c67f0eb0d1e | 2003 | 6 | p25-p50 |
| 12 | 078edffc-0192-4176-b589-7647cab2e11e | 4331 | 16 | p50-p75 |
| 13 | 2de0affb-08a2-44f2-a2ff-577b6befd651 | 4044 | 9 | p50-p75 |
| 14 | b1214f62-8c80-454b-8e93-439a718f93ef | 3133 | 26 | p50-p75 |
| 15 | 47bde8a0-6871-45d6-b0e1-96b0df2c44a4 | 9567 | 15 | p75-p90 |
| 16 | d4897d02-a9c9-4868-9c7f-889b1ba48c51 | 7493 | 10 | p75-p90 |
| 17 | 16350d17-8d90-4163-ae4b-0f3d824ea9f6 | 7535 | 8 | p75-p90 |
| 18 | 0b6e28fb-1f90-42a0-868f-cd916ab064ac | 11676 | 13 | ≥p90 |
| 19 | 1ff2935f-bcd3-4103-bd5e-05246eaf3490 | 10678 | 18 | ≥p90 |
| 20 | 11b4cd7e-0e07-4292-a5c0-3918aaecf768 | 14440 | 18 | ≥p90 |

Ghi lại TRƯỚC khi chạy decompose (Bước 3), đúng yêu cầu tái lập được.

### Bước 3 — Chạy N2 decompose thật (đang chạy, xem cập nhật bên dưới)

**Kết quả**: **20/20 tour thành công, 0 thất bại, 0 empty-marker** (kể cả 4 tour
ngắn nhất, day_count=0). Không cần dừng giữa chừng — không tour nào lỗi. 20
job row mới trong `acp_contract.atom_decompose_jobs` (`atomjob_*`), đúng
convention cũ.

(Ghi chú vận hành: lần đầu poll qua `aws ecs execute-command` liên tục bị
`Cannot perform start session: EOF` do 2 phiên SSM tương tác cạnh tranh trên
cùng 1 task — không phải job bị treo. Đã xác nhận job thật sự chạy xong bằng
cách cho script tự upload log lên S3 rồi tải về đọc sạch, thay vì đọc qua SSM
output trực tiếp.)

| # | tour_id | length | day_count | atom_count | bucket |
|---|---|---|---|---|---|
| 1 | 59b776f2 | 613 | 0 | 4 | <p10 |
| 2 | a1dcfe8d | 642 | 0 | 5 | <p10 |
| 3 | 81e811f9 | 422 | 0 | 4 | <p10 |
| 4 | 2d0c76a8 | 335 | 0 | 3 | <p10 |
| 5 | cbb66854 | 1308 | 2 | 5 | p10-p25 |
| 6 | 66ebe919 | 1224 | 0 | 7 | p10-p25 |
| 7 | 70553197 | 878 | 6 | 6 | p10-p25 |
| 8 | c2681a4d | 1410 | 0 | 6 | p10-p25 |
| 9 | c31ed889 | 2486 | 0 | 13 | p25-p50 |
| 10 | 08960b8d | 1615 | 10 | 9 | p25-p50 |
| 11 | 687b7440 | 2003 | 6 | 7 | p25-p50 |
| 12 | 078edffc | 4331 | 16 | 15 | p50-p75 |
| 13 | 2de0affb | 4044 | 9 | 10 | p50-p75 |
| 14 | b1214f62 | 3133 | 26 | 8 | p50-p75 |
| 15 | 47bde8a0 | 9567 | 15 | 21 | p75-p90 |
| 16 | d4897d02 | 7493 | 10 | 12 | p75-p90 |
| 17 | 16350d17 | 7535 | 8 | 17 | p75-p90 |
| 18 | 0b6e28fb | 11676 | 13 | 22 | ≥p90 |
| 19 | 1ff2935f | 10678 | 18 | 16 | ≥p90 |
| 20 | 11b4cd7e | 14440 | 18 | 17 | ≥p90 |

### Bước 4 — Đo tương quan (mẫu ngẫu nhiên, n=20)

```
corr(length, atom_count)    = 0.887   (mạnh, dương)
corr(day_count, atom_count) = 0.619   (trung bình, dương)
```

**Rõ hơn hẳn** so với mẫu 115 tour chạy tay (STEP 0 không thấy tương quan chất
lượng nào với độ dài) — nhưng đây là tương quan với **atom_count tuyệt đối**,
không phải chất lượng. Atom_count tăng theo độ dài là điều tự nhiên (nhiều
nguyên liệu hơn → nhiều atom hơn), không phải bằng chứng "tour ngắn sinh atom
tệ".

**Mật độ atom (atom/1000 ký tự) — quan trọng hơn atom_count tuyệt đối:**
```
4 tour ngắn nhất (<p10, 335-642 ký tự): 6.5 – 9.5 atom/1000 ký tự
3 tour dài nhất (≥p90, 10,678-14,440 ký tự): 1.2 – 1.9 atom/1000 ký tự
```
**Tour ngắn có mật độ atom CAO HƠN tour dài**, không thấp hơn — ngược với lo
ngại ngầm định trong issue rằng tour mỏng sẽ "sinh atom rác" hoặc kém hiệu
quả. Atom_count tuyệt đối thấp ở tour ngắn chỉ vì ít nguyên liệu, không phải
vì trích xuất kém.

**Chất lượng (length(trim(text)) < 20)**: **0 trên 218 atom** (tổng 20 tour)
dưới 20 ký tự — khớp hoàn toàn với kết quả âm tính của 115 tour cũ (STEP 0).
Tổng cộng qua cả 2 mẫu (115 chạy tay + 20 ngẫu nhiên = 135/763 tour, 18%)
**không tìm được một atom rỗng/quá ngắn nào**, ở bất kỳ độ dài nguồn nào từ 80
đến 27,409 ký tự.

**Đánh giá định tính (tour ngắn nhất trong mẫu, 335 ký tự — tour đạp xe "17
nhà vệ sinh" ở Shibuya, Tokyo)**: đọc thật cả 3 atom sinh ra:
1. "Visit 17 toilets in Shibuya through a specially designed route."
2. "Depart at 09:00 from the Shinkawa, Chuo-ku office and return to the same
   office by 15:00, covering the full route by rental bike with helmet
   provided."
3. "A box lunch and bottle of water are included, fueling the ride between
   toilet stops."

Đối chiếu với nguồn 335 ký tự: cả 3 atom đều bám sát nguyên văn, không thêm
chi tiết bịa, không lặp lại nhau, không generic — **không phải atom rác**, dù
đây là tour cực ngắn, không có nhãn ngày.

### Bước 5 — Đề xuất threshold

**Không đề xuất một ngưỡng độ dài/số ngày để CHẶN decompose.** Bằng chứng thu
được lật ngược giả định ban đầu của issue:

1. Mối tương quan RÕ duy nhất tìm được (length↔atom_count, r=0.887) đo
   **số lượng**, không đo **chất lượng** — và không phải thứ threshold cần
   chặn. `THIN_TRIP_ATOM_MIN` (constant có sẵn, `services/acp_shared/
   atom_constants.py`, đã dùng trong AA-300) đã tự động flag tour ít atom
   **sau khi** decompose — không cần dự đoán trước bằng độ dài nguồn.
2. **Không có bằng chứng chất lượng kém ở tour ngắn** qua 2 mẫu độc lập (115
   chạy tay + 20 ngẫu nhiên, 135/763 tour, trải từ 80-27,409 ký tự) — 0 atom
   rỗng/ngắn bất thường ở bất kỳ đâu, và đọc tay xác nhận atom từ tour ngắn
   nhất (335 ký tự) là thật, bám nguồn, không generic.
3. **0/20 tour ngẫu nhiên thất bại hoặc sinh empty-marker** — kể cả 4 tour có
   `day_count=0` (tour 1-ngày hoặc văn xuôi không nhãn ngày). Nỗi lo "auto
   decompose tour mỏng tốn tiền vô ích" trong issue **không được xác nhận**
   bởi dữ liệu này.

**Đề xuất cụ thể**: bỏ ý tưởng "ngưỡng độ dài để chặn auto-decompose". Thay
vào đó:
- Auto-decompose **mọi tour mới ingest** (qua `v_trip_registry` filter sẵn
  có — trashed/deleted/rỗng), không cần bước lọc độ dài trước.
- Dùng `THIN_TRIP_ATOM_MIN` (đã có, không cần field/logic mới) để gắn cờ
  "cần review tay" **SAU** decompose, dựa trên atom_count thật, không dựa
  trên độ dài nguồn dự đoán trước.
- Điều này khớp với đúng luật curation đã ghi trong AA-300 ("Bắt buộc với
  thin trip <5 atom, tour giàu ≥8 atom → sample check 20%") — AA-345 không
  cần phát minh luật mới, chỉ cần nối vào cơ chế post-hoc đã có.

**Giới hạn cần nêu rõ**: n=20 (vòng này) + n=115 (chạy tay trước) = 135/763
(18%) — đủ để bác bỏ giả thuyết "có một vực chất lượng rõ ràng ở tour ngắn"
(2 mẫu độc lập, 7 bucket percentile, đều không thấy), nhưng **chưa đủ để
khẳng định tuyệt đối không có trường hợp xấu nào** trong 628 tour còn lại.
Đề xuất: khi auto-decompose thật được bật (Phần 3.2), giữ nguyên bước review
tay của Trang cho nhóm thin-trip (đã có sẵn trong AA-300) làm lưới an toàn,
thay vì tin tuyệt đối vào kết luận "không cần threshold" này mà bỏ qua kiểm
tra con người hoàn toàn.

---

## Việc CHƯA làm (cập nhật sau Phần 4)

Không build UI, không sửa `admin_pipeline.py`, không sửa thêm issue AA-345
trên Linear, không tạo migration. Đã ghi dữ liệu thật (20 tour × atom mới,
20 job row `atom_decompose_jobs`) — nằm trong phạm vi được yêu cầu, không tự
ý mở rộng thêm. 135/763 tour giờ đã có atom (115 cũ + 20 mới) — nếu tiếp tục
atom hoá phần còn lại, đó là quyết định của bước sau, không tự động làm tiếp
ở đây. Dừng lại, chờ Nghiep/Claude Chat review kết luận Phần 4-5 trước khi
quyết có auto-decompose toàn bộ 628 tour còn lại hay không.
