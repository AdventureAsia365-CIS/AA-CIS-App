# AA-450 — Build T9 Content Writing (viết mới)

## QUAN TRỌNG — task này chia 2 giai đoạn, KHÔNG build thẳng schema/API trước khi xong giai đoạn 1

**Giai đoạn 1 (làm trước, dừng lại xác nhận):** mục 2b bên dưới — điều tra vòng lặp retry T9↔T10 +
vấn đề N7 đã vướng. Trình bày lại cho Nghiệp/Claude Chat, CHỜ xác nhận kiến trúc trước khi động vào
schema `content_piece` hay bất kỳ API nào.

**Giai đoạn 2 (sau khi giai đoạn 1 được xác nhận):** phần còn lại của task — vá CTA, viết
`services/acp_content_writing/`, schema, API, frontend, verify.

## Quy trình PR — THAY ĐỔI từ giờ (áp dụng ngay task này)
KHÔNG mở PR riêng cho docs STEP0 nữa (bài học 23/08, đã ghi vào memory Claude). File
`docs/claude_audit/AA-450-00-...` và task prompt này CHỈ commit trên cùng branch build
(`feature/aa-450-build-t9-content-writing` hay tên bạn đặt) — gộp chung vào đúng 1 PR duy nhất khi
code build xong, không tách PR docs-only nữa. PR #206 (STEP0, đã mở trước khi có quyết định này)
merge bình thường như cũ, không cần làm lại.

## Quyết định đã chốt (23/08, sau STEP0)

### 1. Ranh giới T9/T10 — đã xác nhận qua SKILL_v2.md
Bước 9 (viết) và bước 10 (quality/editor pass) là **2 bước riêng biệt**, không gộp 1 lệnh LLM.
T9 (task này) chỉ làm bước 9 — viết content. T10 (issue riêng, chưa tạo) sẽ làm bước 10.

### 2. T10 sẽ CHẶN tự động (không phải pass vô hại) — ảnh hưởng trực tiếp thiết kế output T9
Quan trọng: T10 không giống Gate B (T7, đã bỏ hoàn toàn) — T10 là **AI/rule tự động chặn**, gần
giống F1-F9 của admin N7 nhưng hoàn toàn tự động (không phải AA con người duyệt, nên không vi phạm
nguyên tắc self-service của ADR §0.2). Nghĩa là:
- Output T9 KHÔNG được coi là final ngay khi viết xong — phải ở trạng thái chờ T10 duyệt.
- Thiết kế bảng lưu output T9 (mục 4 dưới) cần có cột `status` đủ để phân biệt ít nhất
  `draft`/`pending_quality_check` (T9 vừa xong) vs trạng thái sau khi T10 xử lý (để dành, không cần
  build logic T10 thật trong task này, chỉ cần schema đủ chỗ cho T10 gắn vào sau mà không phải
  migrate lại).

### 2b. BẮT BUỘC điều tra trước khi thiết kế schema/API — vòng lặp retry T9↔T10 (Nghiệp yêu cầu,
### đây CHÍNH XÁC là vấn đề admin N7 (F1-F9) từng vướng phải, KHÔNG được lặp lại)

**Dừng lại, đọc kỹ `SKILL_v2.md` gốc trước khi code bất kỳ dòng nào của mục 2/4/5 dưới đây** — tìm
phần mô tả vòng lặp viết→kiểm tra→sửa (nếu T10 chặn ở 1 gate nào đó trong F1-F9-tương-đương, T9 có
phải viết lại không, dựa trên feedback gì, ai/cái gì quyết định "đã sửa đủ chưa").

Cụ thể cần trả lời được:
1. Khi T10 chặn (fail 1 hoặc nhiều gate), feedback đưa NGƯỢC lại T9 dưới dạng gì — lỗi chung chung
   hay chỉ rõ đúng gate nào fail + lý do cụ thể để LLM viết lại sửa đúng chỗ đó (không viết lại từ
   đầu vô nghĩa)?
2. Retry tối đa bao nhiêu lần trước khi dừng hẳn — SKILL_v2.md có con số cụ thể không? Nếu không có
   trong SKILL_v2.md, tìm trong code N7 cũ (`services/acp_produce/` hoặc tương đương chứa F1-F9) —
   họ đã set retry limit bao nhiêu, và **quan trọng hơn: N7 gặp vấn đề gì với cơ chế retry này**
   (đây là điều Nghiệp nhắc — N7 "vướng phải" 1 vấn đề cụ thể, cần tìm ra chính xác là gì: loop vô
   hạn? retry không hội tụ, sửa mãi vẫn fail cùng gate? cost/latency phình to do gọi LLM quá nhiều
   lần? hay vấn đề khác). Đọc kỹ code/comment/bất kỳ ghi chú nào trong `acp_produce`/N7 để xác định
   đúng vấn đề gốc, không đoán.
3. Khi hết số lần retry mà vẫn fail — hệ quả là gì (trả về tenant với cảnh báo? giữ nguyên bản draft
   tốt nhất trong các lần thử? chặn cứng không cho qua T11)? N7 xử lý trường hợp này thế nào, có
   phải đúng chỗ N7 "vướng" không?
4. Vòng lặp này chạy Ở ĐÂU về mặt kiến trúc — trong CÙNG 1 lần gọi API (T9 tự động gọi lại LLM nội
   bộ cho tới khi T10-logic pass hoặc hết retry, rồi mới trả response), hay là 2 API riêng biệt (T9
   viết xong trả draft, T10 chạy async riêng, nếu fail thì tạo lại request T9 mới)? Đề xuất kiến
   trúc cụ thể dựa trên cách SKILL_v2.md mô tả + tránh đúng vấn đề N7 đã vướng.

**Deliverable riêng cho phần 2b này** (viết vào docs local, không cần PR riêng theo quy trình mới):
tóm tắt rõ vòng lặp retry theo SKILL_v2.md + vấn đề N7 đã gặp + đề xuất kiến trúc T9↔T10 tránh lặp
lại vấn đề đó. Trình bày lại cho Nghiệp/Claude Chat xác nhận TRƯỚC KHI viết schema `content_piece`
chính thức (mục 4) — vì cột `status` và cấu trúc bảng có thể cần đổi tuỳ theo kiến trúc retry chọn
(VD cần thêm `attempt_number`, `previous_piece_id` để nối chuỗi các lần thử, hay không cần vì chỉ
giữ lại attempt cuối).

### 3. Vá lỗ hổng CTA — làm TRƯỚC khi build phần viết chính, vì T9 cần input này
`angle_gate_request` (T8, migration 113) thiếu cột `cta`. `Slot.cta_target` (đã tính sẵn ở T7,
`allocator.py`) chưa từng được nối vào lúc tạo request T8. Cần:
- Migration mới: thêm cột `cta` (nullable, để không phá dữ liệu `angle_gate_request` đã có) vào
  bảng `angle_gate_request`.
- Sửa `services/acp_angle_gate/` (nơi tạo request T8) — nối `Slot.cta_target` vào field `cta` mới
  này tại thời điểm tạo request (đọc đúng slot nào tương ứng atom/tenant đang tạo request).
- Dữ liệu `angle_gate_request` đã có từ trước (nếu có) sẽ có `cta=NULL` — T9 cần xử lý null-case
  hợp lý (fallback CTA chung chung theo channel, hoặc báo lỗi rõ ràng yêu cầu tạo lại request mới
  — tự quyết theo bạn thấy hợp lý hơn, ghi rõ lý do).
- Test bắt buộc: tạo request T8 mới sau khi vá, xác nhận `cta` có giá trị thật (không NULL) khi
  slot gốc có `cta_target`.

## Input T9 — đọc trực tiếp qua `service.py::fetch_request()` (T8), không tạo view mới
Theo đúng tiền lệ chính T8 đã đặt ra (T8 đọc T7 qua hàm trực tiếp, không phải view). T9 gọi
`fetch_request()` lấy đủ: atom, goal, angle đã chọn (4 trường), channel, `cta` (mới vá), fixed
brand audience (đã có từ T8, `tenant_brand_rules.customer_segment/customer_mindset`).

## Viết mới — `services/acp_content_writing/` (hoặc tên bạn thấy hợp lý hơn, nêu lý do nếu đổi)

- Đọc tham khảo `acp_s4_social/writer.py` (pre-ADR §0.5, KHÔNG tái dùng trực tiếp) — chỉ tham khảo
  cấu trúc `ContentBrief`/prompt construction logic thuần, viết lại code mới hoàn toàn.
- Gọi `shared.llm_client.client.LLMClient` (`model_tier="sonnet"`) — cùng layer T7/T8 đã dùng, theo
  đúng xác nhận STEP0 (không dùng `acp_produce`'s long-form path — job shape khác, T9 viết 1 piece
  ngắn).
- Input đầy đủ cho prompt: atom content, goal, angle (4 trường), channel (quyết định structure/
  style theo Bảng 2 — đã có trong `channel_style.py` từ T8, tái dùng trực tiếp không viết lại),
  `cta`, fixed brand audience.
- KHÔNG hardcode giới hạn từ theo kênh từ `acp_s4_social/_CHANNEL_RULES` (code cũ không tái dùng) —
  vì STEP0 xác nhận cả SKILL_v2.md lẫn `channel_style.py` thật đều không có con số cụ thể. Nếu cần
  giới hạn độ dài, hỏi lại trước khi tự đặt con số mới không có căn cứ, hoặc để LLM tự quyết theo
  channel style prompt (không ép cứng số từ) — ghi rõ cách bạn chọn.

## Schema mới — bảng lưu output T9 (đề xuất tên `content_piece`, không dùng `acp_deliver.pieces` vì
## STEP0 xác nhận khoá sai — `run_id` của N7 admin, không phải `angle_gate_request`)

- `id`, `tenant_id`, `angle_gate_request_id` FK (khoá đúng theo T8, không lặp lỗi `acp_deliver.pieces`),
  `content_text`, `status` (`draft` khi vừa viết xong — để chỗ cho T10 gắn vào sau), `created_at`.
- Cân nhắc: có cần lưu lại `cta`/`channel`/`goal`/`angle_name` denormalized vào bảng này không (để
  T10/T11 đọc nhanh không cần join lại `angle_gate_request`), hay chỉ cần FK rồi join khi cần — tự
  quyết theo pattern nhất quán với các bảng khác trong hệ thống (VD `tour_atoms` có denormalize gì
  không, theo cho nhất quán).

## API — theo convention `/v1/*` tenant-JWT-only

- `POST /v1/content-writing/requests/{angle_gate_request_id}/write` — trigger viết (đọc T8 output,
  gọi LLM, lưu `content_piece` mới, trả về content).
- `GET /v1/content-writing/pieces/{id}` — xem lại content đã viết.
- (Không cần endpoint "chọn"/"duyệt" trong task này — vì T10 sẽ handle chặn, T9 chỉ viết.)

## Frontend

- Route `/portal/t9-write` (theo đề xuất STEP0), label "Content Writing".
- Component hiển thị content đã viết, kèm goal/angle/channel/CTA đã dùng để viết (để tenant thấy
  rõ ngữ cảnh, dù chưa có nút duyệt — T10 sẽ thêm sau).
- Sidebar/breadcrumb: ngay sau "Angle Gate" (T8).

## Verify (bắt buộc)

- Test vá CTA (mục 3) — bắt buộc, không tuỳ chọn.
- Live-verify qua JWT tenant thật: tạo angle_gate_request mới đủ CTA → trigger viết → xác nhận
  content trả về hợp lý (có nhắc tới CTA, đúng structure/style theo channel đã chọn) → xác nhận
  `content_piece.status='draft'` đúng, không phải final.
- Kiểm tra kỹ lại pattern "response đồng bộ với DB sau khi ghi" (bug đã gặp ở AA-448, không lặp lại
  ở AA-449 — giữ nguyên chuẩn đó ở đây).

## Không thuộc scope này

- T10 (quality pass tự động, có thể chặn) — issue riêng, chưa tạo. Chỉ cần chừa chỗ schema
  (`status`), không build logic T10 thật.
- T11 (publish) — chưa tồn tại.
- Giới hạn độ dài cứng theo kênh — không tự đặt số nếu không có căn cứ.

## Nhắc

- Lưu task prompt này local trong `docs/claude_tasks/` (không tạo PR riêng, gộp vào PR build).
- Dùng git worktree riêng.
- Nếu phát sinh câu hỏi kiến trúc thật sự, dừng lại hỏi — nhưng gộp thành ít vòng nhất có thể.
