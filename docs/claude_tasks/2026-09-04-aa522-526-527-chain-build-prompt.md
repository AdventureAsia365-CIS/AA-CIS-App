# Build prompt — chuỗi kiến trúc build-tiếp (04/09/2026, phiên 4)

(Saved verbatim from AA-522 latest comment, per chain-start instruction, 2026-09-05)

Chuỗi thực thi quyết định "build tiếp" từ AA-525. Giao Claude Code chạy **tuần tự, không dừng hỏi giữa chừng trừ khi ghi rõ ở dưới**: AA-522 → AA-526 → AA-527. Mỗi issue tự STEP0 → (wireframe nếu có FE mới, đăng comment trước khi code) → build → live-verify thật → comment báo cáo trên đúng issue đó → sang issue kế. Không tự set Done — Claude Chat soát sau.

**Lưu nguyên văn prompt này vào `docs/claude_tasks/` trước khi bắt đầu issue đầu tiên.**

---

## 1. AA-522 — Sửa bug lưu bài Luồng A + gỡ Luồng B
Đã có chẩn đoán chính xác trong comment mới nhất trên issue (từ AA-525 Phần 7.5) — không cần điều tra lại root cause từ đầu. Sửa theo đúng 4 điểm đã liệt kê: persist trạng thái "đang chờ CTA" ở server, phục hồi đúng form khi reload, verify lại các root cause phụ, gỡ hoàn toàn Luồng B sau khi Luồng A ổn định.

## 2. AA-526 — Di dời Atomize sang A-series (trigger tại A3)
Theo đúng mô tả issue. STEP0 bắt buộc xác nhận chính xác điểm code đánh dấu tour "vào A3" trước khi gắn hook — đọc lại luồng A0→A1→A2→A3 hiện tại, đừng giả định. **Dừng lại hỏi Nghiệp/Claude Chat trước khi xoá bất kỳ dữ liệu Segment/Route/Subject/Atom production nào** (mục 3 trong issue) — không tự ý xoá nếu không chắc chắn phạm vi an toàn.

## 3. AA-527 — Xây trang admin Atom Curation mới
Theo đúng mô tả issue. Đây là thiết kế UI mới hoàn toàn (không có pattern gốc từ repo tham chiếu — theo AA-525 Phần 1.2), cần wireframe cụ thể đăng comment trước khi code theo đúng quy ước frontend. Nếu không rõ vai trò/quyền truy cập trang này, dừng hỏi Nghiệp.

---

**Ghi chú quan trọng cho cả 3 issue:** đây là thay đổi kiến trúc lớn, ảnh hưởng dữ liệu production thật. Ưu tiên an toàn — dừng hỏi bất cứ khi nào không chắc chắn về phạm vi xoá dữ liệu hoặc ranh giới tenant/admin, thay vì tự quyết và làm sai.

Báo cáo evidence đầy đủ theo đúng chuẩn (browser/API/DB thật, không `/health` suông) trên từng issue tương ứng.

---

## Bổ sung của user (đầu phiên, không phải nguyên văn Linear comment)

Bundle 2 file docs cũ `docs/implementation-notes/AA-509.md` và `AA-511.md` vào PR đầu tiên của chuỗi này — không push riêng, không tạo PR docs-only tách biệt.

**Ghi chú khi thực thi**: kiểm tra đầu phiên (2026-09-05) cho thấy 2 file này thực ra đã được commit (`19df78b`) VÀ đã push lên `origin/main` trực tiếp từ trước (không qua PR review) — không phải "committed local, chưa push" như giả định. Do đó không có gì để bundle nữa; đã tồn tại trên main. Sẽ flag cho Nghiệp trong báo cáo cuối, không tự sửa git history.
