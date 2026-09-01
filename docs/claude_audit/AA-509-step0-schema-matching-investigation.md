# AA-509 STEP0 — Segment schema + matching, đối chiếu schema thật (post-AA-508/migration 128)

Investigation only — không build gì. Mục tiêu: xác nhận thiết kế gốc trong Linear AA-509 còn
đúng với schema thật hay không, và đề xuất điều chỉnh trước khi giao build prompt.

## 1. `acp_contract.tour_atoms` thật (xác nhận qua migration 079+084+085+093+128, không suy đoán)

```
atom_id           TEXT PRIMARY KEY        -- content-hash (AA-508) hoặc "atom_"+uuid[:10] (legacy)
tour_id           UUID NOT NULL REFERENCES silver_aa_internal.raw_tours(tour_id)
owner_scope       TEXT NOT NULL DEFAULT 'platform'   -- 079: 'platform' (admin) | tenant_id string (T5)
text              TEXT NOT NULL           -- 1 field GỘP, verbatim moment (place+action không tách)
activity_type     TEXT                    -- enum: trek|bike|food|culture|stay|transit|other
emotional_hook    TEXT
visual_potential  SMALLINT (1-3)
persona_fit       JSONB
season_note       TEXT
distinctiveness   TEXT ('HIGH'|'MED'|'LOW')
media             JSONB
starred           BOOLEAN
deleted           BOOLEAN
usage_log         JSONB
cooldown_until    JSONB
human_seam_notes  JSONB
weight            NUMERIC
created_at/updated_at TIMESTAMPTZ
source_hash       TEXT        (084 — whole-tour hash, fallback/audit only since AA-508)
is_empty_marker   BOOLEAN     (085)
itinerary_day     SMALLINT NULL (093 — LLM self-extracted day/order, NULL for pre-093 rows)
```

**Không có `place`/`action` tách riêng, không có `canonical_place`/`canonical_action`** — đã grep
toàn bộ `api/migrations/*.sql` cho `ADD COLUMN.*place`/`ADD COLUMN.*action`/`canonical_place`/
`canonical_action`: 0 kết quả ngoài false-positive không liên quan. Xác nhận đúng như AA-508 đã ghi
nhận và đúng như cảnh báo trong Linear AA-509 gốc ("kiểm tra kiểu dữ liệu khớp khi JOIN trước khi
viết migration thật").

## 2. `src/aa_social/matching.py` + `segments.py` — thuật toán thật dùng field gì

Đọc trực tiếp `docs/AI-gent-for automation works/aa-soscial-media-main/src/aa_social/{segments,
matching,models}.py`. Xác nhận: **grouping (Segment) và matching (search-demand→atom) là 2 module
khác nhau, dùng field khác nhau**:

- **Grouping** (`segments.py::derive_segments()`) — chạy trên `Atom.place` và `Atom.action`
  (2 field tách riêng trong `models.py`), KHÔNG dùng embedding (ADR 0002, xem mục 3):
  - `place`: token-set (connector-stripped, lowercase) — 2 Atom nối khi Jaccard ≥ 0.5 hoặc một
    tập con của tập kia (`_looks_like_one_moment`).
  - `action`: đọc **động từ dẫn đầu** (`_leading_verb`, stemmed, qua bảng đồng nghĩa hẹp
    `reference/action-verbs.toml`) — 2 Atom chỉ nối khi verb khớp NHAU (equality, không phải
    similarity) VÀ phần còn lại của action ("about") liên quan (`_about_the_same_thing`).
  - Kết quả: connected-components (union-find) trên toàn bộ Atom của 1 lần chạy, không có
    embedding nào tham gia bước này.
- **Matching** (`matching.py::match_queries_to_atoms()`) — chạy trên `place` (view riêng) và
  `place + action` gộp (view "said") của từng Atom, DÙNG embedding (fallback: token-overlap khi
  không có embedder) để nối search-demand (DataForSEO keyword/PAA) vào Atom gần nhất, rồi lan ra
  cả Segment atom đó thuộc về.

**Kết luận trực tiếp cho AA-509**: AA-509's scope (theo Linear) là bước Grouping thôi (Segment +
`atom_segment_member`) — Matching (search-demand→atom) không nằm trong AA-509 (đó là việc khác,
chưa có ticket). Nhưng thuật toán Grouping thật **phụ thuộc cấu trúc `place`/`action` tách riêng
mà AA-CIS schema không có** — xem mục 4 để biết 2 hướng giải quyết.

## 3. ADR 0002 — lý do grouping phải deterministic (đối chiếu, không suy diễn)

Đọc `docs/adr/0002-vector-store-scoped-to-search-matching.md` trực tiếp. Xác nhận đúng như trích
dẫn gốc trong Linear AA-509:

> "Grouping stays deterministic — token similarity on `place` plus verb match on `action`. It is
> idempotent, auditable, costs nothing, and produces a stable `segment_id` across re-runs and
> re-ingests. Embedding clusters would put a stochastic step under an identity the Calendar
> depends on: a re-run that silently regroups Atoms invalidates every slot built on the old ids."

Và về id stability (đoạn cuối ADR, khớp với `segments.py::reconcile_ids()`):

> "An id derived from the current members alone moves when the members change... So the id is
> derived from member identity when a Segment is first seen — never from arrival order — and held
> from then on. Where a bridging trip forces two ids into one, the id that gave way is recorded as
> an alias, so a Calendar row built on it still resolves."

Xác nhận: `_mint()` derive `segment_id` = `sha256(sorted place tokens + verb)[:16]` **chỉ khi lần
đầu thấy Segment**; `reconcile_ids()` sau đó giữ id cũ nếu Segment đã tồn tại (so khớp qua
`assigned: atom_id → segment_id` cũ), và khi 2 Segment cũ bị 1 Atom mới "bắc cầu" thành 1, id thua
cuộc được ghi làm **alias** (segment_id → segment_id, không phải atom-level). Điểm này quan trọng
cho mục 5 (schema `is_alias`).

## 4. Vấn đề cốt lõi: `text` gộp + `activity_type` enum vs. `place`/`action` tách riêng

Thuật toán gốc cần 2 tín hiệu độc lập (place similarity, action verb match) để tránh 2 lỗi:
- Chỉ dùng place → "visit temple" và "eat lunch" ở CÙNG 1 địa điểm bị gộp sai thành 1 Segment.
- Chỉ dùng action → "walk the Nakasendo trail" ở Magome và ở Narai (2 địa điểm khác nhau, cùng
  hành động "walk") bị gộp sai thành 1 Segment.

AA-CIS schema chỉ có `text` (câu verbatim gộp) + `activity_type` (7 giá trị enum thô: trek/bike/
food/culture/stay/transit/other — không phải verb, không phải noun-phrase địa điểm). Không thể
derive `place`/`action` tách biệt từ 2 field này bằng regex/heuristic đáng tin cậy — `text` là câu
tự do do LLM viết lại (T5 SYSTEM_PROMPT chỉ yêu cầu "1-2 câu, verbatim-derived", không có cấu trúc
cố định "địa điểm — hoạt động").

**2 hướng khả thi — đây là quyết định sản phẩm cần Nghiệp chốt, không tự quyết ở STEP0:**

**Hướng A — Thêm field `place`/`action` tách riêng vào decompose (đổi SYSTEM_PROMPT + schema).**
- Thêm 2 field mới vào `SYSTEM_PROMPT` JSON contract (`atom_extraction.py`) + 2 cột mới trên
  `tour_atoms` (migration), để T5 tự tách `place`/`action` ngay lúc atomize — port gần nguyên văn
  thuật toán gốc, không cần đổi logic `segments.py`.
- Rủi ro: sửa `SYSTEM_PROMPT` nghĩa là đổi `day_fingerprint()`'s hash input (fingerprint hash gồm
  `SYSTEM_PROMPT` — AA-508 migration 128 comment) → mọi fingerprint cache cũ tự động invalidate
  (không phải bug, nhưng cần biết trước: lần chạy Segment đầu tiên sau khi đổi prompt sẽ re-atomize
  TOÀN BỘ atom hiện có, tốn LLM call). Cũng LLM-derived nên place/action tách ra không hoàn toàn
  deterministic giữa 2 lần chạy giống hệt input — nhưng vì T5 đã fingerprint-cache theo ngày
  (AA-508), place/action 1 atom chỉ đổi khi ngày đó thực sự re-atomize, không đổi ngẫu nhiên mỗi
  lần Segment chạy — nên KHÔNG vi phạm ADR 0002 (Segment tự nó vẫn derive deterministic từ
  place/action đã lưu, việc place/action đó tới từ LLM 1 lần rồi cache lại là chấp nhận được, y hệt
  cách reference repo cũng dùng LLM để tạo `place`/`action` ở stage `atoms` rồi mới derive Segment
  deterministic từ kết quả đã lưu đó — không phải reference repo có place/action "miễn phí không
  LLM", chỉ là stage atoms của họ ra sẵn 2 field, decompose của AA-CIS thì không).

**Hướng B — Đổi thuật toán matching để chạy trên schema hiện có (`text` + `activity_type`), không
đổi decompose.**
- Token-similarity (Jaccard, connector-stripped, giống `_place_tokens()`) chạy trên TOÀN BỘ `text`
  thay vì riêng `place` — mất khả năng phân biệt "cùng địa điểm khác hoạt động" mà thuật toán gốc
  cố tình giữ tách (ví dụ trên sẽ gộp "visit temple" + "eat lunch" tại chùa thành 1 Segment nếu 2
  câu `text` đủ giống từ vựng).
  - Giảm rủi ro gộp sai: dùng `activity_type` làm gate BẮT BUỘC PHẢI KHỚP trước khi so token
    (giống vai trò verb-match ở thuật toán gốc, nhưng thô hơn nhiều — 7 giá trị enum so với không
    gian verb mở). "walk the Nakasendo trail" (activity_type=trek, ở Magome) và "walk the village
    street" (activity_type=trek, ở Narai) đều `trek` → vẫn phải dựa vào token-similarity trên
    toàn câu để tách 2 địa điểm, không có gì tương đương `place` sạch để so riêng.
- Không cần sửa `SYSTEM_PROMPT`/fingerprint — 0 rủi ro re-atomize hàng loạt, build nhanh hơn.
- Độ chính xác nhóm kém hơn thuật toán gốc — cần chấp nhận as trade-off, đo thử trên dữ liệu thật
  (số atom hiện có ít, có thể sample-check bằng mắt sau khi build) trước khi coi là đủ tốt.

**Đề xuất (không phải quyết định cuối)**: Hướng B trước — build nhanh, không đổi fingerprint/T5,
đo chất lượng nhóm trên dữ liệu thật; nếu chất lượng không đạt (quá nhiều false-merge cùng
activity_type khác địa điểm, hoặc quá manh mún vì activity_type quá thô), quay lại Hướng A như
follow-up có ticket riêng. Cần Nghiệp xác nhận hướng trước khi viết build prompt.

## 5. JOIN `atom_segment.tenant_id` (UUID) ↔ `tour_atoms.owner_scope` (TEXT tự do)

Xác nhận bằng đọc trực tiếp `tenant_pipeline.py::run_t5_atomize()`/`_atomize_per_day()`/
`_atomize_whole_tour_legacy()`: `owner_scope` được set = tham số `tenant_id` (string) TRỰC TIẾP,
không qua transform — nghĩa là với atom T5 (tenant tự rewrite), `owner_scope` LÀ chuỗi UUID thật
của `shared.tenants.tenant_id` (ví dụ `1bae2159-671b-4f35-a782-e96ea4cbdd4a`), chỉ là cột khai báo
kiểu TEXT chứ không phải giá trị rác. Atom platform/admin (N2 cũ, nay đã xoá theo AA-475/477) dùng
literal string `'platform'` — KHÔNG parse được thành UUID.

`services/acp_shared/atom_extraction.py::content_hash_atom_id()` cũng xác nhận lại đúng điều này
(docstring: "owner_scope (the rewriting tenant's id, or 'platform')").

**Kết luận cho migration/query thật:**
- `atom_segment.tenant_id UUID NOT NULL` — đúng như schema gốc, GIỮ NGUYÊN kiểu UUID (không đổi
  thành TEXT) vì Segment theo đúng scope của AA-509 ("group atom... của cùng tenant") vốn dĩ chỉ
  có nghĩa cho atom có 1 tenant sở hữu rõ ràng — atom `owner_scope='platform'` không có 1 tenant
  duy nhất để gán `atom_segment.tenant_id`, nên **loại trừ hoàn toàn** khỏi input của
  `segment_matching.py`, không cần cố ép JOIN.
- Query thật lấy atom cho 1 tenant: `WHERE owner_scope = $1` (so sánh TEXT=TEXT với tenant_id đã
  `::text`), KHÔNG `owner_scope::uuid = $1::uuid` — vì nếu tồn tại bất kỳ row nào có
  `owner_scope='platform'` hoặc giá trị không phải UUID lẫn trong tập đang quét (không nên xảy ra
  nếu WHERE đã lọc theo tenant_id cụ thể, nhưng cast ép kiểu trên CẢ CỘT trước khi lọc sẽ crash
  toàn bộ query nếu có 1 row 'platform' lẫn trong tour_atoms của cùng batch — an toàn hơn là so
  sánh TEXT=TEXT, không ép kiểu cột).
- Khi INSERT vào `atom_segment`/kết quả trả về tenant_id UUID: dùng tenant_id đã có sẵn trong tay
  (tham số đầu vào của `segment_matching.py`, không phải parse ngược từ `owner_scope`) — tránh mọi
  rủi ro cast-fail, vì hàm được gọi VỚI 1 tenant_id cụ thể ngay từ đầu (giống cách
  `run_t5_atomize(tenant_id, ...)` đã nhận sẵn).

## 6. Schema `atom_segment`/`atom_segment_member` điều chỉnh

**Không đổi khoá/kiểu dữ liệu cấp bảng** — chỉ đổi ý nghĩa nội dung 2 cột `canonical_place`/
`canonical_action` vì không có nguồn tương ứng trực tiếp:

```sql
-- Số migration thật: 129 (128 đã dùng bởi AA-508 — xác nhận qua ls api/migrations/, không phải
-- 127 như đề xuất tạm trong Linear).

CREATE TABLE acp_contract.atom_segment (
  segment_id       TEXT PRIMARY KEY,
  tenant_id        UUID NOT NULL REFERENCES shared.tenants(tenant_id),
  -- Hướng B (đề xuất): đổi tên phản ánh đúng nguồn — không "canonical_place"/"canonical_action"
  -- (không có field tương ứng), thay bằng:
  canonical_text     TEXT NOT NULL,   -- Atom.text của member được chọn làm nhãn (giống _canonical()
                                       -- chọn member "kinh tế" nhất — ít từ phân biệt nhất, cần
                                       -- định nghĩa lại tiêu chí chọn nhãn cho 1 field gộp)
  canonical_activity TEXT,            -- Atom.activity_type của member đó (đổi tên cho khớp cột thật)
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
  -- Nếu chọn Hướng A (thêm place/action riêng vào decompose) thì GIỮ NGUYÊN canonical_place/
  -- canonical_action như Linear gốc — 2 cột đó có nguồn thật lúc đó.
);

CREATE TABLE acp_contract.atom_segment_member (
  segment_id  TEXT NOT NULL REFERENCES acp_contract.atom_segment(segment_id),
  atom_id     TEXT NOT NULL REFERENCES acp_contract.tour_atoms(atom_id),
  is_alias    BOOLEAN NOT NULL DEFAULT false,   -- xem câu hỏi mở bên dưới — ngữ nghĩa CHƯA rõ
  PRIMARY KEY (segment_id, atom_id)
);
```

**Câu hỏi mở về `is_alias` (chưa tự quyết, cần chốt trước khi build):** Cơ chế alias thật của
reference repo (`reconcile_ids()`) hoạt động Ở CẤP `segment_id` (id cũ → id mới khi 2 Segment nhập
làm 1), KHÔNG phải cấp từng atom-member. Schema Linear gốc đặt `is_alias` trên
`atom_segment_member` (per atom_id, per segment_id) — ngữ nghĩa này không khớp trực tiếp với cơ chế
gốc. Có 2 khả năng, cần Nghiệp/thiết kế gốc xác nhận ý định:
  (a) `atom_segment_member.is_alias` đơn giản là chưa cần dùng ngay (place-holder cho tương lai),
      và cơ chế alias thật cần **thêm 1 bảng riêng** `atom_segment_alias (prior_segment_id TEXT PK,
      current_segment_id TEXT NOT NULL REFERENCES atom_segment(segment_id))` mirror đúng
      `reconcile_ids()`'s aliases dict — đây là bảng schema gốc CHƯA có, cần bổ sung nếu muốn giữ
      đúng bảo đảm "segment_id cũ vẫn resolve" của ADR 0002.
  (b) hoặc `is_alias=true` đánh dấu 1 atom_id gia nhập Segment qua 1 lần merge bắc cầu (khác với
      atom có mặt từ lần derive đầu) — nếu vậy cần logic riêng để set cờ này đúng lúc
      `_connected()`/reconcile chạy, và KHÔNG thay thế được nhu cầu resolve segment_id cũ→mới ở
      (a) (đó là 2 vấn đề khác nhau: atom nào aliased vs. segment_id nào aliased).
  → Khuyến nghị: thêm bảng `atom_segment_alias` riêng (giải quyết đúng bảo đảm ADR 0002 nêu), giữ
    `is_alias` trên `atom_segment_member` với ý nghĩa (b) nếu build task thấy cần, hoặc bỏ hẳn cột
    đó nếu không dùng — quyết định cụ thể để trong build prompt, không STEP0 tự chọn.

## 7. Trigger point + chi phí — câu hỏi mở khác (không thuộc phạm vi câu hỏi gốc, nhưng phát hiện
khi đọc kỹ thuật toán, nên nêu ra trước khi build)

`derive_segments()` (reference) chạy **union-find O(n²) trên TOÀN BỘ atom của 1 tenant**, không
phải chỉ atom của 1 tour vừa atomize xong — vì Segment vốn gom atom "qua nhiều tour của cùng
tenant" (đúng như Linear mô tả). Linear yêu cầu "chạy tự động ngay sau T5 hoàn tất, mỗi lần atomize
xong 1 tour version" — nếu mỗi lần trigger đều recompute toàn bộ atom của tenant đó (không chỉ atom
tour vừa xong), cost tăng theo O(tổng atom tenant²) mỗi lần bất kỳ tour nào của tenant đó chạy T5.
Ở quy mô hiện tại (vài chục atom/tenant) không đáng lo, nhưng đáng ghi lại làm known-tradeoff (như
reference repo tự nhận: "worth revisiting if the inventory reaches thousands") — không phải thứ
cần giải ở STEP0 này, chỉ cần build prompt biết để không coi là bug nếu sau này cost tăng.

## Tóm tắt cần Nghiệp chốt trước khi giao build prompt

1. **Hướng A (thêm place/action field vào decompose) hay Hướng B (đổi thuật toán chạy trên text+
   activity_type hiện có)?** — đề xuất Hướng B trước, Hướng A làm follow-up nếu chất lượng không
   đạt. Đây là quyết định ảnh hưởng schema + có đổi field decompose hay không.
2. **`is_alias` — ngữ nghĩa (a) hay (b) ở mục 6, hay bỏ, hay thêm bảng `atom_segment_alias`
   riêng?** — cần chốt để migration đúng ngay từ đầu, tránh phải sửa lại.
3. Xác nhận migration số **129** (không phải 127 như tạm ghi trong Linear).
4. Xác nhận JOIN dùng `owner_scope = tenant_id::text` (so sánh TEXT=TEXT, loại trừ `'platform'`),
   không ép kiểu `owner_scope::uuid` trên cả cột.
