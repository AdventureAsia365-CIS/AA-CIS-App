[Ghi chú phục dựng: bản chat gốc gửi phiên Claude Code trước đã mất theo `/clear`, không nằm
trong context phiên ghi file này. Nội dung dưới đây ghép từ 2 nguồn Linear thật (qua MCP
`get_issue`/`list_comments`): (1) issue description gốc (STEP0 request), (2) comment "chốt thiết
kế" của Nghiệp lúc 01/09 04:06:48 UTC — đúng thời điểm "giao build prompt" theo lời chính comment
đó. Không đảm bảo khớp 100% byte cho byte với prompt đã gõ vào chat, nhưng là nội dung thật của
quyết định đã chốt, không suy diễn.]

---

# [T5] Atom identity content-hash + cache theo ngày + partial commit — issue description gốc

## Bối cảnh

Sub-issue của AA-507 (epic redesign T5-T11 theo repo Ms. Thư). Đây là bước đầu tiên bắt buộc —
Segment/Route (sub-issue sau) cần `atom_id` ổn định qua re-run mới hoạt động đúng.

## STEP0 bắt buộc trước khi thiết kế cụ thể

1. Đọc `services/acp_shared/atom_extraction.py` (module tách ra từ `v1_atoms.py` trước khi xoá,
   AA-475) — xác nhận `atom_id` hiện sinh theo cách nào (UUID/tuần tự hay đã content-derived).
2. Xác nhận cột `tour_atoms.source_hash` đang được ghi nhưng có ai ĐỌC LẠI để so sánh/skip không,
   hay chỉ lưu suông.
3. Xác nhận `run_t5_atomize()` commit theo batch-toàn-bộ hay theo từng phần (1 ngày lỗi có làm
   mất công các ngày đã xử lý đúng không).

## Thiết kế tham chiếu (repo Ms. Thư)

`src/aa_social/models.py::atom_id()` — `hash(trip_code, day, place, action)`, chuẩn hoá text
trước khi hash. `README.md` phần "atom reads a day only when that day changed" — ghi fingerprint
(nội dung ngày + prompt + model), 206 ngày cache nóng chạy 3 giây thay vì 69 giây/$1.44.

## Việc cần làm (tuỳ kết quả STEP0)

* Đổi cách sinh `atom_id` sang content-hash nếu hiện tại chưa vậy — **bắt buộc**, không tuỳ chọn.
* Bảng mới `acp_contract.atomize_day_fingerprint (tenant_tour_version_id, day_number,
  fingerprint_hash, atomized_at)` nếu `source_hash` chưa đủ dùng cho skip-unchanged.
* Đổi `run_t5_atomize()` sang commit từng ngày nếu hiện đang batch-toàn-bộ.

## Không đổi

Cách LLM decompose 1 ngày thành atom (place+action) — chỉ đổi định danh + khi nào chạy lại, không
đổi cách trích xuất.

## Tham chiếu

ADR-2026-040. Epic: AA-507.

---

## Thiết kế cuối AA-508 — chốt sau 2 vòng STEP0 (comment Linear, 01/09 04:06:48 UTC, Nghiệp)

**Thiết kế cuối AA-508 — chốt sau 2 vòng STEP0 (chính + đối chiếu repo Ms. Thư thật). Sẵn sàng
build.**

**STEP0 chính** (`AA-508-step0-atom-identity-investigation.md`): atom_id hiện tại random UUID
(`tenant_pipeline.py:320`), không content-derived. `source_hash` có ghi+đọc nhưng granularity
per-tour (không phải per-day) — 1 ngày đổi làm re-atomize cả tour. `run_t5_atomize()` không có
transaction bọc ngoài, nhưng cũng không có khái niệm "ngày" (1 LLM call cho cả itinerary) — nên
"commit per-day" chưa áp dụng được ở kiến trúc hiện tại.

**STEP0b đối chiếu repo Ms. Thư thật** (`AA-508-step0b-upsert-vs-new-verification.md`) — trả lời
câu hỏi treo UPSERT vs always-new bằng trích dẫn code trực tiếp, không suy luận:
- Công thức: `sha256(trip_code|day|normalise(place)|normalise(action))[:16]` — không hash
  `evidence`.
- Cơ chế ghi: UPSERT thật (`ON CONFLICT(atom_id) DO UPDATE`), không phải insert-mới-rồi-dọn-rác.
- **Phát hiện quan trọng nhất:** content-hash tự thân KHÔNG miễn nhiễm non-determinism của LLM —
  repo tự đo khi bị ép gọi lại LLM dù input giống hệt, chỉ 41% atom_id giữ nguyên (383/931), 59%
  đổi vì model diễn đạt lại khác đi. Ổn định thật sự đến từ **fingerprint-skip chặn được lệnh gọi
  LLM**, không phải bản thân hash.

**3 quyết định đã chốt với Nghiệp (01/09):**
1. **Công thức atom_id:** copy đúng nguyên văn
   `sha256(trip_code|day|normalise(place)|normalise(action))[:16]`, không hash evidence.
2. **`atomize_day_fingerprint` phải CHẶN gọi LLM thật** (skip hẳn ngày fingerprint khớp, không
   gọi lại) — không phải chỉ ghi log sau khi đã gọi. Đây là điều kiện bắt buộc để atom_id thực sự
   ổn định qua re-run, đúng bài học từ repo Ms. Thư.
3. **FK CASCADE cho bảng con trỏ tới `tour_atoms.atom_id`** (angle_gate_request, content_piece,
   usage_log...) — CHƯA CHỐT, cần Claude Code liệt kê đầy đủ bảng nào FK thật tới `atom_id` trước
   khi quyết có thêm `ON DELETE CASCADE` hay không (rủi ro cao nếu thiếu thông tin, để trong
   STEP0 build, không tự quyết trước).

**Scope build (thứ tự phụ thuộc):**
1. `run_t5_atomize()`: đổi kiến trúc gọi LLM từ 1-lệnh-cho-cả-tour sang xử lý/gọi theo từng ngày
   (điều kiện tiên quyết cho mọi thứ sau).
2. Migration bảng `acp_contract.atomize_day_fingerprint (tenant_tour_version_id, day_number,
   fingerprint_hash, atomized_at)` — dùng để skip/chặn gọi LLM cho ngày không đổi.
3. Đổi `atom_id` generation sang content-hash theo công thức đã chốt, UPSERT keyed trên `atom_id`
   (`ON CONFLICT(atom_id) DO UPDATE`) thay cho so `source_hash` cấp-tour hiện tại.
4. STEP0 riêng (trong lúc build, trước khi viết migration cascade): liệt kê toàn bộ bảng FK tới
   `tour_atoms.atom_id`, báo cáo lại để Nghiệp quyết cascade — chưa tự thêm.
5. `source_hash` cấp-tour hiện có: giữ lại làm fallback/audit, không xoá.

Không đổi: cách LLM decompose atom (place+action) — chỉ đổi định danh + khi nào chạy lại.
