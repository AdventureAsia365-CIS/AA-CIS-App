# AA-382 — repair_fn cần đủ rubric context cho gate LLM-judged (F8/F9)

Task: `docs/claude_tasks/AA-382-01-repair-rubric-context.md`. Branch
`feature/aa-382-repair-rubric-context`.

## STEP 0 — xác nhận giả thuyết bằng code thật + data thật

Giả thuyết gốc trong task ("repair chỉ nhận 1 câu violation ngắn, không có rubric gốc") là
**ĐÚNG MỘT PHẦN, cần điều chỉnh** sau khi đọc code thật:

- **F9 (blog + social)**: `brand_rubric_text` (toàn bộ rubric per-tenant) ĐÃ được đưa vào
  system prompt của repair từ AA-404 (`PieceInvariants.brand_rubric_text`,
  `_build_repair_system_prompt()`) — phần này KHÔNG còn là gap. Gap thật, đọc ra từ code +
  xác nhận bằng data thật (xem bên dưới), là 2 việc khác:
  1. `GENERIC_AI_WORDING_ANCHOR` (ví dụ good/bad cụ thể định nghĩa thế nào là
     GENERIC_AI_WORDING/SUMMARY_OFF_BRAND, gates.py, AA-404 fix #2) chỉ từng được đưa vào
     prompt của JUDGE (`gate_brand_seo_audit()`/`gate_brand_seo_audit_social()`), KHÔNG BAO
     GIỜ đưa vào prompt của REPAIR — repair phải đoán "generic" nghĩa là gì mà không có neo
     cụ thể.
  2. `flagged_phrases` — câu trích dẫn CHÍNH XÁC mà judge chỉ ra là vi phạm (đã có trong audit
     dict từ AA-404 PR #153 fix #3) **bị vứt bỏ hoàn toàn** trước khi tới repair —
     `_format_audit_reason()` chỉ format `failure_codes` + `notes` (một đoạn tóm tắt chung
     chung của judge), không bao giờ đưa `flagged_phrases` vào `violations` — kênh DUY NHẤT
     `repair_fn` thực sự đọc được (`run_gates()` gọi
     `repair_fn(piece.body_tagged, first_failure.violations)`).
- **F8 (framework judge)**: không có bất kỳ dạng "rubric context" nào tới repair cả — violation
  chỉ là `"framework criterion failed: {criterion}"` (3-6 từ, ví dụ `"one emotion"`), không có
  danh sách ĐẦY ĐỦ rubric của framework đó (`FRAMEWORK_RUBRICS`, gates.py), không có ví dụ, và
  `PieceInvariants` trước đây KHÔNG có field nào carry framework/rubric cả. Đây là gap
  "worse than the hypothesis" — chưa từng có bất kỳ rubric context nào, kể cả rubric gốc.

### Bằng chứng thật (query trực tiếp `acp_deliver.pieces`, không phải giả lập)

Trước khi sửa code, query 4 run N7 gần nhất (`acp_shared.acp_v2_runs`, tenant `aa_internal`)
qua S3-mediated ECS exec (read-only) để lấy baseline THẬT:

| Run (year/week) | n pieces | F8 pass | F9 pass |
|---|---:|---:|---:|
| `d776a047` (2026 W4) | 12 | 8/12 (66.7%) | **0/12 (0%)** |
| `363f22c9` (2026 W3) | 12 | 9/12 (75%) | **0/12 (0%)** |
| `d0722ae3` (2026 W2) | 9  | 8/9 (88.9%) | **0/9 (0%)** |
| `b4cc97ee` (2026 W1) | 12 | 9/12 (75%) | 2/12 (16.7%) |

F9 gần như KHÔNG BAO GIỜ pass — khớp chính xác với AA-415's report
(`docs/implementation-notes/AA-415-verify-real-run.md`: "F9 vẫn là moving target"). F8 pass
khá hơn (67-89%) nhưng vẫn có fail thật cần repair.

Query sâu hơn vào `acp_deliver.pieces.brand_seo_audit` (run `d776a047`, piece
`slot_f20e87cc...:blog#facebook`) xác nhận TRỰC TIẾP root cause #2 ở trên — judge THẬT SỰ trả
về `flagged_phrases` cụ thể mỗi round:

```
held_reason (những gì repair từng thấy):
  "F9_brand_seo_audit_social: audit flagged: SUMMARY_OFF_BRAND, GENERIC_AI_WORDING, HOOK_WEAK
  -- The piece contains several instances of generic AI wording and fails to meet the brand's
  specific requirements..."   ← KHÔNG có câu cụ thể nào

audit_flagged_phrases (những gì judge THỰC RA đã chỉ ra, nhưng bị vứt trước khi tới repair):
  - "Royal burial mounds from the Silla Kingdom appear in most Korea itineraries."
  - "The first evening in Seoul does not."
  - "The welcome dinner is a traditional Korean hot pot with noodle soup, shared around the
    table with the group — a central pot over heat, broth deepening as ingredients are added
    in sequence, the meal building rather than arriving."
  - ... (3 câu khác)
```

3 vòng repair trên CÙNG piece này (`slot_f20e87cc...`, cả `#facebook` và `#tiktok`) đều chỉ
nhận `notes` chung chung gần như GIỐNG HỆT nhau mỗi vòng ("contains generic AI wording...
lacking specific verifiable details...") — không có gì phân biệt vòng 1/2/3 để repair biết
NÊN sửa câu nào. Đây chính là cơ chế "3 vòng flag cụm từ khác nhau, không hội tụ" —
`flagged_phrases` tồn tại thật, judge cung cấp thật, nhưng bị bỏ phí hoàn toàn.

(Quan sát phụ, NGOÀI SCOPE task này: một số câu trong `flagged_phrases` — ví dụ "The riding
itself is the access — each day's distance is the means by which you get close to something
specific..." — đọc thực tế lại RẤT khớp tiêu chí GOOD của chính `GENERIC_AI_WORDING_ANCHOR`
(cụ thể, có chi tiết xác minh được, không sáo rỗng). Có khả năng judge (Nova Pro) tự nó
over-flag ngay cả văn bản đã đạt chuẩn — đây là vấn đề CALIBRATION của judge, không phải
INPUT của repair, nằm ngoài scope task này ("không đổi logic judge"). Ghi lại để Nghiệp cân
nhắc một issue riêng nếu muốn.)

## Changed

1. `services/acp_produce/gates.py`
   - `_format_audit_reason()` nhận thêm `flagged_phrases: Optional[list[str]] = None` (giữ
     nguyên chữ ký cũ cho caller không truyền — additive), nối `"exact flagged phrase(s):
     ..."` vào cuối reason string khi có. Cả `gate_brand_seo_audit()` và
     `gate_brand_seo_audit_social()` giờ truyền `flagged_phrases` vào lời gọi này.
   - `_GENERIC_AI_WORDING_ANCHOR` → đổi tên `GENERIC_AI_WORDING_ANCHOR` (bỏ underscore, export
     công khai) — repair.py cần import cùng hằng số này để KHÔNG lặp lại nội dung (rubric
     good/bad anchor) ở 2 nơi có thể trôi (drift) theo thời gian.
   - `_DEFAULT_FRAMEWORK_RUBRIC` → đổi tên `DEFAULT_FRAMEWORK_RUBRIC` (cùng lý do — repair.py/
     pipeline.py cần fallback giống hệt `gate_framework()` dùng).
   - `FRAMEWORK_RUBRICS` đã public sẵn — không đổi.
2. `services/acp_produce/repair.py`
   - Import `DEFAULT_FRAMEWORK_RUBRIC, FRAMEWORK_RUBRICS, GENERIC_AI_WORDING_ANCHOR` từ
     `gates.py` (xác nhận KHÔNG circular: gates.py không import gì từ repair.py).
   - `_build_repair_system_prompt()`: nối `GENERIC_AI_WORDING_ANCHOR` ngay sau
     `brand_rubric_text`, không điều kiện theo gate nào — cùng nguyên tắc "brand rubric luôn
     có mặt mỗi vòng repair bất kể gate nào trigger" AA-404 đã thiết lập.
   - `PieceInvariants` thêm 2 field mới: `framework: Optional[str] = None`,
     `framework_rubric_items: list[str] = field(default_factory=list)` — default rỗng nên mọi
     call site trước AA-382 không đổi hành vi.
   - `_build_structural_context()`: thêm 1 dòng STRUCTURAL CONTEXT khi
     `framework_rubric_items` khác rỗng — liệt kê TOÀN BỘ tiêu chí rubric của framework đó
     (không chỉ tiêu chí đang fail), kèm câu "a fix for one criterion must not break any of
     the others" (cùng tinh thần các invariant khác trong file).
3. `services/acp_produce/pipeline.py`
   - Import thêm `DEFAULT_FRAMEWORK_RUBRIC, FRAMEWORK_RUBRICS` từ gates.py.
   - `_build_repair_invariants()`: không cần tham số mới (đã có sẵn `effective_framework`) —
     tra `FRAMEWORK_RUBRICS.get(effective_framework, DEFAULT_FRAMEWORK_RUBRIC)`, truyền vào
     `PieceInvariants(framework=effective_framework, framework_rubric_items=...)`.

**Không đổi**: logic chấm điểm/pass-fail của F8/F9 (`gate_framework()`,
`gate_brand_seo_audit()`, `gate_brand_seo_audit_social()`'s scoring) — chỉ đổi cách build
`violations`/system-prompt/`PieceInvariants` mà repair nhận, đúng scope task yêu cầu.

## Decisions

- **Không tạo good/bad anchor mới cho F8**: task hỏi có nên thêm anchor riêng cho F8 như F9 đã
  có. Quyết định KHÔNG làm — F9's anchor (`GENERIC_AI_WORDING_ANCHOR`) được hiệu chỉnh từ MỘT
  case thật cụ thể (AA-404 fix #2's docstring: piece thật, ngày thật, false positive thật đã
  xác nhận). F8 chưa có bất kỳ dữ liệu thật nào về false-positive/non-convergence pattern
  tương tự để hiệu chỉnh từ — bịa một anchor không có data thật đi ngược nguyên tắc
  Mistake-to-Rule (ADR-2026-009) chính codebase này đã tự đặt ra cho F9-social's rubric
  ("extend from real failures, don't guess the full blog-shaped rubric ahead of data"). Thay
  vào đó, F8 được đưa TOÀN BỘ rubric list (thay vì chỉ 1 tiêu chí) — đây là phần chắc chắn cần
  và có thể làm ngay không cần thêm data.
- **`GENERIC_AI_WORDING_ANCHOR` đưa vào system prompt KHÔNG điều kiện** (mọi vòng repair, bất
  kể gate nào trigger) thay vì chỉ khi vòng đó target F9 — vì bản thân `brand_rubric_text` mà
  nó đi kèm cũng đã không điều kiện từ AA-404, và nguyên tắc "đừng viết prose chung chung" áp
  dụng cho MỌI câu mới repair viết ra, không chỉ khi sửa lỗi F9.
- **`flagged_phrases` nối vào cuối `_format_audit_reason()`'s output thay vì thay thế
  `notes`**: giữ nguyên tính additive — mọi test/caller cũ assert substring của format cũ vẫn
  đúng.

## Tradeoffs

- **Token cost tăng mỗi vòng repair** (ước tính bằng đếm ký tự/4, không đo runtime — xem mục
  Token cost bên dưới) — chấp nhận được vì repair vốn đã gọi Sonnet với `max_tokens=4096` cho
  toàn bộ `body_tagged`, mức tăng là tương đối nhỏ so với tổng.
- **`framework_rubric_items` giờ LUÔN xuất hiện cho mọi piece thật** (mọi framework key đều có
  entry trong `FRAMEWORK_RUBRICS` hoặc fallback `DEFAULT_FRAMEWORK_RUBRIC`) — không phải
  "conditional theo brief" như `required_h2s`/section-ownership. Đây là lựa chọn có chủ đích
  (framework luôn áp dụng cho piece, khác các invariant chỉ áp dụng cho 1 số channel), nhưng
  nghĩa là STRUCTURAL CONTEXT block giờ dài hơn cho MỌI repair round trong production, không
  chỉ khi F8 fail.
- **Không sửa được root cause phụ đã phát hiện** (judge có thể đang over-flag văn bản đạt
  chuẩn — xem mục "Quan sát phụ" ở trên) — nằm ngoài scope, chỉ ghi nhận.

## Should know (trước khi đọc diff)

- `_GENERIC_AI_WORDING_ANCHOR`/`_DEFAULT_FRAMEWORK_RUBRIC` đổi tên bỏ underscore (export công
  khai) — diff sẽ hiện thay đổi ở CẢ định nghĩa lẫn 2-3 chỗ dùng trong gates.py, không phải
  logic mới.
- `repair.py` giờ import từ `gates.py` (chiều mới) — đã verify KHÔNG circular (gates.py chỉ
  import `judge_client`, `models`, `acp_shared.grounding` — không import gì từ `repair.py`).
- Test suite: `pytest tests/ -v` (trừ 1 file collection error có sẵn từ trước, không liên quan
  — `tests/acp/test_brand_brief_parser.py` thiếu module `models`, xác nhận lỗi này tồn tại y
  hệt trên `main` chưa sửa gì, không phải do AA-382) + 24 integration test fail cần DB
  live/RLS setup thật (xác nhận CŨNG fail y hệt trên `main`, không liên quan AA-382) — TOÀN BỘ
  103 unit test liên quan trực tiếp (`test_aa376_repair.py`, `test_aa404_repair_invariants.py`,
  `test_aa372_gates.py`, `test_aa298_judge.py`, `test_aa364_pipeline.py`) + 1621 test khác
  trong suite PASS sạch, 0 test mới fail do thay đổi này.

## Token cost — ước tính (đếm ký tự/4, KHÔNG đo runtime thật)

| Thành phần thêm mới | ~ký tự | ~token | Tần suất |
|---|---:|---:|---|
| `GENERIC_AI_WORDING_ANCHOR` (system prompt) | 1,664 | **~416** | MỌI vòng repair (mọi gate) |
| `framework_rubric_items` block (user prompt) | 50-120 | **~15-30** | MỌI vòng repair (mọi piece thật) |
| `flagged_phrases` nối vào violation string | biến thiên, thường 1-6 câu | **~15-80** | Chỉ vòng repair target F9, và chỉ khi judge trả `flagged_phrases` (bắt buộc từ AA-404 cho SUMMARY_OFF_BRAND/GENERIC_AI_WORDING) |

**Tổng ước tính mỗi vòng repair**: +~430-530 token input so với trước — so với baseline
`brand_rubric_text` một mình đã ~818 token (constant `AA_BRAND_IDENTITY_PROMPT`, rubric
per-tenant thật có thể khác) + `body_tagged` toàn bộ piece (piece blog thật ~800-1500 từ ≈
1200-2500 token) + `_REPAIR_HARD_RULES` + violations — mức tăng ước tính **~15-25% tổng input
token của một lời gọi repair**, không phải tăng gấp đôi. Output token (`max_tokens=4096`) và
model (Sonnet, acc3) không đổi — cost/call tăng theo tỷ lệ input token tăng thôi (input
Sonnet rẻ hơn output nhiều lần), tác động cost thực tế nhỏ hơn tỷ lệ % input token. Không đo
runtime thật trong task này (theo đúng yêu cầu: "không cần code đo cost, chỉ ước tính bằng
lời") — số liệu thật nên lấy từ CloudWatch/AA-418 cost tracking sau khi merge+chạy N7 thật.

## Verify — LÀM ĐƯỢC vs. CHƯA LÀM ĐƯỢC trong session này

✅ **Đã làm**:
1. STEP 0 xác nhận giả thuyết bằng code thật + data thật (trên).
2. `pytest tests/` — 0 test mới fail (chi tiết ở mục "Should know").
3. Baseline F8/F9 pass rate THẬT lấy từ 4 run N7 gần nhất (bảng trên) — dùng làm mốc so sánh
   sau khi merge.
4. Sanity-check thủ công end-to-end (mock `invoke_claude`, không phải unit test chính thức)
   xác nhận prompt thật sự chứa: violation string kèm `flagged_phrases`, system prompt kèm
   `GENERIC_AI_WORDING_ANCHOR`, structural context kèm đủ rubric F8 framework.

⚠️ **CHƯA làm được trong session này — cần follow-up SAU KHI merge**:
1. **Chạy N7 thật tuần mới để so sánh F8/F9 pass rate trước/sau** — KHÔNG thể làm trong session
   này vì code AA-382 chưa merge/deploy (task yêu cầu rõ "KHÔNG tự merge" — PR mở, chờ Nghiệp).
   ECS Dev hiện đang chạy code từ PR #171 (`f84a12e`), CHƯA có fix này. Chạy N7 bây giờ chỉ
   cho lại đúng baseline 0/12 F9 y hệt bảng trên, không phải verify thật. **Đề nghị: sau khi
   Nghiệp merge + CI deploy xong, chạy 1 task follow-up riêng (theo đúng pattern AA-415 đã làm
   2 lần — verify digest ECR khớp `:latest`/ECS running task, trigger tuần N7 MỚI chưa từng
   chạy, so `d776a047`/`363f22c9`/`d0722ae3` ở trên làm baseline).**
2. Deploy Dev qua CI + verify ECS digest khớp `:latest` — phụ thuộc bước merge, chưa làm được
   vì lý do trên.
3. Đọc `held_reason` của piece còn fail SAU fix để xác nhận hội tụ — phụ thuộc bước 1.

Đây là giới hạn thật của việc "không tự merge" kết hợp "phải verify bằng N7 thật" — 2 yêu cầu
này không thể cùng thoả trong 1 session không merge. Ghi rõ thay vì tự bịa số liệu "sau" giả.

---

# UPDATE 16/08/2026 — merge + deploy + verify N7 thật (theo yêu cầu Nghiệp: "CI green thì merge luôn")

PR #172 merged `0cb7d87` (5/5 required check pass, không có migration). Deploy Dev qua CI
chạy tự động trên push — ECR `:latest` digest `sha256:279a99b1...` (tag
`dev-0cb7d87e2a9522433447a076d26d9f46ec4b258d`, khớp TRỰC TIẾP merge commit) — ECS running
task xác nhận CÙNG digest, `RUNNING`/`HEALTHY`.

## Trigger N7 thật — Gate B chặn tuần dự định ban đầu

Dự định trigger `2026-10 W1` (tháng chưa từng chạy) nhưng bị chặn: `400 — No approved quarter
plan for tenant=... year=2026 quarter=4 — Gate B: quarter plan must be approved by a human (Ms.
Thu) before allocation — never auto.` Q4 (tháng 10-12) chưa được approve. Chuyển sang tuần chưa
từng chạy NHƯNG vẫn trong quarter đã approve (Q3 = tháng 7-9): xác nhận trước khi trigger qua
query `acp_shared.acp_v2_runs` — tháng 7 chỉ có week 1 đã chạy, weeks 2-4 còn trống. Chọn
**`2026-07 W2`** (chưa từng chạy).

Verify run: **`88f094b1-3e0a-4b28-9abb-205cb7d21287`**, tenant `aa_internal`, 2026-07 W2, 3 slot
due.

## Sự cố hạ tầng THẬT xảy ra 2 lần trong lúc chạy — đúng pattern đã ghi nhận 4 lần trước (AA-404/AA-415)

- Lần 1 (~13:59Z): ECS task bị kill/thay (`78ce6214...` → `06628d99...`) giữa lúc 1/3 slot đã
  xong (4 piece đã persist, KHÔNG mất data) — job background (`_produce_slots_background`)
  chết theo task cũ, run kẹt ở `status=producing`. **Recovery: re-POST đúng body cũ** —
  `create_weekly_produce_run()`'s `ON CONFLICT DO NOTHING` cho lại đúng `run_id`,
  `due_slot_count: 2` (2 slot còn `due`) — xác nhận LẦN THỨ 3 (độc lập, sau run #6 và
  `363f22c9`) cơ chế resume an toàn hoạt động đúng.
- Lần 2 (~14:57-15:00Z): API trả response rỗng liên tục ~5 phút (không phải lỗi HTTP, timeout
  client-side) — job production TỰ PHỤC HỒI, không cần re-POST lần 2 (khác lần 1 — có thể chỉ
  là health-check chậm tạm thời, không tới mức ECS kill task lần này).
- Tổng thời gian thật: ~66 phút (13:56:10 → 15:01:48), gồm 1 lần gián đoạn cần can thiệp thủ
  công + 1 lần tự phục hồi.

## Kết quả F8/F9 — cơ chế fix HOẠT ĐỘNG ĐÚNG THIẾT KẾ, nhưng KHÔNG tự nó nâng pass rate

**Pass rate run mới (9 piece) so với baseline (trước fix, 4 run gần nhất):**

| | Baseline (trước AA-382) | Run mới `88f094b1` (sau AA-382) |
|---|---:|---:|
| F8 pass | 8/12, 9/12, 8/9, 9/12 (67-89%) | **8/9 (89%)** |
| F9 pass | 0/12, 0/12, 0/9, 2/12 (0-17%) | **1/9 (11%)** |

Không có bước nhảy rõ rệt — ĐÚNG NHƯ DỰ ĐOÁN trong report gốc: fix này sửa INPUT repair nhận
(có `flagged_phrases`/rubric đầy đủ hay không), không sửa việc JUDGE có tiếp tục tìm ra vi
phạm MỚI mỗi vòng hay không — 2 việc khác nhau.

**Xác nhận CƠ CHẾ hoạt động đúng (đọc `repair_log` đầy đủ, không chỉ pass/fail cuối)** — MỌI
vòng repair target F9 trong run này (7 vòng, trải trên 5 piece) đều có
`"exact flagged phrase(s): ..."` trong violation string — xác nhận `flagged_phrases` đang thật
sự chảy tới repair trong production, không phải chỉ đúng trên unit test.

**Nhưng vẫn thấy "moving target" — nguyên nhân giờ đã rõ, KHÔNG PHẢI THIẾU CONTEXT nữa:**

Ví dụ `slot_9afc9ee...:blog#tiktok` (held sau 3 vòng, hết ngân sách): round 1 flag phrase A
("This one's built differently"), repair sửa ĐÚNG phrase A (có exact quote, không phải đoán) —
nhưng round 2 judge flag phrase B HOÀN TOÀN KHÁC ("The standard South Korea itinerary runs
Seoul to Busan to Jeju...") — không phải vì repair sửa sai, mà vì JUDGE chấm lại TOÀN BỘ piece
mỗi vòng và có thể tìm ra 1 câu KHÁC để flag là "generic" mà vòng trước nó chưa từng nhắc tới.
Đây là hành vi JUDGE (Nova Pro over-sensitive/không ổn định), KHÔNG PHẢI gap về context nữa —
đúng ranh giới đã nêu rõ trong report gốc ("không đổi logic judge") và khớp quan sát phụ đã ghi
("một số câu bị flag đọc thực tế lại đạt chuẩn GOOD của chính rubric"). Repair giờ luôn sửa
ĐÚNG câu được chỉ ra — vấn đề còn lại nằm ở phía JUDGE liên tục di chuyển mục tiêu, xứng đáng 1
issue riêng (đề xuất, không tự tạo).

**1 case F8 đáng chú ý — CHÍNH LÀ case dẫn chứng gốc trong Linear AA-382:**
`slot_9afc9ee...:blog#facebook` held nguyên 4/4 vòng trên `"framework criterion failed: ends
with CTA"` — dù có hint xác định (`_VIOLATION_HINTS`, có từ trước AA-382) VÀ giờ có thêm full
rubric list. Đây đúng là case Nghiệp đã mô tả trong issue gốc ("đổi CTA 3 kiểu khác nhau vẫn
không qua"), verify được LẶP LẠI THẬT trong run này — gợi ý nguyên nhân KHÔNG PHẢI thiếu rubric
context (giờ đã có đủ) mà là 1 giới hạn CẤU TRÚC khác (có thể định dạng facebook luôn cần 1
dòng sau CTA — vd HASHTAGS — mâu thuẫn với "CTA phải là câu cuối cùng" của
`_ends_with_cta()`). KHÔNG sửa trong task này (ngoài scope, cần đọc `body_tagged` thật để xác
nhận giả thuyết trước khi quyết định hướng fix) — ghi lại làm bằng chứng cho 1 issue con nếu
Nghiệp muốn theo đuổi.

## Kết luận verify

✅ Fix hoạt động ĐÚNG như thiết kế — `flagged_phrases`/`GENERIC_AI_WORDING_ANCHOR`/framework
rubric đầy đủ ĐÃ tới repair trong mọi vòng, xác nhận bằng data thật, không phải giả lập.
⚠️ Pass rate F8/F9 KHÔNG cải thiện rõ rệt trong 1 sample nhỏ (N=9) — đúng dự đoán, vì nguyên
nhân pass-rate thấp phần lớn nằm ở JUDGE (moving target) + 1 case cấu trúc F8 riêng, không
phải context-gap AA-382 nhắm sửa. AA-382 tự nó hoàn thành đúng scope ("repair có đủ context
để BIẾT sửa gì" — xác nhận đúng); "sửa được câu đúng có giúp piece pass không" phụ thuộc thêm
vào việc JUDGE có ngừng di chuyển mục tiêu hay không, đó là câu hỏi khác.

**Đề xuất cho Nghiệp (không tự tạo issue, không tự đổi status AA-382):**
1. Issue riêng cho JUDGE calibration (F9 Nova Pro tiếp tục flag phrase mới mỗi vòng dù phrase
   trước đã sửa đúng, một số phrase bị flag đọc lại đạt chuẩn GOOD) — dữ liệu thật đã đủ trong
   report này.
2. Issue riêng cho F8 facebook "ends with CTA" case cụ thể (`slot_9afc9ee...`) — đọc
   `body_tagged` thật để xác nhận giả thuyết HASHTAGS/format-conflict trước khi quyết định
   hướng fix.

## Không làm trong task này

- Không sửa logic chấm điểm F8/F9 (giữ đúng scope).
- Không tạo good/bad anchor mới cho F8 (xem Decisions).
- Không tự merge PR, không tự đổi status AA-382 trên Linear.
- Không sửa vấn đề "judge có thể over-flag văn bản đạt chuẩn" phát hiện phụ ở trên — chỉ ghi
  nhận cho Nghiệp cân nhắc issue riêng.
