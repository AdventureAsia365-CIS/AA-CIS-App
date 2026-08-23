# AA-449-00 — STEP0: T8 Angle Gate viết mới hoàn toàn — investigation

Investigate only, không sửa code. Worktree `../aa-449-worktree`, branch
`docs/aa-449-00-step0-t8-angle-gate-investigation`. **Bản này thay thế bản round 1** (task đã được
Nghiệp bổ sung: 1 workflow 9-bước "chốt" + 2 bảng gốc từ Google Sheet — nguồn ưu tiên cao nhất, đối
chiếu với `SKILL_v2.md`). Nguồn: `SKILL_v2.md` gốc (366 dòng, đọc toàn bộ), `AA-439-06`/`AA-439-07`
(đã audit T7→T8 và so sánh `acp_s4_social` với nguồn gốc — không lặp lại, chỉ trích), `AA-447-01`
(worktree `aa-447-worktree`), code T7 thật trên `origin/main` (`ad90d07`/`bbb2871`/`7cf3b7b`, đã
merge — đọc trực tiếp `services/acp_planning/*`, `api/routers/v1_planning.py`), schema brand thật
(`api/migrations/018/019_brand_*.sql`, `BrandTab.tsx`), schema `acp_silver_s4.social_content` cũ
(migrations 019/067, chỉ tham khảo SHAPE, không tham khảo code), và **ADR-2026-038 đọc trực tiếp từ
Notion** (page "🔴 [21/08/2026] Content Pipeline Redesign" — KHÔNG tồn tại dưới dạng file trong 4
repo, bản mới nhất tính đến 22/08/2026).

**Headline round 2: workflow + 2 bảng Nghiệp cung cấp KHÔNG mâu thuẫn `SKILL_v2.md`/ADR — chúng là
1 bản merge chính xác của `SKILL_v2.md` (logic nội bộ) + `writing formulars.xlsx`/`Channel Output
Structures.xlsx` (2 file đã tìm thấy từ AA-439-07, chưa từng được trích ĐẦY ĐỦ trước đây). Có 2 phát
hiện quan trọng cần Nghiệp biết trước khi build: (1) chữ "Angle" đang được dùng ở 2 TẦNG khác nhau
trong chính task này — Bảng 1 gọi tên GOAL là "Angle" (Name = Promotion/Lead Gen/...), trong khi
"angle" thật theo `SKILL_v2.md` (và theo đúng nghĩa 3-cái-để-chọn ở bước 5-7 workflow) là 1 tầng
KHÁC, sinh SAU khi đã chọn goal — cần thống nhất tên gọi trước khi build, không tự đổi tên; (2) input
"channel" từ T7 CÓ thật (`Slot.channel`, code đã build), nhưng chỉ hỗ trợ 4 giá trị trong khi Bảng 2
có 7 kênh — 1 gap thật, có bằng chứng code cụ thể (§5).**

---

## 1. Đối chiếu Bảng 1/Bảng 2 với `SKILL_v2.md` — khớp ở đâu, sai khác ở đâu, không âm thầm ghi đè

### 1a. Bảng 1 = merge chính xác của `SKILL_v2.md` (cột logic) + `writing formulars.xlsx` (cột
Marketing term) — đã tìm thấy từ trước (AA-439-07 §A2), giờ mới được trích ĐẦY ĐỦ cả 4 cột

`AA-439-07` (§A2) đã dump `writing formulars.xlsx` bằng `openpyxl` nhưng lúc đó chỉ trích 2 cột
(`Name`/`Marketing term`), không trích `description`/`logic`. Bảng 1 Nghiệp đưa lần này khớp
**chính xác cùng 8 dòng, cùng thứ tự, cùng tên Marketing term** với file xlsx đó (đã xác nhận trước
đây "8 rows — no Partner/supplier goal" — khớp) — chỉ khác là giờ có thêm cột `logic` bằng câu chữ
gần như nguyên văn từ `SKILL_v2.md`'s "Internal Goal Mapping" (`SKILL_v2.md:63-177`, đã trích đủ ở
STEP0 round 1). **Kết luận: Bảng 1 không phải nguồn thứ 3 mới — nó là 2 nguồn cũ (`SKILL_v2.md` +
`writing formulars.xlsx`) đã gộp lại đúng, không mâu thuẫn.**

**2 sai khác cụ thể cần nêu rõ, không tự sửa:**

1. **Header ghi "7 loại" nhưng bảng có 8 dòng** (đếm lại: Promotion, Lead Generation, Conversion,
   Introduction/Awareness, Trust-building, Engagement/Conversation, Event Announcement, Product or
   Service Explanation = 8). Không rõ đây là lỗi đếm khi viết task, hay ý định bớt 1 dòng nhưng quên
   xoá — cần Nghiệp xác nhận, không tự đoán dòng nào cần bỏ.
2. **Dòng Conversion: chữ P trong SLAP lệch nghĩa với nguồn.** `SKILL_v2.md:99-104` định nghĩa rõ
   4 bước Conversion là *"Stop, Look, Act, **Proceed**: reinforce why taking action makes sense"* —
   Bảng 1 ghi *"Stop-Look-Act-**Purchase**"*. Cùng viết tắt SLAP nhưng nghĩa chữ P khác hẳn (Proceed
   = củng cố lý do hành động; Purchase = hành vi mua cụ thể) — ảnh hưởng cách LLM diễn giải bước
   cuối khi build prompt. Cần Nghiệp xác nhận dùng nghĩa nào.
3. **Dòng Lead Generation: "Problem-Agitate-Solve" là tên chuẩn ngành của PAS, không phải nguyên văn
   `SKILL_v2.md`.** `SKILL_v2.md:80-91` mô tả Lead Gen là *"Problem or attention: name the friction
   [...] Insight: explain why it matters [...] Solution/desire [...] CTA"* — KHÔNG dùng chữ
   "Agitate" ở đâu cả. "Problem-Agitate-Solve" là cách gọi PAS phổ biến bên ngoài tài liệu gốc, không
   sai về mặt marketing chuẩn nhưng không phải trích dẫn `SKILL_v2.md` — nêu rõ để không nhầm là lỗi
   đọc tài liệu.

Các dòng còn lại (Promotion/AIDA, Introduction-Awareness/Hook-Insight-CTA, Trust-building/FAB,
Engagement/BAB, Event Announcement/5W1H+AIDA, Product-Service Explanation/FAB) khớp sát nguyên văn
cả `logic` lẫn `Marketing term` với `SKILL_v2.md`, không có sai khác đáng kể.

### 1b. Bảng 2 = `Channel Output Structures.xlsx` (đã tìm thấy AA-439-07 §A3, giờ mới trích đủ 7
kênh × 4 cột) — KHÔNG PHẢI `SKILL_v2.md`'s "Channel Rules" section

`SKILL_v2.md:256-298` ("## Channel Rules") có 1 mục riêng cho từng kênh, nhưng CHỈ 2-3 câu văn xuôi
mỗi kênh (VD LinkedIn: *"Use professional, thoughtful, insight-led writing. Avoid hype, clickbait,
cheap urgency, and fake vulnerability. Best for thought leadership..."*) — KHÔNG có cấu trúc 4 cột
(Dùng khi/Structure/Style/Tránh), KHÔNG có danh sách cliché cụ thể nào.

Bảng 2 Nghiệp đưa khớp **chính xác** với `Channel Output Structures.xlsx` mà AA-439-07 đã dump —
bằng chứng trực tiếp: cột "Tránh" của LinkedIn trong Bảng 2 liệt kê nguyên văn *"hidden gem",
"bucket list", "paradise awaits"* — đúng 3/4 cụm từ AA-439-07 §A3 đã trích từ cột `avoid` thật của
file xlsx (*"'hidden gem,' 'bucket list,' 'once-in-a-lifetime,' or 'paradise awaits'"*, thiếu đúng
1 cụm "once-in-a-lifetime" so với bản gốc — có thể do rút gọn khi soạn Bảng 2, không phải sai khác
về nguồn). Cấu trúc "Hook→...→CTA" theo bước cũng khớp bản chất 4-cột `description|structure|
style|avoid` mà AA-439-07 đã xác nhận file xlsx có, SKILL_v2.md hoàn toàn không có mức chi tiết
này. **Kết luận: Bảng 2 = `Channel Output Structures.xlsx`, không phải bản mới, không mâu thuẫn gì
với `SKILL_v2.md` — chỉ là 1 nguồn chi tiết hơn mà `SKILL_v2.md` tự nó không có.**

**Thay đổi phạm vi so với round 1 của chính task này**: STEP0 round 1 (đã lưu trong `AA-447-01`,
trích lại ở AA-439-00-SUMMARY) từng ghi *"`Channel Output Structures.xlsx` [...] chưa port, T9 cần
đọc trực tiếp"* — coi đây là input của **T9**, không phải T8. Nhưng workflow chốt lần này (bước 4
task, field "Best final style" trong 4-field angle) đòi hỏi T8 **tự tra Bảng 2 theo channel đã biết
từ bước 1** để điền field "Best final style" cho mỗi angle — nghĩa là **Bảng 2 giờ là input CẢ T8
lẫn T9**, không chỉ T9. Ghi nhận đây là mở rộng phạm vi thật so với hiểu biết trước đó, không phải
lỗi của round 1 (ADR mục 7 nói xlsx map vào "T8 + T9" — round 1 đọc chưa đủ kỹ chỗ này).

## 2. Định nghĩa "Angle" — 2 TẦNG khác nhau, cần Nghiệp thống nhất tên trước khi build

Đây là phát hiện quan trọng nhất của round 2. Đối chiếu chữ dùng trong chính task:

> "2. Hiện danh sách 'goal' (= chính là 'Angle' ở bảng 1, cột `Name`) để chọn."

So với `SKILL_v2.md` — nơi "Angle" và "Goal" là **2 khái niệm tách biệt hoàn toàn, không đồng
nghĩa**:
- **Goal** (`SKILL_v2.md:43-59`, "## Goal Selection List") = 1 trong 9 mục tiêu nội dung (Promotion,
  Lead Generation, ...) — đây chính xác là điều Bảng 1's cột `Name` liệt kê.
- **Angle** (`SKILL_v2.md:228-252`, "## Angle Selection Output") = 1 trong **3 góc kể chuyện cụ thể,
  do LLM SINH RA sau khi đã biết goal**, mỗi angle có `{Angle name, Why it works, Best final
  style}` — ĐÂY mới là thứ workflow's bước 5-7 (sinh 3 angle → recommend → chờ chọn) đang nói tới.

**Tức là:** "Angle" trong tên "Bảng 1 — Angle" (task lần này) = "Goal" theo đúng vocabulary
`SKILL_v2.md`. Còn "angle" ở bước 5-8 của workflow (3 cái, có Name/Why it works/Formula fit/Best
final style, chờ tenant chọn) = "Angle" đúng nghĩa `SKILL_v2.md`. **2 tầng này KHÔNG PHẢI cùng 1
khái niệm dùng lại tên khác nhau — chúng là 2 bước liên tiếp trong cùng pipeline (chọn Goal → rồi
mới sinh 3 Angle), nhưng đang bị gọi trùng tên "Angle" trong task.**

Không tự đổi tên thay Nghiệp — chỉ nêu rõ để tránh nhầm khi đặt tên schema/route/endpoint: nếu build
đúng theo `SKILL_v2.md`'s vocabulary, Bảng 1 nên được gọi là **Goal table** (hoặc "content goal"),
để chữ "Angle" chỉ dành riêng cho 3-cái-sinh-ra-ở-bước-5. Nếu Nghiệp muốn giữ đúng cách gọi trong
task (Bảng 1 = "Angle", 3-cái-ở-bước-5 = 1 tên khác, VD "Content Angle"/"Story Angle"), cũng được —
chỉ cần CHỌN 1 cách và áp dụng nhất quán cho tên bảng DB/route/field, tránh 2 khái niệm cùng tên
"angle" xuất hiện trong cùng 1 schema (dễ gây lỗi khi build/đọc code sau này).

## 3. Vai trò Angle Gate — "chờ người chọn", KHÔNG phải AA duyệt (đã chốt qua cả workflow lẫn ADR)

Workflow bước 7 tự xác nhận đúng cơ chế ADR đã quyết: **"Gate" = chờ TENANT chọn 1/3, không phải
AA duyệt** — khớp hoàn toàn với ADR §10.3 (21/08) đã trích ở round 1 (*"T8 (Angle Gate) [...] Sau
(21/08): Tenant tự duyệt hoàn toàn — không còn Trang/AA duyệt hộ trước publish"*) và §0.2 nguyên
tắc chung ("AA không gác cổng nội dung tenant"). Round 2 không cần điều tra lại phần này — chỉ xác
nhận workflow Nghiệp đưa KHỚP với ADR, không mâu thuẫn.

Điểm mới round 2 cần bổ sung: ADR §0.5 còn nói thêm Trust Ramp (Gate C) sẽ dùng để **"train mô hình
chọn angle"** — nghĩa là về lâu dài, hệ thống học từ lựa chọn của tenant để dần graduate sang
auto-pick (không hỏi tenant mỗi lần nữa). Điều này không mâu thuẫn workflow 9 bước Nghiệp đưa (vẫn
đúng "chờ người chọn" ở giai đoạn đầu) — chỉ là 1 lớp TỰ ĐỘNG HOÁ DẦN nằm bên ngoài 9 bước, không
cần build ngay ở lần đầu tiên. Xem câu hỏi mở §7.4 cho phần chưa trả lời được (ngưỡng graduate cụ
thể).

## 4. "Chờ người chọn" — cơ chế kỹ thuật: người là ai, lưu ở đâu, có timeout không

**Người chọn là TENANT thật (không phải AI đóng vai)** — xác nhận bằng 2 nguồn độc lập: (a) ADR
§10.3/§0.2 nói rõ "tenant tự duyệt", (b) **toàn bộ pattern self-service T0-T7 đã build** (mọi router
`v1_*` ở `api/routers/v1_planning.py`/`v1_tours.py`/`v1_marketplace.py` đều dùng `Depends(get_tenant)`
— tenant JWT thật, không có đường admin nào) — T8 build theo đúng pattern này thì "người chọn" chắc
chắn là tenant qua UI thật, không phải 1 LLM call khác giả lập "human".

**Lưu trạng thái "đang chờ chọn" ở đâu — chưa có bảng nào sẵn cho T8, nhưng có 1 SHAPE tiền lệ đáng
tham khảo (không phải code, chỉ là cấu trúc cột):** bảng cũ `acp_silver_s4.social_content` (migration
019 + 067, `acp_s4_social` — đã LOẠI theo quyết định ADR, không dùng code, nhưng schema SHAPE của nó
đáng nhìn qua):

```sql
-- migration 067, cột angles_json trên acp_silver_s4.social_content:
-- Shape: {"angle_1":{...},"angle_2":{...},"angle_3":{...},"selected_index":N}
-- NULL khi auto mode hoặc row cũ trước migration này
```

Cùng bảng đó còn có `hitl_gate_3_social_status TEXT CHECK (...'pending','approved','rejected')` làm
trạng thái chờ. **Đây là 1 SHAPE có thể tham khảo cho 1 bảng T8 MỚI** (không phải tái dùng bảng cũ,
đúng quyết định ADR §0.5 "viết mới hoàn toàn") — VD 1 cột JSONB `{angle_1, angle_2, angle_3,
selected_index}` + 1 cột status (`pending_selection`/`selected`) trên bảng T8 mới, tên khác, scoped
theo tenant_id.

**Timeout — KHÔNG có tiền lệ nào ở bất kỳ nguồn nào đã đọc.** Đã kiểm tra 3 nơi: (1) `SKILL_v2.md`
— toàn bộ tài liệu là 1 skill hội thoại đồng bộ (LLM hỏi, người trả lời ngay trong cùng phiên chat),
không có khái niệm "chờ" kéo dài qua thời gian nên không cần timeout; (2) `acp_s4_social` (migration
019/067) — không có cột `expires_at`/`selection_deadline` nào; (3) `trust_ramp.py`'s
`VETO_WINDOW_HOURS=48` (đã audit AA-439-06/07) — đây là timeout cho 1 cơ chế KHÁC (veto window sau
khi publish), không phải cho "chờ chọn angle". **Kết luận: đây là câu hỏi mở THẬT, không có nguồn
nào trả lời — không tự đặt số** (xem §7.2).

## 5. Channel là input có sẵn từ T7 — xác nhận bằng code, kèm 1 gap thật cụ thể

Workflow bước 1 xác nhận "channel là input đã biết trước khi vào T8, T8 không tự chọn kênh". Đọc
code T7 thật (`origin/main`, không đoán) xác nhận: **ĐÚNG, `compute_slot_grid()`
(`services/acp_planning/allocator.py:121-...`) đã sinh sẵn `channel` cho MỖI slot**, trích nguyên
văn logic gán channel:

```python
def make_slot(kind: str, trip_id: Optional[UUID]) -> Optional[Slot]:
    nonlocal slot_n
    week = weeks[slot_n % len(weeks)]
    channel = channels[slot_n % len(channels)]   # round-robin qua config.channels
    slot_n += 1
    ...
```

`channels` ở đây = `TenantPlanningConfig.channels` (`services/acp_planning/tenant_config.py`), đọc
từ `acp_shared.tenant_config.channels` (migration 101) — **1 danh sách text KHÔNG có CHECK
constraint nào ở tầng DB**, mặc định `["blog"]` nếu tenant chưa cấu hình.

**Trả lời câu hỏi "1 slot có tự nhân ra N kênh không":** KHÔNG — mỗi `Slot` chỉ có **đúng 1 giá trị
`channel`** (không phải list). Nếu tenant muốn cùng 1 tuần có content cho cả Facebook lẫn Instagram,
cơ chế round-robin ở trên sẽ tự tạo ra 2 `Slot` row riêng biệt (2 lần gọi `make_slot()`, mỗi lần lấy
1 channel khác nhau theo thứ tự trong `channels` list) — **miễn là tenant đã cấu hình `channels` gồm
>1 giá trị**. Mặc định chỉ có `["blog"]` — 1 tenant chưa từng vào "Tenant Config > Planning" để thêm
kênh sẽ chỉ có slot `channel="blog"` mãi mãi, không tự có Facebook/Instagram.

**Gap thật, có bằng chứng code cụ thể (không suy đoán):** `Slot.channel`'s type Pydantic là
`Channel = Literal["blog", "facebook", "tiktok", "email"]` (`services/acp_planning/models.py:19`) —
**chỉ 4 giá trị**, trong khi Bảng 2 có **7 kênh** (LinkedIn, Facebook, Instagram, TikTok, Email/
Newsletter, Landing Page/Sales Page, Ads). Vì `tenant_config.channels` ở tầng DB là text tự do,
KHÔNG có gì chặn 1 tenant tự cấu hình `channels=["linkedin"]` — nhưng khi `compute_slot_grid()` gọi
`Slot(channel="linkedin", ...)`, **Pydantic sẽ raise `ValidationError` ngay lập tức** vì "linkedin"
không nằm trong `Literal` 4 giá trị — đây là 1 lỗi thật sẽ xảy ra ở tầng T7 (không phải T8) nếu
tenant cấu hình kênh ngoài 4 giá trị đó, KHÔNG PHẢI lý thuyết. Đối chiếu 2 danh sách:

| Slot.Channel (T7, 4 giá trị) | Bảng 2 (7 kênh) | Khớp? |
|---|---|---|
| `blog` | — (không có dòng "Blog" trong Bảng 2) | ❌ không có structure/style/avoid cho blog trong Bảng 2 |
| `facebook` | Facebook | ✅ |
| `tiktok` | TikTok | ✅ |
| `email` | Email / Newsletter | ✅ (tên gần khớp) |
| — | LinkedIn | ❌ T7 chưa hỗ trợ |
| — | Instagram | ❌ T7 chưa hỗ trợ |
| — | Landing Page / Sales Page | ❌ T7 chưa hỗ trợ |
| — | Ads | ❌ T7 chưa hỗ trợ |

Không thuộc phạm vi "chỉ viết T8" để tự sửa `Slot.Channel`'s Literal (đụng lại T7) — ghi nhận là gap
cần quyết định trước khi build field "Best final style" cho các angle thuộc 4/7 kênh chưa hỗ trợ
(§7.3).

## 6. "Fixed brand audience" — nguồn dữ liệu ĐÃ CÓ, nhưng chưa được expose qua API tenant-facing nào

Tìm thấy nguồn thật, không phải giá trị tĩnh mới cần định nghĩa: **`shared.tenant_brand_rules`**
(migration 018, ticket AA-85; mở rộng migration 019, ticket AA-82) đã có sẵn đúng 4 cột mô tả
"audience cố định của brand":

```sql
ALTER TABLE shared.tenant_brand_rules
    ADD COLUMN IF NOT EXISTS brand_type        TEXT,
    ADD COLUMN IF NOT EXISTS core_idea         TEXT,
    ADD COLUMN IF NOT EXISTS customer_segment  TEXT,   -- ← chính là "audience"
    ADD COLUMN IF NOT EXISTS customer_mindset  TEXT,
    ...
```

Ví dụ dữ liệu thật đã seed (migration 018, tenant `atlas-hearth`): `customer_segment` = *"Senior
executives, private wealth, cultural philanthropists aged 45-65"*, `customer_mindset` = *"They have
seen the obvious destinations. They seek depth over access, meaning over spectacle..."* — đây CHÍNH
XÁC là "fixed brand audience" workflow bước 3 muốn tự động áp dụng, **theo TỪNG TENANT** (không phải
1 giá trị tĩnh chung cho toàn AA — mỗi tenant có `customer_segment` riêng, gán từ lúc T0 Brand Setup,
qua `acp_brand_brief_parser` khi tenant upload brand-guide docx, hoặc seed tay).

**Nhưng — gap thật cần biết trước khi build:** `customer_segment`/`customer_mindset`/`core_idea`/
`brand_type` **KHÔNG xuất hiện trong response của endpoint tenant-facing hiện có**
(`GET /api/tenant/admin/brand-identity`, đọc `BrandTab.tsx:29-32`'s `BrandData` interface — chỉ có
`system_prompt, style_guide, forbidden_words, version, updated_at`). Dữ liệu audience CÓ tồn tại
trong DB nhưng đang chỉ được **bake thành văn xuôi bên trong `system_prompt`** (xem migration 018's
`system_prompt` mẫu: *"Target market: [...] Customer mindset: [...]"* viết liền trong 1 đoạn văn
dài) — không tách rời thành field JSON sạch nào mà T8 có thể query trực tiếp qua API hiện có.

**2 hướng khả dĩ cho T8 (liệt kê, không tự chọn thay):**
- (a) T8 tự query trực tiếp `shared.tenant_brand_rules.customer_segment`/`customer_mindset` từ DB
  (cột đã có sẵn, không cần migration mới) — sạch, có structured field riêng cho "audience".
- (b) T8 tái dùng nguyên `system_prompt` đầy đủ (giống cách T2 rewrite engine đang dùng) — thô hơn
  (gồm cả tone/style/forbidden words trộn chung), nhưng không cần thêm code đọc field mới.

## 7. Câu hỏi mở còn thật sự treo (không lặp lại câu đã có đáp án)

1. **Tên gọi "Angle" ở 2 tầng (§2)** — Bảng 1's "Angle" = Goal theo `SKILL_v2.md`; 3-cái-sinh-ra-ở-
   bước-5 mới là "Angle" đúng nghĩa `SKILL_v2.md`. Cần Nghiệp chọn 1 cách gọi nhất quán trước khi
   đặt tên bảng DB/route/response field.
2. **Timeout cho "đang chờ chọn"** (§4) — không có nguồn nào (SKILL_v2.md/acp_s4_social/trust_ramp)
   trả lời. Cần Nghiệp quyết định có cần timeout không, và nếu có thì bao lâu.
3. **4/7 kênh trong Bảng 2 chưa được T7 hỗ trợ** (§5: LinkedIn, Instagram, Landing Page/Sales Page,
   Ads) — field "Best final style" của angle sẽ trống/không tra được cho các kênh này cho tới khi
   `Slot.Channel`'s Literal (T7) được mở rộng — đụng T7, ngoài phạm vi "chỉ viết T8".
4. **Ngưỡng cụ thể để Trust Ramp "graduate" cho T8** (§3, ADR §5 chỉ nói "track record đủ tốt",
   không có số) — có dùng chung điều kiện `weeks_active>=2 AND engagement_ok` của
   `trust_ramp.py::suggest_ramp_transition()` (vốn thiết kế cho packet cấp tuần) hay cần điều kiện
   riêng cho T8 (VD theo số lần tenant đã tự chọn angle)?
5. **"Formula fit" — tất cả 3 angle của cùng 1 lần sinh có cùng giá trị không?** Workflow bước 4 chọn
   1 công thức duy nhất theo goal đã chọn, RỒI bước 5 mới sinh 3 angle "áp dụng công thức đã chọn
   theo cách khác nhau" — nghĩa là cả 3 angle cùng 1 lần generate nhiều khả năng sẽ có "Formula fit"
   GIỐNG HỆT nhau (trừ khi goal đó có 2 công thức khả dĩ, VD Lead Generation = "AIDA hoặc PAS", và hệ
   thống chọn ngẫu nhiên/khác nhau giữa 3 angle). Field này có ý nghĩa phân biệt 3 angle hay chỉ là
   nhãn lặp lại cho biết công thức đã dùng? Chưa có nguồn nào trả lời rõ, cần Nghiệp xác nhận trước
   build (đúng tinh thần ADR §0.5 đã tự flag field này là quyết định MỚI, chưa từng có trong nguồn
   gốc).
6. **Ranh giới T8 kết thúc / T9 bắt đầu ở đâu — CÓ THỂ trả lời từ ADR đã có, nêu lại cho rõ (không
   phải câu hỏi mở mới):** ADR mục 4 (PRD Tenant Tier, đã trích round 1) đã tách rõ 3 stage liên
   tiếp: **T8** = "Angle Generation + Selection Gate" (output: "1 angle duyệt" — dừng lại đây, CHƯA
   viết content), **T9** = "Final Content Write" (input: "Angle đã duyệt", output: "Draft content
   theo kênh" — đây là bước 8 của workflow), **T10** = "Quality/Editor Pass" (đây là bước 9 của
   workflow). Vậy: **bước 8-9 của workflow 9 bước KHÔNG thuộc T8** — đã có câu trả lời từ ADR, không
   còn là câu hỏi mở, chỉ nhắc lại cho rõ vì task round 2 hỏi lại điểm này.

## 8. Route/tên T8 (không đổi so với round 1, xác nhận lại theo convention thật)

`Sidebar.tsx` (`origin/main`) xác nhận convention `/portal/t{N}-{slug ngắn}`: `t0-brand`,
`t1-rewrite`, `t4-pool`, `t6-atoms`, `t7-planning`. Đề xuất T8: **`/portal/t8-angles`** — dùng tên
số nhiều ngắn gọn, không dùng "gate" trong route/label tenant-facing (đúng tinh thần §0.2 — AA
không "gate" nội dung tenant, chữ "Gate" chỉ có nghĩa nội bộ/ADR). Label sidebar đề xuất: **"Angle
Selection"**.

**Lưu ý đặt tên do phát hiện §2**: nếu Nghiệp quyết định gọi Bảng-1-level là "Goal" thay vì "Angle"
(để tránh trùng tên), route/label này vẫn giữ nguyên đúng — `t8-angles` chỉ áp dụng cho tầng
3-cái-sinh-ra-ở-bước-5 (angle đúng nghĩa), không đổi.

## Tổng kết

| Câu hỏi | Trả lời |
|---|---|
| Bảng 1/2 có khớp `SKILL_v2.md` không? | Có — Bảng 1 = merge `SKILL_v2.md` (logic) + `writing formulars.xlsx` (term), Bảng 2 = `Channel Output Structures.xlsx` (không phải `SKILL_v2.md`'s Channel Rules, vốn chỉ có văn xuôi 2 câu/kênh). 2 sai khác nhỏ đã nêu (§1a): header "7 loại" vs 8 dòng thật; SLAP's "Purchase" vs nguồn "Proceed" |
| "Angle" nghĩa là gì? | **2 tầng khác nhau đang bị gọi trùng tên** — Bảng 1's "Angle" = Goal (`SKILL_v2.md` vocabulary); 3-cái-sinh-ở-bước-5 mới là Angle thật (Name/Why it works/Best final style, `SKILL_v2.md:228-252`) |
| Ai gate nó? | Tenant tự chọn (đã chốt, khớp ADR §0.2/§10.3) — không phải AA |
| Người chọn lưu ở đâu, có timeout? | Chưa có bảng — có 1 SHAPE tiền lệ tham khảo được (`angles_json` cột JSONB, cũ, không tái dùng code); **timeout KHÔNG có tiền lệ nào**, câu hỏi mở thật |
| Channel có sẵn từ T7 chưa? | Có — `Slot.channel` đã sinh sẵn theo round-robin qua `tenant_config.channels`, 1 slot = đúng 1 channel; nhưng chỉ hỗ trợ 4/7 giá trị so với Bảng 2 — gap thật, có code cụ thể |
| "Fixed brand audience" ở đâu? | `shared.tenant_brand_rules.customer_segment`/`customer_mindset` — đã có, theo TỪNG TENANT, nhưng chưa expose qua API tenant-facing hiện có (chỉ bake vào `system_prompt`) |
| Ranh giới T8/T9? | Đã có sẵn từ ADR mục 4 — T8 dừng ở "1 angle duyệt", T9 mới viết content, T10 mới QA pass |
| Câu hỏi mở còn treo | (1) tên gọi "Angle" 2 tầng, (2) timeout, (3) 4/7 kênh Bảng 2 chưa hỗ trợ ở T7, (4) ngưỡng Trust Ramp graduate, (5) "Formula fit" có phân biệt 3 angle hay lặp lại |

## Explicitly out of scope — không làm trong task này

- Không thiết kế thuật toán/threshold Trust Ramp cụ thể cho T8 (câu hỏi mở #4).
- Không sửa `Slot.Channel`'s Literal để thêm 4 kênh còn thiếu (câu hỏi mở #3) — đụng T7.
- Không tự chọn hướng (a)/(b) cho nguồn "fixed brand audience" (§6) hay tự đổi tên "Angle"/"Goal"
  (§2) thay Nghiệp.
- Không build bất kỳ route/endpoint nào — `/portal/t8-angles` (§8) chỉ là gợi ý tên, cần Nghiệp xác
  nhận trước khi tạo task build riêng (tương tự AA-448 đã làm cho T7).
