## Task cho Claude Code: Đối chiếu kỹ acp_s4_social với workflow gốc (9 bước) + tài liệu formulas/aa-marketing-v2, và tìm trust-ramp trong thiết kế gốc — CHỦ YẾU ĐỌC, xác nhận trước khi quyết định tái dùng hay viết lại

Mục tiêu: AA-439-06 phát hiện `services/acp_s4_social/` có vẻ triển khai đúng luồng T8 (sinh angle, dual-mode) nhưng CHƯA TỪNG được dùng (0 row). Nghiệp muốn xác nhận CHẮC CHẮN module này có đúng khớp workflow gốc không trước khi quyết định tái dùng hay viết lại với tên mới cho đúng chuỗi T-series. Nghiệp cũng đưa ra workflow 9 bước chuẩn (dưới đây) để đối chiếu chính xác từng bước.

Repo: AA-CIS-App
Branch: feature/aa-439-tenant-tier-audit (đã tồn tại — checkout, KHÔNG tạo branch mới, KHÔNG push, KHÔNG PR).

## Workflow gốc 9 bước (Nghiệp cung cấp, nguồn: nghiên cứu chị Thư) — đối chiếu CHÍNH XÁC với code

1. Collect title/content seed and channel.
2. Show the goal selection list.
3. Apply the fixed brand audience automatically.
4. Apply the formula mapped to the selected goal.
5. Create 3 specific angles.
6. Recommend the strongest angle.
7. Wait for human choice.
8. Write the final content only after the human chooses an angle.
9. Run a quality/editor pass internally.

Angle phải hiển thị: Name, Why it works, formula fit, best final style.

## PHẦN A — Đọc kỹ tài liệu gốc TRƯỚC khi đối chiếu code

Đọc TOÀN BỘ 2 folder (không chỉ file đã đọc ở AA-439-04/05):
1. `docs/AI-gent-for automation works/fomulas/` (lưu ý: tên folder có thể là "fomulas" thiếu chữ "r", hoặc "formulas" — kiểm tra tên chính xác bằng `ls docs/AI-gent-for\ automation\ works/`) — đây là bảng công thức viết (writing formulas table) — đọc toàn bộ, liệt kê đầy đủ công thức có trong đó.
2. `docs/AI-gent-for automation works/aa-marketing-v2/` — đọc lại các phần LIÊN QUAN ĐẾN ANGLE/SOCIAL cụ thể (không phải toàn bộ, đã đọc phần atom/distinctiveness ở AA-439-03/04) — tìm phần mô tả channel output rules ("Channel Output Structures"), workflow 9 bước ở trên có khớp với mô tả trong CONTEXT.md/README.md không.
3. Tìm CHÍNH XÁC nguồn của workflow 9 bước Nghiệp cung cấp — có đúng khớp với 1 phần cụ thể nào trong tài liệu không (trích dẫn path:line nếu tìm thấy), hay đây là mô tả Nghiệp tự diễn giải lại (không sao nếu vậy, chỉ cần xác nhận rõ).
4. **Tìm cụ thể: tài liệu gốc (aa-marketing-v2 hoặc formulas) có nhắc đến khái niệm "trust ramp" / "veto window" / "publish_mode" / progression theo thời gian (tenant mới → tenant tin cậy) ở đâu không?** Đây là câu hỏi quan trọng — Nghiệp muốn biết đây có phải ý tưởng của chị Thư hay là phát minh riêng của lần build trước (AA-365, đã nhắc ở AA-440/AA-439-06). Grep `trust`, `ramp`, `veto`, `graduate`, `probation` trong cả 2 folder.

## PHẦN B — Đối chiếu CHÍNH XÁC `acp_s4_social` với workflow 9 bước

Đọc lại kỹ `services/acp_s4_social/angles.py`, `handler.py`, `formula.py` (đã đọc ở AA-439-06, đọc SÂU hơn lần này, từng dòng liên quan) — với MỖI bước trong 9 bước ở trên, xác nhận:
- Có code thật tương ứng không (path:line).
- Code đó có làm ĐÚNG như mô tả bước đó không, hay có sai khác/thiếu sót (VD bước 3 "apply fixed brand audience automatically" — code có thực sự "tự động áp dụng" hay cần input thủ công?).
- Output angle có đủ 4 trường "Name, Why it works, formula fit, best final style" như Nghiệp yêu cầu không — đối chiếu với field thật trong `angles.py` (AA-439-06 đã liệt: `name`, `why_it_works`, `length_signal`, `style_signal` — CHÚ Ý: "formula fit" và "best final style" trong yêu cầu của Nghiệp có khớp với "length_signal"/"style_signal" trong code không, hay là 2 khái niệm khác cần thêm field mới?).

## PHẦN C — Kết luận rõ ràng

Trả lời dứt khoát: `acp_s4_social` có khớp ĐỦ và ĐÚNG với workflow 9 bước + yêu cầu field của Nghiệp không?
- Nếu khớp hoàn toàn → xác nhận rõ, liệt kê phần cần làm để NỐI vào N7/N8 (không viết lại logic).
- Nếu khớp một phần → liệt kê CHÍNH XÁC phần nào khớp, phần nào thiếu/sai, để quyết định "nối + vá" hay "viết lại".
- Nếu không khớp → giải thích rõ sai khác cụ thể.

KHÔNG tự quyết định "nên tái dùng hay viết lại" — chỉ cung cấp bằng chứng đối chiếu chi tiết để Nghiệp/Claude Chat quyết định.

Verify: Không sửa code. Mọi kết luận có bằng chứng path:line hoặc trích dẫn tài liệu.

Sau khi done:
- Viết báo cáo vào `docs/claude_audit/AA-439-07-s4social-workflow-comparison.md`.
- Copy CHÍNH task prompt này vào `docs/claude_tasks/AA-439-07-audit-s4social-comparison.md`.
- git commit trên branch `feature/aa-439-tenant-tier-audit` — KHÔNG push, KHÔNG PR.
- Comment tóm tắt lên Linear AA-439.
- Paste nội dung báo cáo về Claude Chat.
