# AA-450 — STEP0 Investigate: T9 Content Writing viết mới

## Bối cảnh (đã xác nhận, không cần điều tra lại)

- T7 (Content Planning, AA-448) và T8 (Angle Gate, AA-449) đã merged/deployed/verified. Task def
  hiện tại `aa-cis-dev-api:130`.
- T8 output: bảng `angle_gate_request` (status='approved' khi xong) + `angle_gate_option` (3 dòng,
  đúng 1 dòng `chosen=true`) — mỗi request có `tenant_id`, `atom_id`, `channel`, `goal`, và angle đã
  chọn có đủ `name`/`why_it_works`/`formula_fit`/`best_final_style`.
- Thuật ngữ đã chốt ở AA-449: **Goal** (tầng 1, mục đích) khác **Angle** (tầng 2, phương án cụ thể)
  — dùng đúng 2 từ này khi đọc/viết STEP0, không lẫn lộn.
- LLM layer: Bedrock Sonnet 4.5 qua `LLMClient` (cùng layer AA-449 dùng, có fallback acc2→acc3 khi
  channel-program-account lỗi — đã xác nhận hoạt động đúng thiết kế ở AA-449, không phải bug).
- Bài học từ AA-448/AA-449: LUÔN đối chiếu `SKILL_v2.md` gốc trước khi tự thiết kế; kiểm tra kỹ
  response có đồng bộ với DB ngay sau khi ghi (2 bug đã gặp ở AA-448/không lặp lại ở AA-449 vì đã
  chủ động kiểm tra).

## Câu hỏi quan trọng cần trả lời trước tiên — ranh giới T9/T10

Workflow gốc Nghiệp cung cấp (dùng cho AA-449, có liên quan T9):
- Bước 8: viết nội dung thật, CHỈ SAU KHI người đã chọn 1 angle (T8 xong).
- Bước 9: chạy 1 lượt quality/editor pass **nội bộ**.

ADR-2026-038 gọi T10 là "quality pass" (theo tên A/T-series). Cần xác định: bước 9 (quality/editor
pass NỘI BỘ, ngay sau khi viết xong, KHÔNG phải bước duyệt/gate riêng) có phải chính là T10, hay là
1 bước phụ trong T9 (self-correction ngay trong cùng 1 lần gọi LLM/workflow), còn T10 là 1 gate
riêng biệt (có thể liên quan tenant duyệt, hoặc AI-judged) tách khỏi việc viết? Đọc kỹ ADR + tìm bất
kỳ mô tả nào về T10 trong tài liệu có sẵn (`AA-447-01-sync-audit-matrix.md`, ADR bảng stage) để trả
lời — nếu tài liệu không đủ rõ, nêu thành câu hỏi mở, không tự đoán.

## Việc cần làm — CHỈ ĐIỀU TRA, KHÔNG SỬA CODE

### 1. Đọc kỹ `SKILL_v2.md` gốc — phần viết content thật
- Input chính xác cần những gì: atom (nội dung/dữ liệu tour gốc), goal, angle đã chọn (4 trường),
  channel (quyết định structure/style theo Bảng 2 kênh đã dùng ở T8), fixed brand audience
  (`tenant_brand_rules.customer_segment/customer_mindset`, đã expose qua T8).
- Output là gì — draft thô cần người sửa tiếp, hay nội dung hoàn chỉnh sẵn sàng cho bước tiếp theo
  (T10 quality pass, hoặc thẳng tới T11 publish nếu T10 không tồn tại như 1 gate riêng)?
- Có công thức/cấu trúc bắt buộc nào khi viết không (ngoài Formula fit + Best final style đã có từ
  T8) — VD độ dài tối đa/tối thiểu theo kênh, format đặc biệt (hashtag, line break, CTA vị trí)?
- Bước "quality/editor pass nội bộ" (bước 9) — SKILL_v2.md mô tả cụ thể thế nào (tiêu chí gì, có
  phải LLM tự review lại chính output của nó, hay có checklist riêng)?

### 2. Tìm code cũ liên quan
- Grep repo tìm phần viết content xã hội cũ (có thể trong `acp_s4_social`, nhưng theo ADR §0.5 đã
  chốt KHÔNG tái dùng trực tiếp — chỉ xem có business logic thuần nào đáng tham khảo, giống cách
  đã làm ở T7 với `quarter.py`/`allocator.py`).
- Kiểm tra `content_generation/graph.py` (đã nhắc trong báo cáo AA-449 là nơi `LLMClient` hiện có
  đang dùng) — có sẵn logic viết content nào tái dùng được cho T9 không, hay chỉ là hạ tầng gọi LLM
  chung.

### 3. Input thực tế từ T8 (đọc code thật, đã merge — `services/acp_angle_gate/`)
- Xác nhận chính xác schema `angle_gate_request`/`angle_gate_option` (đọc file migration 113 thật).
- T9 nên đọc trực tiếp 2 bảng này, hay cần 1 API/view riêng (tương tự cách T7 dùng Marketplace view
  thay vì query trực tiếp T4/T6)?

### 4. Ranh giới T9/T10 — trả lời câu hỏi đã nêu ở trên, đọc kỹ ADR toàn bộ, không chỉ đoạn liên quan

### 5. Route/tên T9
- Đề xuất theo convention: `/portal/t0-brand`, `/portal/t1-rewrite`, `/portal/t4-pool`,
  `/portal/t6-atoms`, `/portal/t7-planning`, `/portal/t8-angle-gate`.

### 6. Xác nhận LLM layer
- `LLMClient` dùng thế nào cho content generation dài hơn (khác lệnh sinh 3 angle ngắn ở T8) — có
  giới hạn token/cost nào cần lưu ý không, có cần system prompt riêng theo channel không.

## Deliverable

1 file audit mới: `docs/claude_audit/AA-450-00-step0-t9-content-writing-investigation.md` — liệt kê
đầy đủ 6 mục trên, kèm:
- Trích dẫn/tóm tắt chính xác phần liên quan `SKILL_v2.md`
- Trả lời rõ ranh giới T9/T10 (hoặc nêu là câu hỏi mở nếu tài liệu không đủ)
- Danh sách code cũ tham khảo được vs. viết mới hoàn toàn
- Đề xuất route/tên + cấu trúc endpoint
- Câu hỏi mở cần Nghiệp/Ms. Thư quyết định

**KHÔNG build gì trong task này.**

Lưu prompt task này vào `docs/claude_tasks/` theo đúng quy trình.
