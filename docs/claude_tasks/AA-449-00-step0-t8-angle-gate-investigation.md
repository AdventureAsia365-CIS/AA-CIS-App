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

## Việc cần làm — CHỈ ĐIỀU TRA, KHÔNG SỬA CODE

### 1. Đọc kỹ `SKILL_v2.md` gốc — phần liên quan Angle Gate
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

### 4. Đối chiếu ADR-2026-038 — self-service hay vẫn cần gate?
- ADR §0.2 đã bãi bỏ Gate B (T7) theo hướng self-service hoàn toàn. Kiểm tra ADR có nhắc riêng gì
  về T8/Angle Gate không (đọc lại toàn bộ ADR, không chỉ §0.2) — nếu ADR im lặng về T8, nêu rõ đây
  là khoảng trống cần Nghiệp/Ms. Thư quyết định, không tự suy diễn theo tương tự T7.

### 5. Input/output thực tế từ T7 đã build
- T7 (AA-448) vừa xong — xác nhận chính xác bảng/API nào T8 sẽ đọc làm input (`quarter_plan`,
  `year_plan`, slot đã tính từ `compute_slot_grid`?) bằng cách đọc code T7 thật (branch đã merge),
  không đoán theo mô tả issue.

### 6. Route/tên T8
- Đề xuất tên route theo đúng convention đã dùng: `/portal/t0-brand`, `/portal/t1-rewrite`,
  `/portal/t4-pool`, `/portal/t6-atoms`, `/portal/t7-planning`.

## Deliverable

1 file audit mới: `docs/claude_audit/AA-449-00-step0-t8-angle-gate-investigation.md` — liệt kê đầy
đủ 6 mục trên, kèm:
- Trích dẫn/tóm tắt chính xác phần liên quan của `SKILL_v2.md` (không diễn giải sai lệch)
- Danh sách code cũ có thể tham khảo vs. phải viết mới hoàn toàn
- Đề xuất tên route + cấu trúc endpoint
- Câu hỏi mở cần Nghiệp/Ms. Thư quyết định trước khi build (đặc biệt nếu ADR im lặng về cơ chế gate
  cho T8 — đây rất có thể là 1 câu hỏi mở quan trọng, đừng tự đoán theo tương tự T7)

**KHÔNG build gì trong task này.**
