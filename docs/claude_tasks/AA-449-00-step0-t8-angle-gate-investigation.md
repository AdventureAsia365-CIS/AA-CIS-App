# AA-449 — STEP0 Investigate: T8 Angle Gate viết mới hoàn toàn

## Bối cảnh (đã xác nhận, không cần điều tra lại)

- T7 (Content Planning, AA-448) vừa hoàn tất — merged, deployed, verified. T7 output: `year_plan`
  (Shape 1) bọc 4 `quarter_plan`/`quarter_plan_version`, mỗi quý có trip đã chọn (từ Marketplace,
  tenant-scoped) + `compute_slot_grid()` phân bổ atom vào slot theo tháng/tuần.
- Quyết định trước phiên: T8 viết mới hoàn toàn, dùng **`SKILL_v2.md` gốc** (nghiên cứu Ms. Thư) làm
  tài liệu tham chiếu — KHÔNG tái dùng code `acp_s4_social` cũ.
- Bài học từ AA-448 (round 5): khi có nghiên cứu gốc, LUÔN đối chiếu trước khi tự thiết kế — nghiên
  cứu gốc có thể đã có câu trả lời đúng (như cadence quý/tháng đã khớp sẵn), hoặc phạm vi hẹp hơn
  giả định ban đầu (như feedback loop chỉ chỉnh atom.weight, không sửa quarter plan). Áp dụng đúng
  cách tiếp cận này cho T8 — đọc `SKILL_v2.md` KỸ trước khi đề xuất bất kỳ thiết kế nào.

## Workflow đầy đủ (Nghiệp cung cấp trực tiếp — đây là nguồn CHỐT, ưu tiên cao nhất, đối chiếu
## SKILL_v2.md để bổ sung chi tiết còn thiếu, không mâu thuẫn với workflow này)

1. Thu thập title/content seed + channel (kênh nào đã biết trước khi vào T8, không phải T8 tự chọn
   kênh — kênh là input, không phải output T8 sinh ra).
2. Hiện danh sách "goal" (= chính là "Angle" ở bảng 1, cột `Name`) để chọn.
3. Tự động áp dụng "fixed brand audience" (đối tượng thương hiệu cố định của AA — cần tìm xem khái
   niệm này đã có ở đâu trong hệ thống hiện tại, VD có phải liên quan `brand_guide`/`T0 Brand` đã
   có từ trước, hay là 1 giá trị tĩnh mới cần định nghĩa).
4. Áp dụng công thức (formula) tương ứng với goal đã chọn — tra đúng cột `logic`/`Marketing term`
   trong bảng 1.
5. Tạo ra **3 angle cụ thể** (không phải 1) — mỗi angle áp dụng công thức đã chọn theo cách khác
   nhau trên cùng title/content seed.
6. Đề xuất (recommend) angle mạnh nhất trong 3 angle vừa tạo.
7. **CHỜ NGƯỜI CHỌN** — đây chính là "Gate" thật của T8: không phải AA duyệt (khác Gate B cũ), mà
   là chờ TENANT/người dùng chọn 1 trong 3 angle (có thể chọn theo đề xuất ở bước 6, hoặc chọn khác).
8. Chỉ sau khi người chọn xong mới viết nội dung thật (bước này có thể thuộc T8 hoặc là bước kế
   tiếp T9 — cần xác nhận ranh giới chính xác khi đọc code/SKILL_v2.md).
9. Chạy 1 lượt quality/editor pass nội bộ sau khi viết xong.

### Mỗi angle hiển thị PHẢI có đủ 4 trường (yêu cầu cụ thể của Nghiệp — không được thiếu trường nào):
- **Name** — tên/nhãn ngắn gọn của angle này
- **Why it works** — lý do angle này phù hợp (giải thích ngắn, có căn cứ)
- **Formula fit** — công thức marketing áp dụng (từ cột `Marketing term`/`logic` bảng 1, VD AIDA,
  PAS, SLAP, FAB, BAB, 5W1H...)
- **Best final style** — style/structure phù hợp nhất khi viết ra kênh đã chọn (tra từ bảng 2 theo
  đúng `channel` đã thu thập ở bước 1)

## Nguồn tham chiếu — 2 bảng gốc từ Google Sheet

Đây là nguồn chính xác nhất cho khái niệm "Angle" và "Channel style" — ưu tiên đối chiếu 2 bảng này
cùng với `SKILL_v2.md` khi viết STEP0, vì chúng có thể là bản cập nhật mới hơn hoặc bổ sung cho
`SKILL_v2.md`.

### Bảng 1 — Angle (7 loại, mỗi atom/slot cần gán đúng 1 angle)

| Name | description | logic | Marketing term |
|---|---|---|---|
| Promotion | Quảng bá điểm đến/route/trip/ưu đãi/launch/campaign | Attention-Interest-Desire-Action | AIDA |
| Lead Generation | AIDA nếu offer tích cực; PAS nếu nỗi đau là lập kế hoạch quá tải, trip chung chung, route kém, đông đúc, bất định | Problem-Agitate-Solve | AIDA hoặc PAS |
| Conversion | Đẩy người đọc tới enquiry/booking/waitlist/consultation/purchase | Stop-Look-Act-Purchase | SLAP |
| Introduction / Awareness | Giới thiệu quốc gia/điểm đến/route style/xu hướng/quan điểm AA | Hook-Insight-CTA | Hook-Insight-CTA hoặc 5W1H |
| Trust-building | Xây niềm tin vào năng lực thiết kế route của AA | Problem-Insight-Proof-Action (Proof phải cụ thể, KHÔNG bịa claim) | FAB |
| Engagement / Conversation | Mời comment/share/save/thảo luận | Hook-Value-CTA (câu hỏi có căn cứ) | BAB |
| Event Announcement | Thông báo hội chợ/sự kiện/launch/Web Summit/gặp supplier/đối tác | What-Why-Who-Where/When-Why AA có mặt-CTA | 5W1H + AIDA |
| Product or Service Explanation | Giải thích AA làm gì, dịch vụ trip, itinerary design, supplier curation, partner portal, năng lực AI/data | Feature-Advantage-Benefit | FAB |

### Bảng 2 — Channel style (7 kênh, mỗi angle khi viết ra 1 kênh cụ thể phải theo đúng structure/style/điều cấm riêng)

| Channel | Dùng khi | Structure | Style | Tránh |
|---|---|---|---|---|
| LinkedIn | Thought leadership, founder voice, B2B/investor/partner, premium positioning | Hook insight→đoạn ngắn→1 insight rõ→AA positioning→CTA nhẹ/reflective | professional, calm, insight-led, editorial, premium không kiêu | emoji nhiều, travel copy chung chung, hard sell, liệt kê itinerary dài, storytelling quá cảm xúc, cliché ("hidden gem", "bucket list", "paradise awaits") |
| Facebook | Engagement, giới thiệu điểm đến, community trust, soft promotion | Mở ấm-cụ-thể→cảm giác điểm đến+chi tiết cụ thể→ý tưởng trip thực tế→vì sao hợp audience AA→CTA thân thiện | human, warm, clear, travel-led, thoải mái hơn LinkedIn | corporate tone, "discover paradise" chung chung, quá nhiều fact thiếu cảm xúc, wording rẻ tiền, ngôn ngữ cảnh quan mơ hồ |
| Instagram | Visual inspiration, mood điểm đến, brand awareness, engagement ngắn | Hook giác quan ngắn→dòng dễ lướt→3-5 chi tiết cụ thể→AA positioning nhẹ→CTA đơn giản | visual, precise, sensory, minimal, elegant | đoạn dài, caption mơ hồ, nhồi hashtag, tính từ chung chung, ngôn ngữ quá kịch |
| TikTok | Attention ngắn, tò mò, giáo dục, reframe điểm đến | Câu mở sắc→setup nói chuyện đơn giản→3 điểm nhanh→tò mò không clickbait→direction hình ảnh (tuỳ chọn) | direct, clear, conversational, fast-moving, useful | hook viral rẻ tiền, phóng đại nguy hiểm, urgency giả, luxury flexing, thuật ngữ travel phức tạp |
| Email / Newsletter | Nurture, trust-building, giải thích sản phẩm, thông báo trip, gợi ý theo mùa, đối tác | Subject rõ→mở đầu bình tĩnh→1 ý chính→giải thích editorial hữu ích→1 CTA rõ | personal nhưng polished, calm, useful, trust-building, editorial | quá nhiều link, quá nhiều CTA, ngôn ngữ promo chung chung, block text dài, urgency giả |
| Landing Page / Sales Page | Conversion, giải thích sản phẩm, campaign landing, trang điểm đến/trip | Value prop rõ→đối tượng phù hợp→vì sao điểm đến/trải nghiệm này quan trọng→AA xử lý gì→trust signal/process→CTA rõ | precise, benefit-led, premium, grounded, dễ scan | overwriting, luxury claim chung chung, superlative không có bằng chứng, itinerary detail rối, quá nhiều brand philosophy trước khi giải thích offer |
| Ads | Lead gen, retargeting, quảng bá điểm đến, test campaign | 1 hook rõ→1 benefit theo audience→1 điểm khác biệt AA→1 CTA | clear, specific, benefit-led, calm nhưng thuyết phục | clickbait, slogan travel chung chung, quá nhiều ý trong 1 ad, urgency không có căn cứ, over-promise |

## Việc cần làm — CHỈ ĐIỀU TRA, KHÔNG SỬA CODE

### 1. Đọc kỹ `SKILL_v2.md` gốc — phần liên quan Angle Gate
- Đối chiếu 2 bảng trên với `SKILL_v2.md` — bảng nào khớp, bảng nào là bổ sung/cập nhật mới hơn.
  Nếu `SKILL_v2.md` có phiên bản khác 2 bảng này, ưu tiên bảng Nghiệp vừa cung cấp (mới hơn), nhưng
  NÊU RÕ sai khác nếu có, không âm thầm ghi đè.
- "Angle" trong ngữ cảnh này nghĩa là gì chính xác (góc độ nội dung/content angle cho 1 atom hoặc
  1 slot — VD: "gia đình" vs "phiêu lưu" vs "sang trọng" cho cùng 1 điểm đến)? Trích đúng định nghĩa
  từ tài liệu gốc, không tự suy diễn.
- Angle Gate có vai trò gì trong toàn chuỗi — duyệt góc trước khi viết nội dung thật? Ai/cơ chế nào
  từng gate nó theo thiết kế gốc (con người, rule-based, LLM-judged)?
- Input của Angle Gate là gì theo thiết kế gốc (atom? slot đã có từ T7? trip?) — Output là gì (angle
  đã gán, sẵn sàng cho bước viết content tiếp theo)?
- Có công thức/tiêu chí chấm điểm cụ thể nào không (giống cách `compute_quarter_plan` có công thức
  trọng số) — nếu có, trích chính xác.

### 2. Đọc lại `docs/claude_audit/AA-447-01-sync-audit-matrix.md`
- Trích đúng phần mô tả tình trạng T8 hiện tại (route/sidebar/backend) để đối chiếu với AA-449.

### 3. Tìm code liên quan hiện có (ngoài `acp_s4_social` đã loại trừ theo quyết định)
- Grep toàn repo tìm "angle" (không phân biệt hoa thường) trong `services/`, `api/routers/` — liệt
  kê mọi chỗ tìm thấy, xác định cái nào thuộc `acp_s4_social` (loại) vs cái khác (có thể tham khảo).
- Kiểm tra xem AA-309 (N1 Onboard, có "gán góc"/Gate A theo tên issue cũ) có liên quan tới Angle Gate
  T8 này không, hay là 1 khái niệm "gate" khác ở giai đoạn onboard (nhắc trong tên issue: "gán góc ·
  Mirror · Gate A") — làm rõ Gate A (onboard, N1) và Angle Gate (T8) có phải cùng 1 cơ chế tái dùng
  hay là 2 thứ khác nhau hoàn toàn dùng chung từ "angle/gate".

### 4. Gate = chờ người chọn, KHÔNG PHẢI AA duyệt — đã CHỐT theo workflow trên, không còn là câu hỏi mở
Xác nhận cơ chế "chờ người chọn" (bước 7 workflow) implement thế nào về mặt kỹ thuật:
- Người chọn ở đây là AI (agent) hay TENANT (con người thật qua UI)? Workflow ghi "human choice" —
  cần xác nhận đây là tenant end-user thật, không phải 1 bước AI tự động khác đóng vai "human".
- Trạng thái "đang chờ chọn" cần lưu ở đâu (bảng mới, hay field trên `acp_v2_slots` hiện có)?
- Có time-out hay giới hạn nào nếu tenant không chọn không (VD giữ 3 angle bao lâu trước khi cần
  làm lại)? Nếu SKILL_v2.md không nói, đánh dấu là câu hỏi mở thật.

### 5. Input/output — 1 atom sinh N piece theo N kênh, đã CHỐT theo workflow bước 1
Workflow bước 1 xác nhận: **channel là INPUT đã biết trước khi vào T8**, không phải T8 tự chọn kênh.
Vậy cấu trúc đúng là: mỗi (atom, channel) là 1 "content generation request" độc lập chạy qua toàn bộ
workflow 9 bước — không phải 1 atom chạy 1 lần rồi tự nhân ra N kênh. Xác nhận:
- `compute_slot_grid` (T7) hiện tại có sinh sẵn field `channel`/`platform` cho mỗi slot chưa, hay
  T8 là nơi ĐẦU TIÊN cần thêm khái niệm channel vào pipeline?
- Nếu 1 slot T7 cần ra nhiều kênh (VD cùng 1 tuần, 1 atom viết cả Facebook lẫn Instagram) — slot đó
  có tự nhân bản thành N request T8 không, theo cơ chế nào (do `compute_slot_grid` sinh sẵn N dòng,
  hay do tenant tự bấm "tạo thêm cho kênh khác" tại T8)?

### 6. "Fixed brand audience" — tìm nguồn dữ liệu đã có
Workflow bước 3 nói "tự động áp dụng fixed brand audience" — tìm xem khái niệm này đã tồn tại ở đâu:
- `brand_guide`/T0 Brand (đã build, tenant upload brand guide ở T0) có chứa audience definition
  không? Hay đây là 1 giá trị TĨNH chung cho toàn AA (không theo tenant), cần định nghĩa mới?
- Nếu chưa có nguồn nào, đánh dấu rõ đây là input còn thiếu, cần Nghiệp/Ms. Thư cung cấp trước khi
  build được bước 3 của workflow.

### 7. Route/tên T8
- Đề xuất tên route theo đúng convention đã dùng: `/portal/t0-brand`, `/portal/t1-rewrite`,
  `/portal/t4-pool`, `/portal/t6-atoms`, `/portal/t7-planning`.

## Deliverable

1 file audit mới: `docs/claude_audit/AA-449-00-step0-t8-angle-gate-investigation.md` — liệt kê đầy
đủ 7 mục trên, kèm:
- Trích dẫn/tóm tắt chính xác phần liên quan của `SKILL_v2.md` (không diễn giải sai lệch)
- Danh sách code cũ có thể tham khảo vs. phải viết mới hoàn toàn
- Đề xuất tên route + cấu trúc endpoint
- Câu hỏi mở còn thật sự treo (KHÔNG lặp lại câu đã có đáp án từ workflow — VD "self-service hay
  gate" đã trả lời rõ là "chờ người chọn"): ranh giới chính xác T8 kết thúc ở đâu/T9 bắt đầu ở đâu
  (bước 8-9 thuộc T8 hay đã là stage khác), cơ chế time-out cho "đang chờ chọn" nếu có, nguồn dữ
  liệu "fixed brand audience" nếu chưa tìm thấy.

**KHÔNG build gì trong task này.**

Lưu prompt task này vào `docs/claude_tasks/` theo đúng quy trình (skill ai-nghiep §2.1).
