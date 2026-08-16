## Task cho Claude Code: /admin/produce — layout fit-width fixes + modal đè sidebar + copy gọn

Mục tiêu: Sửa các vấn đề layout còn sót lại sau PR #168 (piece-level Gate C list + data
bug fix). Đây là round 4 trên cùng trang `/admin/produce` — nhiều vấn đề layout cũ vẫn
CHƯA được sửa dù các PR trước báo đã xong, nên lần này bắt buộc verify bằng screenshot
thật ở đúng breakpoint trước khi báo Done.

Repo: AA-CIS-App
Branch hiện tại: main (verify bằng `git branch --show-current`)
Tạo branch mới: yes — `feature/aa-412-produce-page-layout-fixes`
Merge vào: main

BƯỚC 0 — LÀM NGAY TRƯỚC KHI CODE (rule §2.1 skill ai-nghiep): lưu chính file task prompt
này vào repo, đúng nguyên văn, tại đường dẫn
`docs/claude_tasks/AA-412-04-produce-page-layout-fixes.md` — commit riêng 1 commit đầu
tiên (`docs: save task prompt [AA-412]`) trước khi bắt đầu code, không gộp chung với
commit code sau này. Đây không phải việc "nhớ làm cuối" — làm ngay bước đầu tiên.

Files cần đọc trước:
- Layout admin chính (component bọc sidebar — tìm bằng `grep -r "CIS Admin" --include=*.tsx`
  hoặc tìm `AdminLayout`/`Sidebar` component) — để hiểu sidebar được render ở tầng nào so
  với page content, và z-index/positioning hiện tại.
- Component "Trigger a Production Run" form.
- Component "Gate C — Packets Ready for Review" table (piece-level, vừa đổi ở PR #168).
- Component modal "Review Packet Pieces" (full-screen, đang đè sidebar — bug chính cần
  sửa).
- Component bảng "Run History".
- `docs/implementation-notes/AA-412-ui-readability.md` và
  `docs/implementation-notes/AA-412-produce-page-usability.md` (nếu đã tồn tại từ PR
  trước) — đọc kỹ để hiểu ĐÃ claim sửa gì, đối chiếu với thực tế còn bug để tránh lặp lại
  cách làm không hiệu quả.

Context — quan sát trực tiếp qua browser thật (aa-cis.lumiguides.it.com/admin/produce),
sau PR #168 đã merge/deploy:

1. **Trang /admin/produce nói chung vẫn chưa fit chiều ngang** — dù PR #166/#168 báo đã
   sửa Run History full-width, thực tế mở trang vẫn thấy không dùng hết chiều rộng viewport
   đúng cách (khoảng trắng thừa hoặc bị giới hạn max-width không hợp lý). Cần audit lại
   toàn trang, không chỉ 1 component riêng lẻ.

2. **"Trigger a Production Run" — CHƯA có gì thay đổi.** PR #168 báo phần Gate B
   availability hints (Phần 1 của task trước) bị hoãn lại chờ Nghiệp confirm endpoint —
   ĐÚNG, chưa cần build phần đó ngay. NHƯNG có 1 việc nhỏ, độc lập, cần làm ngay: câu mô
   tả dưới form hiện đang dài dòng và lẫn cả issue-tracking id vô nghĩa với người dùng
   cuối:
   > "Only tenants with an approved Quarter Plan (Gate B) can be produced for. If a tenant
   > has no approved plan yet, the run will fail with a clear message below — approve one
   > first via Quarter Plan (Gate B). "Week" is the 1-4 week-of-month slot numbering used
   > by the production schedule, not an ISO week — Month + Week together identify one
   > specific production slot (AA-410)."

   Viết gọn lại, bỏ "(AA-410)" (nội bộ, không có nghĩa gì với người dùng), giữ lại 2 ý cốt
   lõi: (a) tenant cần Quarter Plan approved trước khi produce được; (b) Week = tuần thứ
   1-4 trong THÁNG, không phải ISO week. Gợi ý rút gọn (không bắt buộc dùng nguyên văn,
   miễn giữ đúng 2 ý và ngắn gọn):
   > "Requires an approved Quarter Plan (Gate B) for the tenant. Week = 1st–4th week of
   > the selected month, not an ISO week."

3. **Modal "Review Packet Pieces" đang full-screen đè LÊN CẢ SIDEBAR** (sidebar admin bên
   trái — Dashboard/Tenants/Marketplace/.../Produce & Deliver/...) — khi mở modal, sidebar
   biến mất/bị che hoàn toàn, mất điều hướng. Fix: modal chỉ nên chiếm vùng CONTENT bên
   phải sidebar (giữ sidebar luôn hiển thị, không bị đè), vẫn giữ nguyên toàn bộ hành vi
   đã build ở PR #166 (sticky header/footer, per-piece action sticky, Gate Ledger hiện
   ngoài/Content-Audit collapsed từ PR #168) — chỉ đổi VÙNG modal chiếm, không đổi nội
   dung/hành vi bên trong.

4. **Bảng "Run History" vẫn chưa fit chiều ngang** — dù PR #166 báo đã sửa full-width
   table-layout:fixed, thực tế mở trang vẫn thấy: (a) bảng không fit đúng chiều ngang
   viewport (tương tự vấn đề #1); (b) khi khổ ngang bị hẹp, các cột/thông tin bị CHỒNG LÊN
   NHAU (overlap), không phải chỉ tràn/cuộn — đây là bug nghiêm trọng hơn (dữ liệu không
   đọc được vì đè lên nhau, không đơn thuần là "phải cuộn mới thấy"). Cần điều tra CSS gây
   overlap (khả năng do table-layout:fixed với % column width cộng dồn sai, hoặc content
   trong cell không wrap/truncate đúng cách tràn ra ngoài cell). Áp dụng nguyên tắc tương
   tự mục 3: bảng Run History PHẢI nằm trong vùng content bên phải sidebar, không đè lên
   sidebar.

Steps:
1. Audit layout tổng thể trang `/admin/produce` — xác định container/wrapper nào đang giới
   hạn sai chiều rộng (page-level hoặc từng component), fix để cả trang dùng đúng full
   width của vùng content (bên phải sidebar).
2. Sửa câu mô tả dưới "Trigger a Production Run" — rút gọn theo Context #2.
3. Sửa modal "Review Packet Pieces" — đổi từ full-viewport sang full-width-of-content-area
   (không đè sidebar). Cách làm phổ biến: nếu đang dùng React Portal render vào `<body>`,
   cân nhắc render trong DOM tree của content area thay vì portal ra ngoài, HOẶC nếu vẫn
   cần portal, tính toán `left` offset = chiều rộng sidebar (dùng CSS variable nếu sidebar
   đã có, hoặc đo bằng `getBoundingClientRect`) để modal không đè lên sidebar. Verify sidebar
   luôn nhìn thấy được và click được khi modal đang mở.
4. Sửa bảng Run History — fix bug chồng thông tin: kiểm tra lại CSS `table-layout: fixed`
   + % column width hiện tại có cộng đúng 100% không, cell content có set `overflow`,
   `text-overflow`, `white-space` hợp lý không (tránh tràn đè cell bên cạnh). Đảm bảo bảng
   nằm trong vùng content, không đè sidebar, và ở các khổ ngang hẹp (thu nhỏ browser) vẫn
   đọc được — có thể cần giảm số cột hiển thị đồng thời, ẩn bớt cột ít quan trọng vào
   dropdown "..." hoặc cho phép horizontal scroll CỤC BỘ trong khung bảng (không phải toàn
   trang) nếu thực sự không đủ chỗ, thay vì để chồng lấp.

Verify — BẮT BUỘC, không được báo Done nếu thiếu bước nào:
1. `npm run build` pass sạch.
2. Chạy production build thật (`npm run build && npm start`, không phải `next dev`).
3. Chụp screenshot thật (Playwright, viewport 1920x1080 VÀ 1440x900 VÀ 1280x800) cho:
   (a) trang /admin/produce tổng thể — xác nhận full-width content area, sidebar luôn
   hiển thị; (b) modal Review Packet Pieces đang MỞ — xác nhận sidebar vẫn hiển thị bên
   trái, modal không đè lên; (c) tab Run History ở cả 3 viewport — xác nhận KHÔNG có cột/
   text nào chồng lên nhau, đọc được rõ ràng, sidebar vẫn hiển thị.
4. Nếu bất kỳ ảnh nào ở bước 3 vẫn cho thấy sidebar bị che hoặc chữ/cột chồng nhau — ĐÂY
   LÀ CHƯA XONG, tiếp tục sửa, không dừng lại báo Done.
5. Deploy Dev qua CI, verify ECS task digest khớp `:latest` — nếu AWS session cần MFA
   tương tác mà không có sẵn, DỪNG và báo rõ cho Nghiệp thay vì bỏ qua bước này (như PR
   #168 đã gặp).
6. Lưu toàn bộ screenshot + report vào
   `docs/implementation-notes/AA-412-produce-page-layout-fixes.md` (không lưu `/tmp`).
7. KHÔNG tự đánh dấu Done — dừng lại sau deploy, báo Nghiệp tự test qua
   `aa-cis.lumiguides.it.com/admin/produce`, đặc biệt bấm mở modal Review Packet Pieces để
   tự mắt xác nhận sidebar không bị đè.

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Tạo branch mới: yes — feature/aa-412-produce-page-layout-fixes
- Merge vào: main
- Sau khi done: `git add . && git commit -m "fix: produce page full-width layout, modal no longer covers sidebar, trim copy [AA-412]" && git push`, tự `gh pr create` (KHÔNG tự merge)

Sau khi done:
- Paste PR link + toàn bộ screenshot verify về Claude Chat
- Trước khi ghi Linear, tự `get_issue` xác minh AA-412 title khớp bối cảnh trước khi post
  comment — không đổi status (giữ In Progress, D3 reject-flow + Phần 1 Gate B hints vẫn
  chờ riêng).
