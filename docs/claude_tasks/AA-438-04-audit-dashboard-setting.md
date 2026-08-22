## Task cho Claude Code: Audit Dashboard/Setting + toàn bộ mục sidebar Admin còn lại — KHÔNG sửa code

Mục tiêu: Task cuối của nhịp Admin (AA-438). Audit riêng phần "trang giám sát" — không phải data-flow A0-A3 (đã xong 3 task trước), mà là: mỗi mục trong sidebar admin có thật sự sống (đọc data thật) hay là placeholder/mock/dữ liệu cũ, giống như dashboard đã bị nghi ngờ (và đúng, đã xác nhận 1 phần ở AA-438-01: "Pipeline Activity 7D" và "Pass Rate 0%" là bug thật).

Repo: AA-CIS-App
Branch: feature/aa-438-admin-tier-audit (đã tồn tại từ AA-438-01/02/03 — checkout, KHÔNG tạo branch mới, KHÔNG push, KHÔNG PR ở task này).

Files cần đọc trước:
- `docs/claude_audit/AA-438-01-a0-a1-audit.md`, `AA-438-02-a1-a2-audit.md`, `AA-438-03-a2-a3-audit.md` — đọc cả 3, đây là audit cuối của cùng issue, không lặp lại việc đã xác nhận (Upload/S1 Rewrite/Review Queue/Master Content đã audit kỹ ở 3 task trước — KHÔNG audit lại).
- `frontend/app/admin/_components/AdminSidebar.tsx` — liệt kê TOÀN BỘ mục sidebar, đối chiếu với danh sách dưới đây, xác nhận mục nào CHƯA được audit.
- `frontend/app/admin/dashboard/page.tsx` + `GET /admin/metrics` handler (`api/routers/admin_pipeline.py:3370-3395`+) — đã audit 1 phần ở AA-438-01 (chỉ phần "Pipeline Activity"/"Pass Rate"), task này audit NỐT các phần còn lại của cùng trang: "Model Usage", "Pipeline Health", "Tenant Breakdown", "SEO Intelligence" tab, "Content Library" tab.

Danh sách mục sidebar THẬT (đọc trực tiếp từ ảnh chụp UI admin thật, 22/08 — KHÔNG suy đoán, đây là nguồn chính xác):

**ACP V2 — Setup & Approval:** Dashboard, Tenants, Marketplace, Quarter Plan (Gate B), Produce & Deliver (N7/N8), Run Health
**ACP V2 — Atoms:** Atomize (N2), Atom Curation
**AA Internal Content:** Upload (S0), S1 Rewrite, Review Queue, Brand Identity, Master Content
**Riêng:** Settings

CẦN audit trong task này (KHÔNG lặp lại Upload/S1 Rewrite/Review Queue/Master Content nếu đã đụng ở task trước — 3 task trước ĐÃ audit kỹ các mục này):
- Dashboard (nốt phần chưa audit: Model Usage, Pipeline Health, Tenant Breakdown, SEO Intelligence tab, Content Library tab)
- Tenants (danh sách tenant, trạng thái, plan tier)
- Marketplace
- Quarter Plan (Gate B)
- Produce & Deliver (N7/N8)
- Run Health
- Brand Identity (đã nhắc gián tiếp ở AA-438-02 §5 nhưng chưa audit riêng trang này)
- Settings
- **Atomize (N2)** — audit MỚI trong task này, xem mục "Điều tra legacy vs tenant-facing overlap" bên dưới
- **Atom Curation** — audit MỚI trong task này, xem mục "Điều tra legacy vs tenant-facing overlap" bên dưới

## Điều tra riêng, ưu tiên cao: "Atomize (N2)" và "Atom Curation" có phải tàn dư không

Nghiệp trực tiếp xem ảnh sidebar và nghi ngờ CẢ HAI mục này là tàn dư của kiến trúc admin-managed cũ, vì đã có bản tenant-facing tương đương:
- T5 (Atomize) giờ chạy TỰ ĐỘNG trong chuỗi T2→T3→T5, trigger trong 1 job khi tenant bấm "Viết" (xác nhận từ AA-436, ADR-2026-038 Direction B) — không còn cần admin thao tác tay atomize riêng.
- T6 (Atom Curation) đã có bản tenant self-service đầy đủ tại `/portal/t6-atoms` (AA-431, JWT auth + owner_scope filter).

**Cần xác nhận bằng code thật, KHÔNG suy đoán:**
1. "Atomize (N2)" trong sidebar admin trỏ tới route/endpoint nào — còn được gọi thật (có traffic/log gần đây) hay đã chết hẳn từ khi AA-436 merge (deploy 22/08)?
2. "Atom Curation" trong sidebar admin trỏ tới route/endpoint nào — khác gì với `/portal/t6-atoms` (tenant-facing, AA-431)? Cùng bảng `tour_atoms` hay khác?
3. Nếu cả 2 mục admin này giờ chỉ thao tác trên data của `aa_internal` (không phải tenant) — thì đây KHÔNG phải tàn dư, mà là 1 luồng riêng biệt hợp lệ cho nội dung nội bộ AA (giống cách Upload/S1 Rewrite là luồng riêng cho aa_internal, đã xác nhận ở AA-438-01). XÁC NHẬN rõ: 2 mục Atoms này có phải là "atomize cho aa_internal" (hợp lệ, giữ lại) hay là "atomize cho tenant nhưng qua đường admin cũ" (tàn dư, nên xóa sau khi audit Tenant tier xong)?
4. Nếu là tàn dư: ghi rõ trong báo cáo, KHÔNG xóa trong task này (Nghiệp sẽ quyết định xóa sau khi audit xong Tenant tier T0-T11, để tránh nhầm lẫn/gây rối UI trong lúc audit vẫn đang chạy).

Với mỗi mục, trả lời:
1. Route thật tồn tại không, page.tsx có phải placeholder/"Coming soon" không.
2. Data hiển thị từ endpoint nào, query gì — CHẠY THỬ query đó, so với con số hiển thị trên UI (nếu biết được từ code) để xác nhận khớp/lệch.
3. Nếu là số liệu tổng hợp (dashboard-style), kiểm tra CÓ mắc lỗi tương tự AA-438-01 đã tìm ra không (filter ngày sai, status-based filter kẹt, hardcode) — đây là trọng tâm chính của task, vì đã có 1 tiền lệ thật.
4. Có phải mock/hardcoded data không (tìm chuỗi cứng, số cứng trong JSX).

Context:
- ADR-2026-038: KHÔNG có trong repo (đã xác nhận AA-438-01) — không cố tìm lại.
- Đã xác nhận 3 bug thật ở A0-A3 audit trước: (a) `pipeline_runs` kẹt `'ingesting'` — ảnh hưởng dashboard "Pipeline Activity"/"Pass Rate", (b) reject không reset status, (c) `published_tours` UPSERT chỉ update 4/18 cột, (d) T1 thiếu filter master_status. Task này CHỈ audit thêm các mục CHƯA từng đụng — không audit lại 4 bug trên.
- Nghiệp đã quyết định (comment Linear AA-438): sau khi audit xong TOÀN BỘ (cả Admin lẫn Tenant tier), sẽ xóa sạch data build/test, chỉ giữ ~700+ tour thô, chạy lại từ đầu. Task này CHỈ audit code/UI, KHÔNG cần lo giữ gìn data hiện có (nhưng vẫn không tự ý xóa gì — chỉ đọc/query).

Steps:
1. Đọc `AdminSidebar.tsx`, liệt kê đầy đủ mục, đánh dấu mục nào đã audit (Upload/S1 Rewrite/Review Queue/Master Content/Atomize/Atom Curation — bỏ qua) vs chưa (danh sách ở trên).
2. Với từng mục CHƯA audit, làm theo 4 câu hỏi ở trên.
3. Đặc biệt chú ý "Run Health" và "Pipeline Health" (trên Dashboard) — các thẻ trạng thái "Idle" đã bị nghi ngờ ở AA-438-01 (Ingestion Lambda card đọc sai nguồn — `tenant_api_usage` thay vì AWS Lambda invocation thật) — xem các card khác (Step Functions Pipeline, Content Generation, Validation Lambda, Export/Catalog API) có cùng vấn đề "đọc nhầm nguồn" không.
4. "Model Usage" trên Dashboard hiển thị `claude-haiku-4-5`, `claude-sonnet-4-5`, `gpt-4.1` với calls/avg score — xác nhận nguồn dữ liệu này (bảng nào ghi lại mỗi lần gọi LLM), có đang ghi đúng cho MỌI lần gọi (kể cả từ AA-436 vừa test hôm nay) hay chỉ ghi cho 1 số luồng.

Verify: Không sửa code. Mọi kết luận có bằng chứng path:line hoặc query/response thật.

Sau khi done — ĐÂY LÀ TASK CUỐI CỦA NHỊP ADMIN, viết thêm 1 báo cáo TỔNG HỢP:
- Viết báo cáo riêng của task này: `docs/claude_audit/AA-438-04-dashboard-setting-audit.md`.
- Viết THÊM báo cáo TỔNG HỢP toàn bộ AA-438: `docs/claude_audit/AA-438-00-SUMMARY-admin-tier-audit.md` — tổng hợp cả 4 task (01/02/03/04), liệt kê TOÀN BỘ bug/gap tìm thấy xuyên suốt (dùng lại đúng danh sách đã comment trên Linear AA-438 làm khung, bổ sung phát hiện của task 04), kèm 2 phần riêng:
  - **"Data Cleanup Plan"** — ghi lại quyết định của Nghiệp (xóa data build/test, giữ ~700 tour thô, chạy lại từ đầu — SAU KHI audit xong cả AA-438 và AA-439).
  - **"Sidebar Admin — Legacy vs Tenant-Facing Overlap"** — bảng liệt kê TOÀN BỘ mục sidebar admin (11 mục + Settings), với 3 cột: (a) route/endpoint thật, (b) có bản tenant-facing tương đương không (VD Atomize N2 ↔ T5 tự động, Atom Curation ↔ /portal/t6-atoms), (c) khuyến nghị GIỮ (luồng aa_internal riêng biệt, hợp lệ) hay ĐÁNH DẤU XÓA SAU (tàn dư, chờ audit Tenant tier T0-T11 xong mới xóa để tránh nhầm lẫn giữa 2 audit đang chạy song song).
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-438-04-audit-dashboard-setting.md`.
- git commit trên branch `feature/aa-438-admin-tier-audit` — KHÔNG push, KHÔNG PR (chờ lệnh tổng hợp push, sẽ có task riêng).
- Comment tóm tắt lên Linear AA-438 (không đổi status — Nghiệp sẽ tự quyết định A4 build task tiếp theo sau khi đọc báo cáo tổng hợp).
- Paste nội dung báo cáo tổng hợp (hoặc link file) về Claude Chat.
