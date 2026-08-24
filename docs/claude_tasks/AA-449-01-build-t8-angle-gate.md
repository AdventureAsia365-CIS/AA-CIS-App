# AA-449 — Build T8 Angle Gate (viết mới hoàn toàn)

## Bước 0 — Merge PR #203 (STEP0 docs) trước khi build
Docs-only, đã đủ thông tin nền — merge trước khi bắt đầu code trên worktree/branch build mới.

## Quyết định đã chốt (round 2, 23/08) — đọc kỹ trước khi code

### 1. Thuật ngữ — dùng ĐÚNG theo SKILL_v2.md, không theo bảng ban đầu Claude Chat đưa nhầm
- **Goal** = tầng 1, 7-8 loại mục đích viết (Promotion/Lead Generation/Conversion/Introduction-
  Awareness/Trust-building/Engagement-Conversation/Event Announcement/Product or Service
  Explanation) — đây là Bảng 1 (writing formulars), field/bảng/route dùng tên `goal`, KHÔNG dùng
  `angle` cho tầng này.
- **Angle** = tầng 2, ĐÚNG 3 phương án cụ thể sinh SAU KHI đã chọn Goal, mỗi angle có đủ 4 trường:
  `name`, `why_it_works`, `formula_fit`, `best_final_style`. Đây mới là thứ tenant chọn ở bước 7
  của workflow (STOP → chờ người chọn).
- Sửa lại đúng chỗ nếu STEP0/investigation notes trước đó lỡ dùng `angle` cho tầng Goal — không để
  lẫn lộn 2 tầng khi đặt tên bảng/cột/route/component.

### 2. Mở rộng `compute_slot_grid()` (T7, `allocator.py`) lên đủ 7 channel — làm TRƯỚC các phần khác
Hiện chỉ hỗ trợ 4 giá trị, cần đủ 7 theo Bảng 2 (writing/channel style): LinkedIn, Facebook,
Instagram, TikTok, Email/Newsletter, Landing Page/Sales Page, Ads. Vì đây là sửa ngược vào code T7
vừa merge (AA-448) — làm cẩn thận:
- Tìm đúng Pydantic model/enum định nghĩa 4 giá trị hiện tại của `Slot.channel`, mở rộng thêm 3.
- Kiểm tra toàn bộ call site khác đang dùng enum/model đó (không chỉ trong `allocator.py`) — có thể
  frontend `PlanningTab.tsx` (T7, vừa build ở AA-448) cũng có logic hiển thị theo channel, cần đồng
  bộ nếu có.
- Tên giá trị enum: đề xuất dùng tên chuẩn hoá dễ dùng trong code (VD `linkedin`, `facebook`,
  `instagram`, `tiktok`, `email`, `landing_page`, `ads`) — khớp với tên trong Bảng 2, không tự bịa
  tên khác.
- **Test bắt buộc:** viết test case tenant cấu hình đủ cả 7 channel, xác nhận `compute_slot_grid()`
  không crash — đây chính là bug thật STEP0 đã cảnh báo (Pydantic ValidationError), phải có test
  cụ thể chặn regression, không chỉ sửa xong là thôi.
- Test hồi quy: xác nhận 4 channel cũ vẫn hoạt động y hệt như trước (không đổi hành vi tenant đang
  dùng 4 channel cũ).

### 3. Time-out chờ chọn Angle — KHÔNG giới hạn thời gian (quyết định tạm)
Build trạng thái "đang chờ tenant chọn Angle" không có cơ chế hết hạn/tự huỷ. Thiết kế schema đủ
linh hoạt để thêm time-out sau (VD có cột `created_at` sẵn để tính tuổi request sau này) nhưng
KHÔNG tự thêm logic time-out/expiry ngay bây giờ.

## Workflow cần build — đúng 7 bước đầu (bước 8-9 KHÔNG thuộc T8, đã xác nhận qua ADR: T9=viết
## content, T10=quality pass)

1. Nhận input: `(atom_id, channel)` — channel đã có sẵn từ `Slot.channel` (T7, sau khi mở rộng ở
   mục 2). Atom lấy title/content seed từ atom đã curate (T6).
2. Trả về danh sách Goal (Bảng 1, 8 loại) cho tenant chọn — endpoint hiển thị, không cần logic gợi
   ý ở bước này (đúng theo workflow gốc, bước 2 chỉ "show danh sách").
3. Tự động lấy "fixed brand audience" — từ `shared.tenant_brand_rules.customer_segment` +
   `customer_mindset` (ĐÃ CÓ, migration 018) — cần build endpoint/hàm expose ra ngoài lần đầu tiên
   (STEP0 xác nhận hiện chỉ bake vào system_prompt, chưa có API tenant-facing).
4. Áp dụng công thức tương ứng Goal đã chọn (tra cột `logic`/`Marketing term` Bảng 1).
5. Sinh đúng 3 Angle cụ thể (dùng LLM — Bedrock Sonnet 4.5, theo đúng exclusive LLM layer đã chốt).
   Mỗi angle đủ 4 trường: `name`, `why_it_works`, `formula_fit`, `best_final_style` (style tra theo
   đúng `channel` đã có từ bước 1, dùng Bảng 2).
6. Đề xuất (`recommended: true`) 1 trong 3 angle mạnh nhất — LLM tự chấm hoặc rule đơn giản, ghi rõ
   cách chọn trong docstring.
7. Trả về 3 angle cho tenant, chờ chọn qua endpoint riêng (`POST .../choose`) — đây là điểm dừng
   thật của T8. Sau khi tenant chọn, `status='approved'`, sẵn sàng cho T9 đọc.

## Schema — thiết kế mới (đề xuất, điều chỉnh nếu thấy hợp lý hơn, không cần hỏi lại nếu chỉ là chi
## tiết implementation không ảnh hưởng khái niệm Goal/Angle đã chốt)

- Bảng mới (đề xuất tên `angle_gate_request` hoặc tương tự — không dùng chữ "angle" cho tầng Goal):
  `id`, `tenant_id`, `atom_id`, `channel`, `goal` (nullable cho tới khi tenant chọn ở bước 2),
  `status` (`pending_goal`/`pending_angle_choice`/`approved`), `created_at`.
- Bảng con `angle_gate_option` (3 dòng cho mỗi request): `id`, `request_id` FK, `name`,
  `why_it_works`, `formula_fit`, `best_final_style`, `recommended` (bool), `chosen` (bool, chỉ 1
  dòng true sau khi tenant chọn).

## API — theo convention `/v1/*` tenant-JWT-only

- `POST /v1/angle-gate/requests` — tạo request mới từ `(atom_id, channel)`.
- `GET /v1/angle-gate/goals` — trả danh sách 8 Goal (Bảng 1, có thể tĩnh, không cần đọc DB).
- `POST /v1/angle-gate/requests/{id}/goal` — chọn Goal, trigger sinh 3 Angle (bước 4-6).
- `GET /v1/angle-gate/requests/{id}` — xem request + 3 angle option (nếu đã sinh).
- `POST /v1/angle-gate/requests/{id}/choose` — tenant chọn 1 angle, chuyển `status='approved'`.

## Frontend

- Route `/portal/t8-angle-gate` (theo đúng convention t0/t1/t4/t6/t7), label "Angle Gate".
- Component hiển thị 3 angle option rõ ràng đủ 4 trường mỗi angle, đánh dấu angle được đề xuất,
  nút chọn.
- Sidebar + breadcrumb: thêm ngay sau "Content Planning" (T7).

## Verify (bắt buộc, theo chuẩn team)

- Test case mở rộng 7 channel như mục 2 đã nêu (bắt buộc, không phải tuỳ chọn).
- Live-verify qua JWT tenant thật: tạo request → chọn goal → nhận đúng 3 angle với đủ 4 trường mỗi
  angle → chọn 1 angle → xác nhận `status='approved'` phản ánh đúng ngay trong response (nhớ bug
  round trước ở AA-448: response không đồng bộ với DB sau khi ghi — kiểm tra kỹ lại pattern này ở
  đây, đừng lặp lại).
- Xác nhận "fixed brand audience" lấy đúng dữ liệu thật của tenant (không phải giá trị mặc định).

## Không thuộc scope này

- T9 (viết content thật) — issue riêng, chưa tạo.
- Time-out cho trạng thái chờ chọn — để sau.
- Redesign UI Marketplace/Content Planning hiện có.

## Nhắc

- Lưu task prompt này vào `docs/claude_tasks/` trước khi bắt đầu.
- Nếu phát sinh câu hỏi kiến trúc thật sự (không phải chi tiết implementation), dừng lại hỏi —
  nhưng cố gắng gộp thành ít vòng nhất có thể.
- Dùng git worktree riêng cho task build này.
