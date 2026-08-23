# AA-449-00 — STEP0: T8 Angle Gate viết mới hoàn toàn — investigation

Investigate only, không sửa code. Worktree `../aa-449-worktree`, branch
`docs/aa-449-00-step0-t8-angle-gate-investigation`. Nguồn: `SKILL_v2.md` gốc (đọc toàn bộ 366
dòng), `docs/claude_audit/AA-439-06-t7-t8-audit.md` + `AA-439-07-s4social-workflow-comparison.md`
(đã audit T7→T8 và so sánh `acp_s4_social` với nguồn gốc trước đây — không lặp lại việc đã làm,
chỉ trích dẫn), `docs/claude_audit/AA-447-01-sync-audit-matrix.md` (worktree `aa-447-worktree`),
code T7 thật trên `origin/main` (`ad90d07`/`bbb2871`/`7cf3b7b`, đã merge), và **ADR-2026-038 đọc
trực tiếp từ Notion** (page "🔴 [21/08/2026] Content Pipeline Redesign", KHÔNG tồn tại dưới dạng
file trong 4 repo — điểm này AA-439-00-SUMMARY và AA-438-00-SUMMARY từng ghi là "cần Notion/Linear
lookup ngoài môi trường này"; phiên này có quyền truy cập Notion nên đọc được toàn văn, bản mới
nhất tính đến 22/08/2026).

**Headline: ADR-2026-038 KHÔNG im lặng về T8 — nó có 2 phần nói trực tiếp về Angle Gate (§0.5,
22/08, MỚI NHẤT — sau cả AA-439-06/07) và §4/§5/§10.3 (21/08). Đây là phát hiện quan trọng nhất
của investigation này: các audit trước (AA-439-06, chốt 22/08 sáng; AA-439-00-SUMMARY) coi "ADR có
nói gì về T8 không" là câu hỏi mở — nhưng ADR đã được cập nhật (§0.5) CÙNG NGÀY 22/08, sau khi
AA-439-06/07 chạy, với quyết định cụ thể: (1) viết lại hoàn toàn T8, không dùng `acp_s4_social`;
(2) tham khảo không copy `SKILL_v2.md`, giữ đúng 3 trường angle (Name/Why it works/Best final
style), "formula fit" là trường MỚI cần Nghiệp xác nhận ý nghĩa; (3) 8 goal chính thức (bỏ
Partner/supplier); (4) Trust Ramp (Gate C) GIỮ LẠI làm cơ chế tự động hoá dần, KHÔNG phải content
gate. Task này không cần đặt lại câu hỏi "ADR có nói gì về T8" như 1 khoảng trống — nó đã có câu
trả lời, chỉ còn 1 câu hỏi thật sự mở (§6 bên dưới: "formula fit" nghĩa là gì).**

---

## 1. Định nghĩa "Angle" theo `SKILL_v2.md` gốc — trích nguyên văn

`SKILL_v2.md` không có phần định nghĩa tường minh 1 câu "Angle = ...", nhưng nghĩa được xác lập rõ
qua cách nó được dùng xuyên suốt tài liệu:

**Angle = 1 trong 3 hướng tiếp cận chiến lược cho 1 NỘI DUNG CỤ THỂ** (không phải 1 atom, không
phải 1 destination) — chọn theo brand + audience + channel + goal + CTA đã thu thập trước đó
(`SKILL_v2.md:19-41`, "Required Human Inputs"). Định nghĩa gần nhất với 1 câu tóm tắt, trích
nguyên văn từ mục "Content Seed Handling" (`SKILL_v2.md:196-208`):

> "5. Generate 3 angles shaped by the selected goal and CTA."

Và mục "Human-In-The-Loop Workflow", bước 6 (`SKILL_v2.md:219`):

> "6. Create 3 content angles shaped by brand, audience, channel, goal, and CTA."

**Định dạng output angle**, trích nguyên văn `SKILL_v2.md:228-252` ("## Angle Selection Output") —
đúng 3 trường mỗi angle, không hơn:

```md
1. {Angle name}
Why it works: {short business reason}
Best final style: {short / detailed / persuasive / founder-led / visual / conversion-led}
```

**Kết luận về ngữ nghĩa "angle" trong ví dụ Nghiệp nêu ở task ("gia đình" vs "phiêu lưu" vs "sang
trọng"):** đúng hướng nhưng cần chính xác hơn — angle không phải 1 nhãn cố định cho 1 destination,
mà là 1 trong 3 GÓC KỂ CHUYỆN được LLM sinh ra RIÊNG cho từng content piece (mỗi lần chạy sinh 3
angle mới, không phải chọn từ 1 danh sách cố định trước) — tương tự việc `services/acp_s4_social/
angles.py::generate_angles()` (đã audit AA-439-06/07, không lặp lại chi tiết ở đây) sinh ra
`{name, why_it_works, style_signal}` theo LLM call thật, không phải tra bảng tĩnh.

**Phân biệt quan trọng — "angle" này KHÁC với `assigned_angle` (N1 onboarding, AA-309)** — xem §4.

## 2. Vai trò Angle Gate trong chuỗi — theo ADR §4/§5, KHÔNG chỉ theo `SKILL_v2.md`

`SKILL_v2.md` tự nó không có khái niệm "gate" — nó là 1 content skill nói chung (LinkedIn/FB/
email/ads, không riêng gì pipeline ACP), quy trình HITL của nó (bước 7-8, `SKILL_v2.md:221-222`)
đơn thuần là "recommend 1 angle → chờ người chọn", không có khái niệm "trust ramp"/"tự động hoá
dần" nào. **Khái niệm "gate" (T8 = Angle Generation **+ Selection Gate**) là do ADR-2026-038 thêm
vào khi map workflow này vào kiến trúc T-series** — trích nguyên văn bảng PRD Tenant Tier
(mục 4 của ADR):

| Mã | Tên stage | Input | Xử lý | Output |
|---|---|---|---|---|
| **T8** | Angle Generation + Selection Gate | Kế hoạch T7 (channel + goal) | 1) Goal list → 2) brand audience → 3) formula theo goal → 4) sinh 3 angle → 5) recommend → 6) người chọn (dual-mode) | 1 angle duyệt |

Và mục 5 của ADR, "T8 — Angle Gate dual-mode" (trích nguyên văn):

> "Dùng lại nguyên cơ chế Gate C 'trust ramp' đã Accepted (ADR-2026-026/036) — mandatory review
> lúc đầu, graduate sang auto-approve khi track record đủ tốt (dùng để train mô hình chọn angle,
> đúng ý Nghiệp). Không thiết kế thuật toán agreement-rate riêng."

**Ai/cơ chế nào gate nó — câu trả lời đã chốt, KHÔNG phải "AA duyệt":**

Bảng §10.3 của ADR (21/08) từng viết T8 = "Trang review + veto 48h (Gate C)" (kế thừa nguyên bản
`aamc`) rồi đổi ngay trong cùng mục thành:

> "T8 (Angle Gate) | Trước (ADR-2026-026/028): 'Không bao giờ thấy gates', Trang review + veto 48h
> (Gate C) | Sau (21/08): **Tenant tự duyệt hoàn toàn — không còn Trang/AA duyệt hộ trước
> publish**"

Rồi §0.5 (22/08, **bản mới nhất, sau AA-439-06/07**) làm rõ thêm — Trust Ramp (Gate C) không bị
xoá, mà đổi vai trò:

> "Trust Ramp (Gate C, `trust_ramp.py`) — GIữ LẠI, sửa cho tự động thật: [...] Vai trò đúng của
> trust ramp: cơ chế AN TOÀN cho tenant MỚI, KHÔNG phải content gate — không mâu thuẫn §0.2 vì bản
> chất khác nhau: §0.2 nói AA không duyệt NỘI DUNG tenant, còn trust ramp là về AI được phép TỰ
> XUẤT BẢN ngay hay cần thời gian 'thử việc' trước — giống thời gian giữ tiền của merchant mới ở
> cổng thanh toán, không phải kiểm duyệt."

**Tổng hợp, không suy diễn thêm:** người chọn 1 trong 3 angle là **TENANT** (self-service, đúng
nguyên tắc §0.2 "AA không gác cổng nội dung tenant"), KHÔNG phải AA/Trang/Ms. Thư. "Gate" trong
tên T8 không có nghĩa AA duyệt — nó có 2 lớp: (a) **dual-mode structural gate** (guided mode dừng
lại chờ tenant chọn 1/3 angle trước khi viết content thật — giống hệt cơ chế `run_guided_angles()`
→ chờ → `run_guided_write()` đã có ở `acp_s4_social`, chỉ đổi người chọn từ admin sang tenant), và
(b) **Trust Ramp là lớp "khi nào tenant được TỰ ĐỘNG bỏ qua bước chọn tay"** — mandatory guided
review lúc tenant mới, dần graduate sang auto (LLM tự chọn 1/3, như `mode="auto"` đã có sẵn trong
`acp_s4_social/angles.py`) khi "track record đủ tốt" — con số/ngưỡng "đủ tốt" cụ thể **chưa được
ADR định nghĩa cho T8** (xem câu hỏi mở §6).

## 3. Input/Output Angle Gate theo thiết kế ADR + input thực tế từ code T7 đã build

**Theo ADR (mục 4):** Input = "Kế hoạch T7 (channel + goal)"; Output = "1 angle duyệt".

**Theo code T7 thật đã merge** (`origin/main`, `api/routers/v1_planning.py`,
`services/acp_planning/models.py` — đọc trực tiếp, không đoán theo mô tả issue, đúng yêu cầu mục
5 của task):

T8 sẽ đọc từ **`GET /v1/planning/slot-grid?year=&month=`** (`v1_planning.py:179-217`), gọi
`compute_slot_grid()` và trả về `{"slot_grid": SlotGrid.model_dump()}`. `SlotGrid`
(`services/acp_planning/models.py:148-154`): `tenant_id, year, month, slots: list[Slot],
capacity_note, trips_hash`. Mỗi `Slot` (`models.py:134-145`) — đây chính là "1 kế hoạch cho 1
content piece" mà T8 nhận làm input:

```python
class Slot(BaseModel):
    slot_id: str
    week: int
    channel: Channel          # Literal["blog", "facebook", "tiktok", "email"]
    kind: Literal["evergreen", "campaign", "reactive_hold"]
    trip_id: Optional[UUID] = None
    atom_ids: list[str] = Field(default_factory=list)
    funnel_stage: FunnelStage = "TOFU"   # Literal["TOFU","MOFU","BOFU","OFF"]
    framework: Optional[str] = None
    cta_target: Optional[str] = None
    topic_hint: Optional[str] = None
    keyword_seed: Optional[str] = None
```

**Phát hiện quan trọng — khoảng trống thật giữa mô tả ADR và schema thật:** ADR mô tả input T8 là
"channel + **goal**" nhưng `Slot` **không có trường `goal`** (chỉ có `channel`, `funnel_stage`,
`kind`, `cta_target`, `topic_hint`) — 1 trong 8 goal chính thức (Promotion/Lead Gen/Conversion/...)
**không tồn tại ở bất cứ đâu trong output T7 thật**. Đây không phải giả định — đã đọc toàn bộ
`models.py`, không có field nào tên `goal` trên `Slot`/`SlotGrid`/`QuarterPlan`/`TripScore`. Ghi
nhận là câu hỏi mở thật, không tự suy diễn cách map (§6).

`Slot.atom_ids` trỏ vào `acp_contract.tour_atoms` (owner_scope=tenant_id, theo Hướng B) —
đây là nguồn "brand voice/sự thật của tenant" mà angle phải phản ánh, đọc qua
`fetch_tenant_atoms_by_trip()` (đã có sẵn từ T7, `services/acp_planning/tenant_pool.py`).
`Slot.trip_id` trỏ `Trip` (`fetch_tenant_trips()`) — cho brand/destination context.
`tenant_brand_rules` (T0) cho brand/audience — đúng 2 trường bắt buộc `ContentBrief.brand`/
`.audience` mà `acp_s4_social/brief.py` đã validate (AA-439-07 §B2, không lặp lại).

**Output** (theo ADR: "1 angle duyệt") — chưa có schema thật vì T8 chưa build; đề xuất ở §7 dưới
đây là dựa trên `Slot` đã có + `SKILL_v2.md`'s 3-field format, không phải thiết kế mới ngoài
phạm vi investigate.

## 4. Gate A (N1 onboarding, AA-309) vs. Angle Gate (T8) — 2 khái niệm khác nhau, xác nhận bằng code thật

Grep tươi `git grep -ni "angle" -- 'services/*' 'api/routers/*'` trên `origin/main` (loại trừ
`acp_s4_social`, đã audit riêng AA-439-06 §2-3) tìm thấy đúng 1 nhóm khác dùng chữ "angle":
**`ASSIGNED_ANGLES`** (`api/routers/admin.py:49`, dùng bởi `PATCH /admin/tenants/{id}/angle`,
comment tại chỗ: *"N1 step 3 — assign the tenant's anti-cannibalization angle"*).

**Đây là 1 cơ chế hoàn toàn khác Angle Gate T8**, xác nhận trực tiếp từ code:
- **Cấp áp dụng: 1 LẦN/TENANT** (không phải 1 lần/content piece) — `assigned_angle` là 1 cột trên
  `acp_shared.tenant_atom_state`, gán lúc onboarding (N1), 7 giá trị cố định từ `ASSIGNED_ANGLES`
  dict (`admin.py:49`, ví dụ minh hoạ: culinary_people, physical_terrain — đã trích đủ ở
  AA-439-06 §1.2, không lặp lại toàn bộ 7 giá trị ở đây).
- **Mục đích: chống trùng lặp nội dung giữa NHIỀU TENANT cùng bán 1 tour** (anti-cannibalization
  narrative lens) — không phải chọn góc kể chuyện cho 1 bài viết cụ thể.
- **Gate A** (thuật ngữ CLAUDE.md dùng, khác `git grep` — xem `admin.py:416,421`: *"through Gate A
  (no seed-atoms, no assigned_angle, no approval)"*) = **toàn bộ điều kiện onboarding phải xong
  trước khi `shared.tenants.is_active` được bật thật** (`admin.py:1184-1220`, đòi hỏi
  `assigned_angle IS NOT NULL` như 1 trong các điều kiện, KHÔNG PHẢI bản thân Gate A = angle). Gate
  A là gate cho TOÀN BỘ quy trình N1 (seed atoms + angle + approval), `assigned_angle` chỉ là 1
  điều kiện con của nó.

**Kết luận: Gate A và Angle Gate (T8) dùng chữ "angle"/"gate" trùng ngẫu nhiên, KHÔNG phải cùng 1
cơ chế tái dùng.** Gate A chạy 1 lần lúc tenant mới tạo, output là 1 giá trị cố định gắn cho toàn
bộ tenant mãi mãi (trừ khi admin đổi tay). Angle Gate (T8) chạy nhiều lần, mỗi content piece 1 lần,
sinh 3 angle mới bằng LLM mỗi lần, do chính tenant chọn. Xác nhận thêm bằng chính ADR (§10.1,
đọc lại nguyên văn khi tra `tenant_atom_state`): *"`starred/usage_log/cooldown_until` 0 reader
trong code [...] Kết luận: `tenant_atom_state` trong thực tế chỉ sống với vai trò `assigned_angle`
(tour-level, đúng bản chất — angle là cách kể 1 tour, không phải thuộc tính từng atom)"* — ADR tự
gọi đây là "tour-level", đối lập trực tiếp với T8's "per content piece" angle.

## 5. `docs/claude_audit/AA-447-01-sync-audit-matrix.md` — trích đúng phần T8

Từ `aa-447-worktree` (branch `feature/aa-447-sync-audit-matrix`, đã merge lên remote nhưng chưa
merge `main` cục bộ ở thời điểm audit này — đọc trực tiếp file trên worktree). Dòng bảng T8
(nguyên văn):

> "**T8** Angle Generation + Selection Gate | ⚠️ Code thật, ĐẦY ĐỦ tồn tại
> (`acp_s4_social/angles.py`+`handler.py`+`formula.py`) NHƯNG **quyết định viết lại HOÀN TOÀN,
> không dùng code này** (ADR §0.5, 22/08) — 0 caller, 0 row `social_content`, ever | ❌ 0 — route
> cũ (`v1_s4_social.py`) 100% admin-secret-only, và **chính admin sidebar cũng ẩn nhóm ACP v1 này
> đi** (`AdminSidebar.tsx:241-244` comment "AA-390... hidden... reachable directly by URL if ever
> needed again") — kể cả admin cũng không tự thấy | ✅ `acp_silver_s4.social_content` table tồn
> tại nhưng 0 row | ❌ **CHƯA CÓ** (đúng nghĩa, kể cả code cũ cũng coi như không tồn tại theo quyết
> định) | AA-439-06/07 + ADR §0.5: build T-series mới từ đầu, tham khảo không copy. 8 goal đã chốt
> (bỏ goal thứ 9), `Channel Output Structures.xlsx` chưa port"

Và phần giải thích riêng (nguyên văn, mục "T8 — quyết định KHÔNG dùng code cũ"):

> "ADR §0.5 (22/08) rất rõ: viết lại hoàn toàn, không mượn `acp_s4_social`. Điều này thay đổi ý
> nghĩa của cột 'BE' trong bảng — code `acp_s4_social` 'tồn tại' theo nghĩa đen (files thật, chạy
> được) nhưng theo quyết định sản phẩm thì coi như KHÔNG dùng được cho T8 — vì vậy tôi xếp T8 vào
> ❌ CHƯA CÓ, không phải ⚠️ LỆCH TẦNG, dù về mặt code thuần tuý có nhiều hơn T7."

Và dòng headline của toàn bộ file: T8 là 1 trong 4 gap thật lớn ("T7 (0 FE dù BE có), **T8 (quyết
định viết lại từ đầu, chưa bắt đầu)**, T11 (BE chưa tồn tại)"). **Xác nhận: kể cả admin cũng không
còn thấy được route `acp_s4_social` cũ nữa** (ẩn khỏi `AdminSidebar.tsx`) — không chỉ tenant chưa
có route, mà route cũ giờ coi như đã chết hoàn toàn về mặt UX, chỉ còn tồn tại trên đĩa.

## 6. Câu hỏi mở — CẦN Nghiệp/Ms. Thư quyết định trước khi build, không tự suy diễn

1. **"Formula fit" — nghĩa cụ thể là gì?** ADR §0.5 điểm 2 tự xác nhận: *"KHÔNG có 'formula fit'
   trong nguồn gốc, nếu vẫn muốn thêm trường này thì đây là quyết định MỚI của Nghiệp [...] cần
   xác nhận lại ý nghĩa 'formula fit' cụ thể là gì trước khi build."* AA-439-07 §B4 (đọc lại xác
   nhận) cũng grep không thấy field này ở bất kỳ đâu trong `SKILL_v2.md`/`SKILL.md`(v1)/
   `acp_s4_social`. Đây là câu hỏi mở DUY NHẤT mà chính ADR tự nêu ra và chưa trả lời — không phải
   phát hiện mới của task này, chỉ xác nhận lại nó vẫn còn mở tính đến bản ADR mới nhất.

2. **"Goal" của mỗi slot đến từ đâu?** (Phát hiện mới của investigation này, §3) — `Slot` (T7 thật)
   không có trường `goal`, nhưng ADR mô tả input T8 là "channel + goal" và bước 2-3 của
   `SKILL_v2.md` ("Show 9-goal list" → "Human selects a goal") đòi hỏi 1 giá trị goal cụ thể
   trước khi sinh angle. 3 hướng khả dĩ (liệt kê, KHÔNG chọn thay):
   - (a) T8 tự map `funnel_stage`/`kind` có sẵn của Slot sang 1 trong 8 goal (VD: TOFU→
     Introduction/Awareness, BOFU→Conversion) — cần bảng mapping rõ ràng, chưa tồn tại ở đâu.
   - (b) Tenant tự chọn goal cho từng slot khi mở T8 (đúng bước 2-3 gốc của `SKILL_v2.md`, nhưng
     `acp_s4_social` cũ CŨNG chưa từng implement bước này như 1 round-trip riêng — AA-439-07 §B,
     dòng 3-4 — caller phải biết goal từ trước).
   - (c) T7 cần bổ sung `goal` vào `Slot` (đòi hỏi sửa lại T7 — ngoài phạm vi "chỉ viết T8", cần
     xác nhận có chấp nhận đụng lại T7 hay không).

3. **Ngưỡng "track record đủ tốt" để Trust Ramp graduate cho T8 cụ thể là gì?** ADR §5 nói dùng
   lại "nguyên cơ chế Gate C trust ramp" nhưng `trust_ramp.py::suggest_ramp_transition()`
   (đã audit AA-439-06 §4, `weeks_active >= 2 AND engagement_ok`) được thiết kế cho **publish
   packet cấp tuần** (`acp_deliver.packets`), không phải cho "tenant tự chọn angle cho 1 content
   piece". Áp dụng y nguyên điều kiện đó cho T8 (VD: sau bao nhiêu lần tenant tự chọn angle thì
   graduate sang auto?) chưa được ADR nói rõ số cụ thể — chỉ nói "dùng để train mô hình chọn
   angle". Cần Nghiệp/Ms. Thư xác nhận: dùng chung 1 trạng thái ramp cho cả T8 lẫn T11 (delivery),
   hay T8 cần ramp trạng thái riêng của chính nó?

4. **`Channel Output Structures.xlsx` (7 kênh) vs. `Slot.Channel` thật (4 giá trị: blog/facebook/
   tiktok/email)** — ADR mục 7 nói 9-bước + 2 file xlsx map vào **T8 + T9**, nhưng
   `Channel_Output_Structures.xlsx` có 7 kênh (thêm LinkedIn/Instagram/Landing Page/Ads) trong khi
   `Slot`'s `Channel` type hiện chỉ literal 4 giá trị. Không thuộc phạm vi build T8 riêng (đây là
   T9's input theo ADR), nhưng đáng ghi nhận vì ảnh hưởng "goal → formula → angle" ở T8 nếu channel
   mở rộng sau — flag để không phải điều tra lại từ đầu khi tới lượt T9.

## 7. Đề xuất route + cấu trúc endpoint (đề xuất, KHÔNG phải quyết định — task này không build)

**Route FE**, theo đúng convention `Sidebar.tsx` đang dùng (`/portal/t{N}-{slug-ngắn}`, đọc trực
tiếp từ `frontend/app/(tenant)/portal/_components/Sidebar.tsx` trên `origin/main`):

| Stage đã có | Route | Label |
|---|---|---|
| T0 | `/portal/t0-brand` | Brand Identity |
| T1 | `/portal/t1-rewrite` | Browse Pool |
| T4 | `/portal/t4-pool` | My Catalog |
| T6 | `/portal/t6-atoms` | Atom Curation |
| T7 | `/portal/t7-planning` | Content Planning |

Đề xuất T8: **`/portal/t8-angles`** (danh từ ngắn, khớp nhịp `t6-atoms`/`t1-rewrite`, không dùng
`angle-gate` — chữ "gate" chỉ có ý nghĩa nội bộ/ADR, không nên lộ ra route/label tenant-facing vì
chính nguyên tắc §0.2 nói AA không "gate" nội dung tenant). Label sidebar đề xuất: **"Angle
Selection"** (không dùng "Gate", tránh cảm giác approval-by-AA cho tenant — nhất quán với cách
T3/T6 đã đổi ngôn ngữ để không gây hiểu lầm "chờ duyệt", xem ADR §0.1).

**Endpoint BE**, theo đúng pattern router `v1_planning.py` (preview không persist / finalize có
persist) đã dùng cho T7 — chỉ là đề xuất hình dạng dựa trên tiền lệ đã có, không phải thiết kế đã
chốt:

- `POST /v1/angles/generate` — input: `slot_id` (trỏ vào `SlotGrid` đã có từ T7) + `goal` (khi câu
  hỏi mở #2 ở §6 được trả lời) → sinh 3 angle (LLM call thật, không persist) → trả về 3 angle +
  angle được recommend (angle[0]).
- `POST /v1/angles/select` — input: `slot_id` + `selected_angle` → persist 1 angle đã chọn, gate
  mở khoá cho T9 viết content thật.
- (Tuỳ theo câu trả lời câu hỏi mở #3) `GET /v1/angles/ramp-status` hoặc field lồng trong response
  `generate` — cho biết tenant hiện đang ở mandatory-review hay đã graduate auto-approve.

## Tổng kết

| Câu hỏi | Trả lời |
|---|---|
| "Angle" nghĩa là gì? | 1 trong 3 góc kể chuyện LLM sinh RIÊNG cho 1 content piece cụ thể (không phải nhãn cố định theo destination), gồm 3 trường: Name, Why it works, Best final style (`SKILL_v2.md:228-252`) |
| Angle Gate có vai trò gì? | Dừng pipeline giữa "sinh 3 angle" và "viết content thật" (T9), chờ 1 lựa chọn trước khi tiếp tục — cơ chế dual-mode (guided/auto) đã có tiền lệ ở `acp_s4_social` |
| Ai gate nó? | **Tenant tự duyệt** (không phải AA) — theo ADR §10.3 (21/08) + §0.2. Trust Ramp (Gate C) quyết định tenant có cần tự chọn tay hay được LLM tự chọn thay, KHÔNG phải AA duyệt nội dung |
| Input/Output theo ADR | Input: "Kế hoạch T7 (channel + goal)"; Output: "1 angle duyệt" |
| Input thật theo code T7 | `GET /v1/planning/slot-grid` → `SlotGrid.slots[]` (mỗi `Slot`: channel, trip_id, atom_ids, funnel_stage, kind, cta_target, topic_hint, keyword_seed — **KHÔNG có `goal`**, câu hỏi mở #2) |
| ADR có im lặng về T8 không? | **KHÔNG** — §0.5 (22/08) + §4/§5/§10.3 nói trực tiếp, chi tiết, mới hơn cả AA-439-06/07 |
| Gate A (AA-309) có phải Angle Gate T8 không? | **Không** — Gate A = điều kiện tổng thể bật `tenants.is_active` lúc onboarding; `assigned_angle` bên trong nó là 1 nhãn cố định/tenant (anti-cannibalization), khác hoàn toàn 3-angle/content-piece của T8 |
| Code cũ tham khảo được gì? | `acp_s4_social/angles.py`+`formula.py`+`handler.py` — đọc để hiểu shape (dual-mode, prompt structure), **KHÔNG copy file/import** theo quyết định ADR §0.5 |
| Câu hỏi mở lớn nhất | "Formula fit" nghĩa là gì (ADR tự nêu, chưa trả lời) + "goal" của mỗi slot lấy từ đâu (phát hiện mới, ADR/T7 chưa có chỗ chứa) |

## Explicitly out of scope — không làm trong task này

- Không thiết kế thuật toán chấm điểm/threshold Trust Ramp cụ thể cho T8 (câu hỏi mở #3).
- Không sửa `Slot` model để thêm `goal` (câu hỏi mở #2) — chỉ ghi nhận gap, không tự chọn hướng
  (a)/(b)/(c).
- Không đọc/port `Channel Output Structures.xlsx` — đó là input T9 theo ADR mục 7, không phải T8.
- Không build bất kỳ route/endpoint nào đề xuất ở §7 — chỉ là gợi ý hình dạng dựa trên tiền lệ
  `v1_planning.py`, cần Nghiệp xác nhận trước khi tạo task build riêng (tương tự AA-448 đã làm
  cho T7).
