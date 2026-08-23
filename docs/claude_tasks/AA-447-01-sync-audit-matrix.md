# AA-447-01 — Rà soát đồng bộ BE+FE+hạ tầng toàn bộ T0-T11 + A0-A4

Task cho Claude Code: Rà soát đồng bộ BE+FE+hạ tầng toàn bộ T0-T11 + A0-A4 (AA-447)

Mục tiêu: tạo 1 ma trận đầy đủ, chính xác — với mỗi stage, xác nhận qua BẰNG CHỨNG THẬT (không
suy đoán từ tên file/route) xem cả 3 lớp (Backend, Frontend, Hạ tầng) có khớp nhau và tenant/admin
THẬT SỰ dùng được tính năng đó không. KHÔNG viết code, KHÔNG sửa gì — thuần investigate + tổng hợp.

⚠️ Concurrency: dùng git worktree riêng nếu có session khác đang chạy song song.

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: yes: feature/aa-447-sync-audit-matrix
Merge vào: main (không áp dụng phiên này — investigate only)

Files cần đọc trước:
- ADR-2026-038 (Notion `3c3b8a41-ec5d-8123-911f-e0c308841e79`) — đặc biệt mục 11.2 (roadmap
  A0→T11) và mục 10.4 (bảng scope FE) — đây là baseline NGHI NGỜ cần verify lại, không phải sự
  thật đã xác nhận (ADR ghi tại thời điểm 21-22/08, có thể đã lỗi thời sau các task mới)
- TẤT CẢ báo cáo `docs/claude_audit/AA-438-*.md`, `docs/claude_audit/AA-439-*.md`,
  `docs/claude_audit/AA-440-*.md`, `docs/claude_audit/AA-445-01-*.md`,
  `docs/claude_audit/AA-437-01-*.md` — đã có nhiều finding về từng stage riêng lẻ, tổng hợp lại
  thay vì điều tra lại từ đầu những gì đã biết
- `docs/implementation-notes/AA-441-*.md`, `AA-443-*.md`, `AA-437-02-*.md`, `AA-444-*.md`,
  `AA-445-02-*.md` — các task đã build xong trong session 23/08, đối chiếu xem đã thay đổi gì so
  với baseline ADR

Context:
- Ký hiệu: A0-A4 (Admin/Global tier), T0-T11 (Tenant tier) — theo ADR-2026-038 mục 2.
- Baseline nghi ngờ (ADR mục 11.2, TỪ 21/08, CẦN VERIFY LẠI vì đã có nhiều task build/fix từ đó
  tới 23/08):
  - A0-A3: BE+FE live
  - A4: baseline nói "chưa" — NHƯNG đã build ở AA-437 (23/08) — cần verify lại thành ĐÃ CÓ
  - T0: BE fixed (AA-424), FE "chưa test qua UI thật" — cần verify lại, có UI thật (BrandTab.tsx
    + CompetitorsTab mới từ AA-445) — nhưng route `/portal/t0-brand` có đủ để tenant tự thấy/dùng
    không
  - T1: BE xong, FE "label cũ, không hiện kết quả T3/T5"
  - T2-T5: BE verified, chạy trong 1 job — không có FE riêng (đúng thiết kế, chạy ẩn)
  - T3: BE có, FE "chưa có" — NHƯNG theo ADR mục 0.1 (22/08, sau baseline), quyết định đổi hẳn:
    T3 KHÔNG có UI riêng nữa (badge nhẹ trên T4 thay vì trang riêng) — verify FE hiện tại có
    đúng badge đó chưa
  - T4: BE+FE có (My Catalog / CatalogTab.tsx)
  - T6: FE "100% admin-only" theo baseline — NHƯNG AA-439-02/03 tìm thấy `/portal/t6-atoms` ĐÃ
    build tenant-facing thật (baseline lỗi thời ngay trong ADR) — verify lại trạng thái thật
    hiện tại
  - T7: BE có (`quarter.py`/`allocator.py`, giờ đọc `distinctiveness` thật sau AA-445) — FE:
    THEO ẢNH THẬT NGHIỆP GỬI (sidebar portal 23/08), KHÔNG CÓ mục Content Planning nào — xác
    nhận rõ đây là gap thật, không phải nhầm lẫn
  - T8: BE tồn tại nhưng orphan (`acp_s4_social`, 0 caller) — quyết định viết lại hoàn toàn (ADR
    §0.5) — FE hoàn toàn chưa có
  - T9-T10: BE thật (E1/E2/E3, F1-F9 gate stack) nhưng nằm "trong T8" theo baseline — chưa có FE
    riêng, phụ thuộc T8 build trước
  - T11: BE hoàn toàn chưa tồn tại (`deliver_packet()` chỉ đánh dấu status, không gửi thật) — FE
    chưa có
  - Marketplace: đã build AA-444 (`/portal/marketplace`) — verify liên kết với T7 (nguồn dữ
    liệu) có thật sự nối chưa

Steps:

1. **Với MỖI stage (A0-A4, T0-T11), xác nhận 3 lớp bằng bằng chứng thật:**
   - BE: endpoint/hàm có tồn tại + có ĐANG được gọi thật không (log, query DB xác nhận có
     traffic/data thật gần đây, không chỉ code tồn tại)
   - FE: route/trang có tồn tại trong portal (tenant-facing) hoặc admin — QUAN TRỌNG:
     tenant/admin có TỰ THẤY được nó từ sidebar/navigation thông thường không, hay chỉ truy cập
     được nếu biết URL chính xác (như tình huống Marketplace/Competitors vừa gặp — có trang
     nhưng phải tự tìm)
   - Hạ tầng: migration/bảng liên quan đã apply chưa, cột nào NULL/rỗng cho thấy chưa có dữ liệu
     thật dù code đã chạy

2. **Đặc biệt kiểm tra sidebar/navigation portal thật** — liệt kê ĐẦY ĐỦ toàn bộ mục hiện có
   trong sidebar (`/portal/*`), đối chiếu xem mỗi mục map vào T-stage nào, và ngược lại —
   T-stage nào có BE/FE code nhưng KHÔNG xuất hiện trong sidebar (giống tình huống T7 vừa phát
   hiện qua ảnh chụp thật).

3. **Với mỗi stage, kết luận rõ ràng 1 trong 3 trạng thái:**
   - ✅ ĐỒNG BỘ — cả 3 lớp khớp, người dùng thật (tenant/admin) tự thấy và dùng được
   - ⚠️ LỆCH TẦNG — có ít nhất 1 lớp thiếu hoặc không nối đúng (ghi rõ lớp nào, ví dụ "BE có, FE
     không có trong sidebar")
   - ❌ CHƯA CÓ — cả 3 lớp đều chưa build

4. **Tổng hợp thành 1 bảng duy nhất** (stage | BE | FE | Hạ tầng | Kết luận | Ghi chú) — đây là
   output chính, phải đầy đủ tất cả 16 stage (A0-A4 + T0-T11).

Verify: mọi kết luận phải có bằng chứng cụ thể (đường dẫn code, kết quả query, tên route thật) —
không suy đoán từ tên biến hay tài liệu cũ.

Sau khi done:
- Lưu CHÍNH file task prompt này vào `docs/claude_tasks/AA-447-01-sync-audit-matrix.md` trước
  khi bắt tay.
- Lưu báo cáo đầy đủ (bảng ma trận + chi tiết từng stage) vào
  `docs/claude_audit/AA-447-01-sync-audit-matrix.md`.
- Paste TOÀN BỘ bảng ma trận về Claude Chat (không chỉ tóm tắt).
- Linear AA-447: giữ nguyên status Backlog — Claude Chat sẽ đối chiếu với AA-446 (sổ cái 40
  bug/gap) và cùng Nghiệp quyết định thứ tự ưu tiên build tiếp theo dựa trên ma trận này.
