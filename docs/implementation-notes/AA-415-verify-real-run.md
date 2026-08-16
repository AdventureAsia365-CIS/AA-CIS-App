# AA-415 — verify bằng N7 run thật (post-merge), đối chiếu Run History

Task: `docs/claude_tasks/AA-415-02-verify-real-n7-run.md`. PR #170 merged `35cbf7b`, deployed
Dev. Verify run: **`363f22c9-f528-4b7a-83f7-c08c90021f53`**, tenant `aa_internal`
(`00000000-0000-0000-0000-000000000001`), **2026-09 W3** — tuần kế tiếp ngay sau baseline
(2026-09 W2 = run #6, chưa từng chạy trước đây, xác nhận qua query trực tiếp
`acp_shared.acp_v2_runs` trước khi trigger, không trùng tuần nào trong 7 run trước).

## Bước 0 — Digest verify: khớp, resolve luôn gap "MFA blocked" từ AA-415's PR comment

- ECR `:latest` digest: `sha256:a8caf46d3c6f7294ae813074bcc6b70b03cede7a6da40d74a000b1958c052de5`
  (tag `dev-35cbf7bedf43403133831161e76a237eb7ffe866` — khớp TRỰC TIẾP merge commit `35cbf7b`
  của PR #170, không phải suy luận).
- ECS running task digest tại thời điểm trigger run: **CÙNG** digest trên. Task started
  `2026-08-16T17:57:52+07:00` (task `286b1655...`).
- **Đây là lần verify digest THÀNH CÔNG** cho AA-415 — session trước bị chặn bởi MFA tương
  tác; session này cache session AWS đã hoạt động lại bình thường, không cần MFA. Gap đã nêu
  trong comment Linear AA-415 trước đây (16/08, ~11:00Z) nay đã đóng.

## Bước 1-2 — Trigger + theo dõi run thật, có 1 sự cố hạ tầng thật xen giữa (giống hệt run #6)

- Trigger `POST /admin/produce/run` lúc `2026-08-16T11:30:43Z`, `due_slot_count: 4`.
- 2 slot đầu (`slot_3485bd7d3513aaee9f89`, `slot_ca3d574725334f1b6d99`) xong lúc ~11:39Z (6
  piece). Sau đó run TREO — không thêm piece nào trong ~10 phút.
- **Xác nhận qua `aws ecs describe-services` events: đúng CÙNG sự cố ALB health-check timeout
  đã ghi trong run #6** (`docs/claude_audit/AA-404-n7-run6-results.md` Step 2) — task
  `286b1655...` báo `unhealthy` (`Request timed out`) lúc `18:33:28+07` (`11:33:28Z`), ECS
  kill + thay task mới (`052066a4...`). Đây là bằng chứng THỨ 2 (độc lập với run #6) cho cơ
  chế nghi vấn nêu trong `docs/claude_audit/AA-418-parallel-cost-investigation.md` §A.2(d) —
  không còn là sự cố 1 lần, mà là pattern lặp lại thật, đáng làm ticket riêng nghiêm túc hơn
  (đã có khuyến nghị này trong AA-404's report, nhắc lại ở đây với bằng chứng thứ 2).
- **Recovery: re-POST đúng body cũ** — `create_weekly_produce_run()`'s `ON CONFLICT DO
  NOTHING` cho lại đúng `run_id`, `due_slot_count: 2` (chỉ 2 slot còn `due`) — xác nhận cơ chế
  resume an toàn hoạt động đúng lần thứ 2. Run tiếp tục và **COMPLETED** lúc `12:08:33Z` — 12/12
  piece thật, không có piece nào bị mất/orphan (giống kết luận run #6: sự cố hạ tầng không làm
  hỏng data, chỉ tốn thêm thời gian + 1 lần retrigger thủ công).
- Tổng thời gian thật: ~38 phút (11:30:43 → 12:08:33), bao gồm ~10 phút chết do sự cố.

## Bước 3 — Gate ledger đầy đủ, so sánh F1_grounding với baseline run #6

**F1_grounding — CẢI THIỆN THẬT, có số liệu cụ thể:**

| | Run #6 (baseline, trước PR #170) | Run mới (363f22c9, sau PR #170) |
|---|---:|---:|
| F1 pass | 5/9 (55.6%) | **9/12 (75%)** |
| F1 fail (first-fail) | 4/9 (44.4%) | **3/12 (25%)** |

→ **F1 fail rate giảm từ 44% xuống 25%** — cải thiện thật, ~19 điểm phần trăm, ~43% relative
reduction. Không phải "cải thiện đáng kể tuyệt đối" (vẫn còn 1/4 piece fail F1) nhưng là cải
thiện rõ rệt, đúng hướng dự đoán của fix.

**F9 (không phải mục tiêu AA-415, ghi lại theo yêu cầu task) — KHÔNG cải thiện, thậm chí tệ
hơn baseline trong sample nhỏ này:**

| | Run #6 | Run mới |
|---|---:|---:|
| F9_brand_seo_audit (blog) pass | 4/9→3/9 tuỳ run 5a/5b (33%/33%, xem AA-404-n7-run6-results.md) | **0/4 (0%)** |
| F9_brand_seo_audit_social pass | ~33% | **0/8 (0%)** |

F9 vẫn là "moving target" (GENERIC_AI_WORDING) đúng như F9 deep-dive đã kết luận trước đây —
không nằm trong scope AA-415, không sửa gì ở đây, chỉ ghi số liệu thật để AA-404 (đang mở
song song) có dữ liệu. Sample N=12 nhỏ, 0/12 có thể là nhiễu thống kê, không kết luận "F9 xấu
đi thật" chỉ từ 1 run.

## Bước 4 — Cơ chế cũ (F1 xuất hiện "bất ngờ" sau F5/F9) có còn xảy ra không? **CÓ, nhưng ÍT HƠN — fix GIẢM chứ chưa LOẠI BỎ hoàn toàn**

Đọc kỹ `repair_log` (round-by-round, query trực tiếp DB — API `/admin/produce/run/{id}`
KHÔNG trả field này, phải query `acp_deliver.pieces.repair_log` qua ECS exec) cho cả 3 piece
fail F1 trong final ledger — phân biệt rõ 2 loại khác nhau:

**Loại 1 — F1 fail NGAY TỪ ĐẦU, không phải regression (2/3 piece fail F1):**
- `slot_3485bd7d3513aaee9f89:blog`: `initial_failing_gate_count=2` — F1 đã fail ở draft đầu.
  CẢ 4/4 vòng repair đều target thẳng vào F1_grounding — được cấp ĐỦ ngân sách riêng, nhưng
  **LLM không sửa được**, trả về CÙNG một violation y hệt (`sentence states ['99'] not
  present...`) suốt cả 4 vòng, không đổi một chữ. Đây KHÔNG PHẢI cơ chế AA-415 nhắm sửa (F1
  không "bất ngờ xuất hiện" — nó fail từ đầu và có cơ hội sửa riêng) — đây là vấn đề KHÁC:
  repair loop bị "kẹt", lặp lại cùng 1 kết quả không hội tụ. Nghi vấn (chưa xác nhận, cần đọc
  `body_tagged` thật để kết luận): "99"/"Ride 99" trong context có vẻ là TÊN route đạp xe
  (heading "## Ride 99"), có thể F1's numeric-claim detection đang flag nhầm 1 con số nằm
  trong TÊN RIÊNG, không phải 1 claim thật cần grounding — nếu đúng, đây là false positive ở
  chính F1_grounding, không liên quan gì tới AA-415/PieceInvariants. KHÔNG tự sửa trong task
  này — báo lại, đề xuất đọc thêm `body_tagged` thật để xác nhận trước khi quyết định có phải
  bug F1 hay không.
- `slot_efb6c6d175e23bad4767:blog`: y hệt pattern trên — `initial_failing_gate_count=2`, 4/4
  vòng target F1, không hội tụ, violation lặp lại (`sentence states ['3']...`).

**Loại 2 — ĐÚNG cơ chế AA-415 nhắm sửa, VẪN CÒN XẢY RA 1 LẦN (1/3 piece fail F1):**
- `slot_efb6c6d175e23bad4767:blog#tiktok`: `initial_failing_gate_count=1` — **F1 KHÔNG fail ở
  draft đầu** (đúng chữ ký của cơ chế regression AA-415 mô tả). Round 1-2 target
  `F9_brand_seo_audit_social` (sửa brand/SEO). Round 3 chuyển sang target `F1_grounding` — tức
  là **F1 mới xuất hiện SAU 2 vòng repair F9**, đúng cơ chế cũ. Round 3 (vòng F1 dành riêng
  DUY NHẤT — vì `repair_budget=3` tính từ `initial_failing_gate_count=1`, ngân sách không mở
  rộng thêm) **fail**, hết ngân sách, piece held trên F1
  (`sentence states ['60'] not present in its cited id(s): 'A K-pop dance class...'`).

**Kết luận rõ ràng cho câu hỏi của task:** cơ chế cũ (F5/F9 repair viết câu mới, tạo F1 fail
mới mà repair loop không có cơ hội sửa riêng) **VẪN CÓ THỂ XẢY RA sau PR #170** — tần suất
giảm (1/12 = 8% ở run mới, so với 2/9 = 22% ở run #6 — cả 2 case F1-regression thật của run #6
đều thuộc loại này) nhưng KHÔNG bằng 0. Đọc kỹ violation: câu bị flag VẪN có tag trích dẫn
(`cited id(s)`) — nghĩa là AA-415's hướng dẫn "đừng viết câu không tag" đã có tác dụng một
phần (không còn thấy câu HOÀN TOÀN không tag nào trong 3 case fail F1 lần này, khác baseline
run #6 nơi ít nhất 1 case có sentence hoàn toàn thiếu context) — nhưng chưa ngăn được hoàn toàn
việc gắn tag SAI (claim không khớp text atom được cite) khi round 3 chỉ có ĐÚNG 1 lần thử.
**Đây không phải bug mới do AA-415 gây ra — đây là giới hạn CÒN LẠI của chính cơ chế
`compute_repair_budget()`** (ngân sách tính từ SỐ GATE fail ban đầu, không phải từ gate nào
xuất hiện MUỘN) — AA-415 chỉ thêm INPUT (atom text + hướng dẫn tag) cho vòng repair, không đổi
cách TÍNH ngân sách. Fix đã làm đúng scope của nó (giảm tần suất, không xoá hoàn toàn nguyên
nhân gốc là budget-sizing) — phù hợp với chính lời văn AA-415 (Linear): "rẻ để vá... chỉ mở
rộng phạm vi dùng, không xây cơ chế mới" — không hứa loại bỏ 100%.

## Bước 5 — Đối chiếu Run History UI thật: KHÔNG chụp được screenshot trong session này

Đã verify bằng cách gọi TRỰC TIẾP đúng API thật production (`GET/POST
https://api-cis.lumiguides.it.com/admin/produce/...`, cùng route Run History UI dùng) + query
trực tiếp DB thật (`acp_deliver.pieces`) — dữ liệu là dữ liệu PRODUCTION thật, không phải
mock/local. **Nhưng session Claude Code này không có công cụ browser/screenshot** để tự mở
`aa-cis.lumiguides.it.com/admin/produce` và chụp ảnh — route UI đó còn yêu cầu cookie session
admin thật (`requireAdmin()`) mà agent không có. Đây là giới hạn công cụ, không phải bỏ qua
bước — flagging rõ thay vì im lặng bỏ qua, đúng như task dặn. **Đề xuất: Nghiệp tự mở
`/admin/produce` → Run History → run `363f22c9` (2026-09 W3) để đối chiếu mắt thường với số
liệu trên, và/hoặc tự chụp nếu cần bằng chứng hình ảnh.**

## Verify checklist (theo task)

1. ✅ Kết luận rõ ràng: **F1 pass rate cải thiện — 9/12 (75%) so với baseline 5/9 (55.6%),
   fail rate giảm 44%→25%.**
2. ⚠️ F1 CÓ cải thiện rõ rệt nhưng CHƯA hoàn hảo — 1/12 piece vẫn thể hiện đúng cơ chế
   regression cũ (tần suất giảm, chưa = 0). Đề xuất bước tiếp theo (không tự code):
   (a) đọc `body_tagged` thật của 2 piece "loại 1" (`slot_3485...blog`,
   `slot_efb6...blog`) để xác nhận có phải F1 false-positive trên tên riêng ("Ride 99") hay
   là hallucination thật — quyết định khác nhau tuỳ kết quả; (b) cân nhắc thiết kế lại
   `compute_repair_budget()` để dành riêng ít nhất 1 vòng cho gate MỚI xuất hiện muộn, không
   chỉ tính theo số gate fail BAN ĐẦU — đây là nguyên nhân gốc còn lại của "loại 2".
3. ✅ Report này lưu tại `docs/implementation-notes/AA-415-verify-real-run.md`.
4. Đề xuất cho Nghiệp (không tự đổi status): **AA-415 CÓ THỂ coi là Done** theo đúng nghĩa
   "cải thiện thật, đo được, hướng đúng" — nhưng nếu tiêu chuẩn Done là "loại bỏ hoàn toàn cơ
   chế regression", thì CHƯA đạt (1/12 case vẫn xảy ra) — 2 việc tiếp theo (false-positive
   "Ride 99" + budget-sizing cho gate muộn) xứng đáng thành issue con riêng thay vì giữ
   AA-415 mở treo, vì bản thân AA-415's scope ("mở rộng PieceInvariants") đã hoàn thành đúng
   như mô tả.

## Không làm trong task này (đúng scope "chỉ verify")

- Không sửa code nào (kể cả nghi vấn F1 false-positive trên "Ride 99" — chỉ nêu giả thuyết,
  chưa đọc body thật để xác nhận).
- Không tạo Linear issue con mới cho 2 việc đề xuất ở Bước 5 — để Nghiệp quyết.
- Không tự đổi status AA-415 trên Linear.

---

# UPDATE 16/08/2026 — verify PR #171 (repair-budget-late-gate fix), N7 run thật thứ 3

PR #171 merged `f84a12e`, deployed Dev — digest ECR `:latest` khớp TRỰC TIẾP tag
`dev-f84a12e0c66c73a317f4a8e66d6a564d3083b273` (merge commit `f84a12e`), ECS running task
cùng digest `sha256:d1dc1ab0...` tại thời điểm trigger.

Verify run: **`d776a047-0aa8-4175-a252-3084cd4f3d3d`**, tenant `aa_internal`, **2026-09 W4** —
tuần kế tiếp chưa từng chạy (xác nhận trước khi trigger).

## Số liệu F1_grounding — cải thiện thêm rõ rệt

| Run | F1 pass | F1 fail |
|---|---:|---:|
| Run #6 (baseline, trước PR #170) | 5/9 (55.6%) | 4/9 (44.4%) |
| `363f22c9` (sau PR #170, trước #171) | 9/12 (75%) | 3/12 (25%) |
| **`d776a047` (sau PR #171)** | **11/12 (91.7%)** | **1/12 (8.3%)** |

## Cơ chế late-gate-budget mà PR #171 nhắm sửa — KHÔNG còn xuất hiện lần nào trong run này

Đọc `repair_log` đầy đủ cả 12 piece: **0/12 piece nào cho thấy hình dạng "gate xuất hiện muộn,
hết ngân sách trước khi kịp sửa"** — đúng chữ ký AA-415 gốc. 1 piece duy nhất còn fail F1
(`slot_f20e87cc4207a3673f02:blog`) có `initial_failing_gate_count=3`, **F1 fail NGAY TỪ ĐẦU**
(round 1 đã target F1), được cấp đủ 5/5 vòng repair dành riêng (`repair_budget=5`), không hội
tụ — đúng loại "stuck từ đầu" đã thấy ở run trước (`slot_3485...blog`/`slot_efb6...blog`), KHÔNG
PHẢI cơ chế PR #171 sửa.

## Xác nhận lần 3: ĐÚNG bug sentence-split, không phải hallucination

Đọc `body_tagged` thật của piece còn fail — **cùng cơ chế regex y hệt 2 case trước** (citation
tag `[R:id]` nằm giữa dấu câu và FAQ marker tiếp theo phá vỡ ranh giới câu):

```
...isn't available from this source. [R:atom_b12bdb857e]

**Q: What is the 52 hour rule in South Korea?**
A: The given fact covers a Day 2 visit to the Demilitarised Zone...
```

Citation `atom_b12bdb857e` (về chủ đề DMZ/food) bị merge với câu hỏi FAQ TIẾP THEO ("52 hour
rule"), số "52" bị kiểm tra sai atom nguồn. **Đây là lần thứ 3 độc lập xác nhận CÙNG root
cause** (Ride 99 / "3 day rule" / "52 hour rule" — cả 3 đều FAQ hoặc heading merge với citation
liền trước). Với PR #171 đã đóng cơ chế late-gate-budget, **bug sentence-split này giờ là
NGUYÊN NHÂN DUY NHẤT còn lại** của mọi F1 fail quan sát được qua cả 2 run verify — đáng để
Nghiệp cân nhắc lại việc tách issue riêng (trước đó quyết giữ trong AA-415 khi mới có 2 case,
giờ đã có 3, cùng root cause, và là block cuối cùng còn lại).

## Sự cố hạ tầng (AA-416) — LẦN THỨ 3 và 4 xảy ra ngay trong lúc verify run này

Run này bị gián đoạn bởi container/ALB health-check timeout **2 lần liên tiếp** (tổng cộng lần
thứ 3 và thứ 4 quan sát được, sau 2 lần ở run #6 và run `363f22c9`):
- Lần 1: ngay đầu run, 0 piece nào bị mất (chưa kịp persist gì) — resume qua re-POST.
- Lần 2: giữa lúc piece `slot_f20e87cc...:blog` đang ở vòng repair 4 (F1_grounding) — task bị
  kill, `/health` chính nó cũng trả 504 (29.7s) TRƯỚC KHI task bị đánh dấu unhealthy — bằng
  chứng trực tiếp khớp cơ chế đã nêu trong `docs/claude_audit/AA-418-parallel-cost-investigation.md`
  §A.2(d): lệnh Bedrock đồng bộ (`invoke_claude()`) chặn event loop đơn luồng đủ lâu để chính
  health check thất bại — không phải giả thuyết nữa, quan sát trực tiếp lần này (log thấy
  `n7_repair_round_attempt round=4` ngay trước dòng "Shutting down"). Resume qua re-POST lần
  2, không mất data (slot đã produced trước đó giữ nguyên).
- Tổng thời gian chạy thật: ~23 phút (12:58:33 → 13:21:42), có 2 lần gián đoạn + 2 lần
  re-POST thủ công.

## Kết luận verify PR #171

**Đạt mục tiêu chính: cơ chế late-gate-budget-exhausted (đúng thứ AA-415/PR#171 nhắm sửa)
KHÔNG còn xuất hiện trong run thật này (0/12).** F1 pass rate tiếp tục cải thiện 75%→91.7%.
1 piece còn fail F1 là do bug KHÁC (sentence-split, đã xác nhận 3 lần, ngoài scope AA-415 gốc).

**Đề xuất cho Nghiệp:** AA-415 (cả 2 phần: PieceInvariants atom_text_by_id + repair-budget
late-gate) có thể coi là Done thật — mục tiêu ban đầu ("F1 không còn bất ngờ xuất hiện sau
F5/F9 mà không có cơ hội sửa riêng") đã đạt, đo bằng dữ liệu production thật qua 2 lần merge.
Phần còn lại (sentence-split bug) là vấn đề khác, đáng 1 issue riêng nếu Nghiệp đồng ý (đã đủ
bằng chứng, không còn "chưa chắc") — nhưng không tự tạo, không tự đổi status AA-415.
