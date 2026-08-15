# F9 Deep-Dive — tại sao F9 chặn 100% piece qua 5 lần chạy [AA-404]

**Phạm vi: điều tra đọc-only, dữ liệu từ 6 run_id thật đã có (69 piece, 4 pass / 65 held) — không chạy N7 thêm.**

## TL;DR — 2 phát hiện mới quan trọng hơn cả 4 giả thuyết ban đầu

1. **Fix #1 (PR #158) chỉ wire brand rubric thật vào phía JUDGE (F9), không vào phía WRITER.**
   `generation.py` (E2 draft), `adapt.py` (E3), `faq.py` (E4), `repair.py` (E5) — **cả 4 module
   viết nội dung** vẫn hardcode `AA_BRAND_IDENTITY_PROMPT` generic. Chỉ `gates.py`'s 2 hàm F9
   (qua `slot_runner.py::fetch_brand_rubric_text()`) nhận rubric thật. Judge giờ chấm theo
   tiêu chuẩn cụ thể hơn hẳn — nhưng writer/repair vẫn viết theo target cũ, mơ hồ hơn. Đây gần
   như chắc chắn là lý do fix #1 không cải thiện được blog nhiều: đích chấm đã dịch chuyển,
   đích viết thì chưa.
2. **F9 (blog `F9_brand_seo_audit` + social `F9_brand_seo_audit_social`) fail ở **100% (65/65)**
   piece held**, qua TOÀN BỘ gate_ledger (không chỉ headline `held_reason`) — kể cả những piece
   mà `held_reason` báo gate khác (F1/F8) là "lý do chính". F9 chưa từng vắng mặt trong một
   piece held nào, ở bất kỳ lần chạy nào.

---

## Giả thuyết A — voice drift cấp-đoạn, judge chấm cấp-toàn-bài

**Kết luận: bằng chứng LẪN LỘN — đúng một phần, không phải nguyên nhân chính.**

Đọc `flagged_phrases` (evidence field, fix #3) + map vị trí ký tự trong `body_tagged`, đối
chiếu H2 section, cho 3 piece blog fail F9 ở lần chạy tháng 7 (mới nhất):

| Piece | Số phrase bị flag | Vị trí |
|---|---|---|
| `slot_329f2da4` (evergreen, transit) | 4 | 3/4 dồn ở section MỞ ĐẦU (2-6% bài), 1 ở section 2 (47%) |
| `slot_0457d3f4` (evergreen, culture) | 4 | Dồn đúng ranh giới section 1→2 (34-44% bài) — khớp giả thuyết boundary |
| `slot_d43e8c98` (campaign, bike) | **17** | Rải khắp TOÀN BÀI (0-84%), không có pattern vị trí |

Piece 3 (nhiều flag nhất, 17/25 = 68% tổng số phrase bị flag trong mẫu 3-piece) **KHÔNG** có
pattern vị trí — bác bỏ giả thuyết A là nguyên nhân chính cho piece này. Đọc nội dung 17 câu bị
flag của piece 3: phần lớn là văn phong **suy tư/triết lý** ("The mountains here do not
announce themselves dramatically", "That quietness of arrival is... the point") — CÓ gắn với
địa danh cụ thể (Yanggu, DMZ, Seorak) nhưng judge vẫn flag. Đây là dấu hiệu của **giả thuyết
mới**: judge coi văn phong suy tư/triết lý = generic, kể cả khi neo vào chi tiết thật — anchor
hiện tại (`_GENERIC_AI_WORDING_ANCHOR`) chỉ phân biệt "concrete fact" (tốt) vs "templated
superlative" (xấu), chưa có ví dụ cho loại thứ 3 này (suy tư cụ thể-theo-ngữ-cảnh nhưng không
phải factual).

Piece 1/2 CÓ ủng hộ giả thuyết A một phần (dồn ở mở đầu hoặc ranh giới section) — nhưng không
đủ mạnh/nhất quán để là nguyên nhân chính, và piece 3 (nặng nhất) hoàn toàn không khớp.

## Giả thuyết B — F9 chấm nhầm cấp độ tổng quát, đang làm việc của tầng khác chưa xây

**Kết luận: BẰNG CHỨNG MẠNH NHẤT — có xác nhận trực tiếp từ chính spec gốc.**

CONTEXT.md gốc (aa-marketing-v2) §1.6 "Anti-AI-voice stack (ordered by leverage)" liệt kê 6 tầng,
XẾP HẠNG theo độ hiệu quả — tầng #1 (cao nhất) là:

> **"Atom density validator: every 200–300 words of body must cite ≥1 atom/facts entry...
> AI-sounding text is an information-density problem, not a style problem: starve genericity
> out with specifics."**

Module F gốc cũng liệt F2 = atom density như gate THỨ HAI (ngay sau F1 grounding, TRƯỚC cả
banned-pattern lexicon). **Gate này KHÔNG hề tồn tại trong repo hiện tại** — `gates.py`'s
docstring tự xác nhận: *"Atom density (the aamc prototype's original F2) is not part of this
repo's gate set... it is not built here."*

Tầng #5 gốc ("The human seam" — chèn 1 câu thật/guest quote mỗi bài) **cũng không tồn tại**.

Kết quả: trong 6 tầng chống-AI-voice gốc, chỉ 2 tầng thực sự có (banned-pattern lexicon = F2 ở
repo này, structural variance = F3) + F9 (tầng #4 gốc, ĐƯỢC THIẾT KẾ để bắt phần CÒN LẠI sau
khi 3 tầng kia đã lọc). Ở repo này, F9 đang phải một mình gánh việc của CẢ tầng #1 (atom
density — deterministic, rẻ, không cần LLM judgment) LẪN tầng #5 (human seam) chưa từng được
xây — đúng như Nghiệp nghi ngờ: "F9 bị giao nhiệm vụ mơ hồ về bản chất."

**Số liệu ủng hộ trực tiếp:** code `BODY_EXPERIENCE_DETAILS_TOO_GENERIC` (nghĩa đen: thiếu
density chi tiết cụ thể — chính là thứ atom-density validator được thiết kế để bắt bằng
deterministic check) là code #1 riêng cho blog (22 lần, xem bảng tần suất bên dưới) — F9 đang
LLM-đoán chính xác cái mà 1 deterministic gate (không tốn Bedrock call) lẽ ra đã bắt được.

## Giả thuyết C — repair loop không sửa được "generic" theo cách sửa được vi phạm cụ thể

**Kết luận: XÁC NHẬN MẠNH, có số liệu — nhưng KHÔNG chỉ riêng F9.**

Tỷ lệ 1 vòng repair thực sự sửa xong (outcome=`passed`) theo từng gate, gộp cả 118 vòng nhắm
F9 + 139 vòng nhắm gate khác, toàn bộ 6 lần chạy thật:

| Gate | Vòng repair | Passed | Tỷ lệ |
|---|---:|---:|---:|
| F6_route_to_sellable | 1 | 1 | 100% |
| F2_banned_patterns | 5 | 4 | 80% |
| F4_brief_compliance | 11 | 6 | 54.5% |
| F1_grounding | 45 | 15 | 33.3% |
| F8_framework | 41 | 6 | 14.6% |
| **F3_structural_variance** | 36 | 1 | **2.8%** |
| **F9_brand_seo_audit_social** | 99 | 3 | **3.0%** |
| **F9_brand_seo_audit (blog)** | 19 | 0 | **0.0%** |
| **F9 tổng (blog+social)** | **118** | **3** | **2.5%** |
| Non-F9 tổng | 139 | 33 | 23.7% |

F9 thấp hơn ~10x so với non-F9 trung bình — **blog F9 CHƯA TỪNG sửa xong dù chỉ 1 lần trong 19
lần thử.** Nhưng: **F3_structural_variance (2.8%) gần y hệt F9 dù F3 là gate DETERMINISTIC,
không phải LLM judgment.** Đây là phát hiện bổ sung quan trọng: sự khác biệt không hoàn toàn
nằm ở "LLM judgment vs deterministic" — mà có vẻ nằm ở **LOCAL vs WHOLE-PIECE**: F1 (sửa 1 câu
sai)/F2 (thay từ cấm)/F6 (đổi URL) là vi phạm CỤC BỘ, dễ sửa từng điểm; F3 (nhịp điệu cả bài)/F9
(giọng văn/tính đầy đủ cả bài) là thuộc tính TOÀN BÀI, 1 lần rewrite Sonnet khó đảm bảo đồng
thời giữ mọi thứ khác VÀ sửa đúng thuộc tính lan toả đó — nhất là khi piece dài (blog, nhiều
section được viết ở các batch E2 khác nhau, repair chỉ thấy 1 bản chốt, không thấy quá trình).

## Giả thuyết D — ngưỡng all-or-nothing quá khắt khe

**Kết luận: XÁC NHẬN — bằng chứng định lượng rất rõ, đặc biệt nghiêm trọng ở TikTok.**

`status` (pass/flagged/manual_check) là **quyết định RIÊNG của LLM**, không phải code tính từ
AND của các field điểm — code chỉ đọc `data.get("status")` trực tiếp. Nghĩa là "all-or-nothing"
không phải 1 threshold trong code có thể nới — nó là judgment nội tại của LLM, tách biệt hoàn
toàn khỏi các field điểm 1/0 nó cũng phải điền.

**Bằng chứng cụ thể — TikTok là trường hợp nặng nhất, gần như hỏng hoàn toàn về mặt thiết kế:**
- TikTok chỉ có 2 field điểm: `hook_strength`, `cta_clear` — **KHÔNG có field nào đo "brand
  voice" hay "generic wording" cả.**
- **21/21 piece TikTok bị fail (status=flagged) đều có CẢ 2 field = 1/1 (điểm tuyệt đối)** —
  100% trường hợp. Lý do fail luôn là `GENERIC_AI_WORDING`/`SUMMARY_OFF_BRAND` — 2 code
  **không hề có field điểm tương ứng trong rubric TikTok**, hoàn toàn là phán đoán tự do của
  LLM, không bị ràng buộc bởi bất kỳ số liệu nào trong chính response nó vừa điền.
- TikTok **0/? pass** trong toàn bộ 69 piece — không một piece TikTok nào từng pass.
- Facebook (3 field) khá hơn — không có ca "3/3 điểm tuyệt đối mà vẫn fail" nào — field điểm ở
  đây có tương quan thật với status.
- Blog (5 field): case gần nhất là 4/5 (9 lần) — 1 field không đạt là plausible ảnh hưởng thật,
  không có ca 5/5-mà-vẫn-fail nào quan sát được.

**Kết luận D: đúng, nhưng chỉ nghiêm trọng ở TikTok** — rubric TikTok về mặt cấu trúc không thể
đo được thứ quyết định số phận của nó. Facebook/blog ít bị vấn đề này hơn.

---

## Bức tranh tổng hợp — "F9 có những gì"

### 1. Toàn bộ failure_codes

**Blog (`gate_brand_seo_audit`, 5 field điểm + `BRAND_SEO_FAILURE_CODES`, 10 code):**

| Code | Cơ chế | Ý nghĩa |
|---|---|---|
| `PRODUCT_TRUTH_RISK` | LLM | Rủi ro sai sự thật sản phẩm — **chưa từng trigger (0 lần)** |
| `SUMMARY_OFF_BRAND` | LLM tự do, không field riêng | Vi phạm required/forbidden word hoặc trái voice attribute |
| `BODY_EXPERIENCE_DETAILS_TOO_GENERIC` | LLM tự do | Thiếu chi tiết cụ thể — **đáng lẽ atom-density (det.) bắt được** |
| `BODY_DAY_FLOW_STRUCTURE_WEAK` | LLM tự do | Mạch ngày yếu (chỉ blog) |
| `BODY_OPENING_TITLE_WEAK` | LLM tự do | Mở bài yếu |
| `BODY_SUMMARY_LINE_INCOMPLETE` | LLM tự do | Dòng tóm tắt chưa hoàn chỉnh |
| `DFS_INTENT_UNDERUSED` | LLM tự do | Chưa khai thác đúng search intent |
| `KEYWORD_STUFFING_RISK` | LLM tự do | Nhồi từ khoá |
| `GENERIC_AI_WORDING` | LLM tự do, không field riêng | Văn phong AI chung chung — bắt buộc trích `flagged_phrases` (fix #3) |
| `FACT_CHECK_MANUAL_CHECK` | LLM tự do | Cần review tay — **chưa từng trigger (0 lần)** |

**Social (`gate_brand_seo_audit_social`, facebook 3 field / tiktok 2 field, 5 code):**
`SUMMARY_OFF_BRAND`, `CTA_MISSING_OR_WEAK`, `HOOK_WEAK`, `GENERIC_AI_WORDING`,
`FACT_CHECK_MANUAL_CHECK` (0 lần trigger).

### 2. Tần suất thật, 69 piece / 6 lần chạy (đếm mỗi lần code xuất hiện trong `failure_codes`)

| Code | Tổng | Blog | Facebook | TikTok |
|---|---:|---:|---:|---:|
| `SUMMARY_OFF_BRAND` | **52** | 13 | 20 | 19 |
| `GENERIC_AI_WORDING` | **50** | 9 | 18 | 23 |
| `BODY_EXPERIENCE_DETAILS_TOO_GENERIC` | 22 | 22 | – | – |
| `BODY_SUMMARY_LINE_INCOMPLETE` | 19 | 19 | – | – |
| `BODY_DAY_FLOW_STRUCTURE_WEAK` | 18 | 18 | – | – |
| `BODY_OPENING_TITLE_WEAK` | 13 | 13 | – | – |
| `DFS_INTENT_UNDERUSED` | 10 | 10 | – | – |
| `CTA_MISSING_OR_WEAK` | 6 | – | 6 | – |
| `KEYWORD_STUFFING_RISK` | 5 | 5 | – | – |
| `HOOK_WEAK` | 4 | – | 2 | 2 |

**Điều chỉnh lại framing trước đó (từ báo cáo run 5):** nhìn narrative text dễ nghĩ blog fail chủ
yếu vì "generic AI wording" — nhưng nhìn code THẬT, blog fail chủ yếu vì **4 code
`BODY_*` (72/109 = 66% tổng code-occurrence của blog)** — về tính đầy đủ/cấu trúc từng phần,
KHÔNG phải thuần "giọng văn". `SUMMARY_OFF_BRAND`+`GENERIC_AI_WORDING` chỉ chiếm 20% ở blog —
ngược lại, ở social (facebook+tiktok), 2 code này chiếm gần như toàn bộ (80/85 = 94%). Đây là 2
vấn đề khác nhau về bản chất, không phải cùng 1 hiện tượng.

### 3. Cấu trúc lời gọi

- Model: Nova Pro (`us.amazon.nova-pro-v1:0`), acc2, `temperature=0`, `max_tokens=2048`.
- System prompt (dùng chung F8+F9): *"You are a structural editor. You score writing against a
  fixed rubric — you do not rewrite, you do not soften scores... You have not seen and do not
  know how this piece was generated."*
- `status` KHÔNG được code tính từ field điểm — LLM tự quyết định trực tiếp.
- `flagged_phrases` bắt buộc (fix #3, PR #155) khi dùng `SUMMARY_OFF_BRAND`/`GENERIC_AI_WORDING`
  — cơ chế evidence THẬT SỰ hoạt động đúng (xác nhận qua data: mọi flag loại này đều có quote
  thật, đúng nguyên văn trong `body_tagged`).
- `_GENERIC_AI_WORDING_ANCHOR` (fix #2): 1 câu BAD (superlative rỗng) + 1 câu GOOD (Gyeongju
  bullet train, cụ thể/verifiable) — chỉ phân biệt được 2 trong 3 loại văn phong quan sát được
  (thiếu ví dụ cho loại "suy tư cụ thể-theo-ngữ-cảnh", xem giả thuyết A).

### 4. Chuỗi fix đã áp dụng

| Fix | PR | Giải quyết | Chưa đủ |
|---|---|---|---|
| F8 "ends with CTA" → deterministic | #148 (AA-396) | 4/4→0/9 fail, xác nhận sống | — |
| F3/F8 writer-prompt gaps | #153 | Directive rõ hơn cho variance/AIDA | 0/12 pass — chưa chạm F9 |
| Cross-gate regression fix (piece invariants) | #154 | F8 protection hoạt động đúng | 0/3 — F9 vẫn dominant |
| F9 fix #2 (concrete anchor) + #3 (blog evidence) | #155 | flagged_phrases hoạt động thật, TikTok flag hẹp lại 1-phrase | Blog vẫn 0/12 — anchor chưa đủ phân biệt loại 3 |
| F9 fix #1 (brand rubric thật vào JUDGE) | #158 | Blog pass lần đầu (1/12), TikTok flag narrower | **Writer/repair KHÔNG nhận rubric mới** (phát hiện hôm nay) — có thể là lý do chính chưa cải thiện thêm |

---

## Đề xuất hướng (KHÔNG tự code — chờ Nghiệp quyết)

Xếp theo mức độ tin cậy bằng chứng, không phải mức độ dễ làm:

1. **Wire `brand_rubric_text` thật vào E2/E3/E5 (writer + repair), không chỉ F9 judge.**
   Bằng chứng trực tiếp nhất, rủi ro thấp nhất (chỉ đổi 1 hằng số truyền vào, không đổi logic
   gate nào) — closes đúng cái gap fix #1 mới hé lộ. Có khả năng cao nhất cải thiện blog thật,
   vì đây là lần đầu tiên writer/repair thực sự thấy nội dung rubric cụ thể mà judge đang chấm.

2. **Build atom-density validator (deterministic, không LLM) như gate riêng hoặc pre-check của
   F9** — đúng tinh thần spec gốc (tầng #1, cao nhất leverage). Rẻ, nhanh, không thêm Bedrock
   call. Trực tiếp giảm tải cho F9 ở đúng code hay trigger nhất (`BODY_EXPERIENCE_DETAILS_TOO_
   GENERIC`, 22 lần).

3. **Sửa TikTok rubric** — thêm field điểm thực sự đo "generic/brand voice" (thay vì chỉ
   hook_strength/cta_clear rồi tự do phán riêng ngoài field), hoặc bỏ hẳn GENERIC_AI_WORDING/
   SUMMARY_OFF_BRAND khỏi social nếu không có field tương ứng — tránh tình trạng 100% fail dù
   điểm tuyệt đối.

4. **Mở rộng `_GENERIC_AI_WORDING_ANCHOR`** thêm ví dụ loại thứ 3 (suy tư/reflective cụ thể theo
   ngữ cảnh thật, không phải factual thuần nhưng cũng không phải templated filler) — dựa trên
   piece 3 (17 flag) làm case study thật.

5. **Cân nhắc KHÔNG dùng repair.py cho F3/F9** (2 gate whole-piece, tỷ lệ sửa <3%) — thay bằng
   giữ nguyên/hold trực tiếp sau round 1 thất bại (tiết kiệm chi phí Sonnet vô ích: 118 lần gọi
   F9-repair chỉ 3 lần thành công), hoặc đổi chiến lược repair cho riêng 2 gate này (per-section
   thay vì whole-piece rewrite — cần thiết kế lại, rủi ro cao hơn, không đề xuất làm ngay).

Không đề xuất merge/code ngay bất kỳ mục nào — đây vẫn là investigation, để Nghiệp/Claude Chat
quyết định hướng trước 17/08.
