## Task cho Claude Code: N7 khảo sát — song song hoá piece-level + hiện trạng cost tracking

Mục tiêu: ĐÂY LÀ TASK KHẢO SÁT, KHÔNG PHẢI TASK CODE. Trả lời đủ thông tin để Nghiệp
quyết hướng làm tiếp — không tự ý implement song song hoá hay xây cost dashboard trong
task này, trừ bước 3 (chỉ nếu hoàn toàn an toàn, xem rõ bên dưới).

Bối cảnh: N7 hiện chạy các lần Nghiệp trigger để verify fix (AA-404, AA-415, tương lai
còn nhiều) khá chậm (tuần tự từng piece/slot) và tốn LLM cost thật (Bedrock, có satellite
account routing acc2→acc3→acc1, xem skill `aa-cis-schema`/`ai-nghiep` §4) — muốn biết (a)
có thể song song hoá piece trong 1 run để giảm thời gian chờ không, và (b) hiện có track
được cost/run không, nếu chưa thì cần gì để có.

Repo: AA-CIS-App
Branch hiện tại: main
Tạo branch mới: no (task khảo sát, không code — nếu cần branch để thử nghiệm nhỏ ở bước
3, tạo `feature/aa-418-parallel-cost-investigation` và KHÔNG merge, chỉ để tham khảo)

BƯỚC 0: lưu file task prompt này vào `docs/claude_tasks/AA-418-01-parallel-run-and-cost-investigation.md`.

Phần A — Khảo sát song song hoá piece-level (KHÔNG code, chỉ điều tra + báo cáo)

1. Đọc pipeline N7 (`services/acp_produce/`, graph orchestration) — xác định hiện tại các
   piece (blog/facebook/tiktok...) trong CÙNG 1 slot/tuần có đang chạy tuần tự (await từng
   piece xong mới sang piece tiếp) hay đã có concurrency nào chưa.
2. Nếu tuần tự — xác định RÀNG BUỘC thật trước khi đề xuất song song:
   a. Bedrock rate limit / quota trên acc2 (native) và acc3/acc1 (satellite) — có giới hạn
      concurrent request nào không? (Kiểm tra IAM/service quota, hoặc tài liệu nội bộ nếu
      có ghi lại từ trước.)
   b. Piece nào phụ thuộc kết quả piece khác không (VD content social có tham chiếu ngược
      lại nội dung blog đã sinh?) — nếu có dependency, không thể song song hoá vô điều kiện.
   c. Cost per LLM call có tăng khi chạy song song không (thường không tăng — cost là theo
      token, không theo thời gian — nhưng XÁC NHẬN không giả định).
   d. Repair loop (F1-F9, PieceInvariants vừa sửa ở AA-415) có state nào chia sẻ giữa các
      piece trong cùng run không — nếu có, song song hoá có thể phá invariant.
3. Nếu XÁC NHẬN an toàn (không có dependency chéo, rate limit đủ chỗ) — có thể làm 1 PoC
   nhỏ trên nhánh riêng (KHÔNG merge) để đo thử thời gian chạy 1 run trước/sau song song
   hoá piece-level, báo lại số liệu thực tế thay vì ước tính.
4. Nếu KHÔNG an toàn hoặc chưa rõ — dừng lại, báo cáo đầy đủ ràng buộc tìm được, để
   Nghiệp quyết có đầu tư fix rate-limit/dependency trước không.
5. Ghi rõ trong báo cáo: nếu làm song song piece-level, có cần đổi gì ở tầng theo dõi
   run status (`GET .../produce/run/{id}`, Run History UI) để vẫn hiển thị đúng progress
   không (VD hiện có thể đang giả định tuần tự để tính % hoàn thành).

Phần B — Khảo sát hiện trạng cost tracking (KHÔNG code, chỉ điều tra + báo cáo)

1. Tìm trong `shared/llm_client/` (client.py, bedrock_satellite.py) xem input_tokens/
   output_tokens có đang được log lại mỗi lần gọi Bedrock không, và log ở đâu (DB table,
   CloudWatch log, hay chỉ print/log ra console rồi mất).
2. Nếu ĐÃ log vào DB/bảng nào đó — xác định bảng, schema, có group theo run_id/piece_id
   không, có field nào phân biệt model (haiku/sonnet/gpt-4.1) và account (acc2/acc3/acc1,
   field `satellite_account` theo AA-399) không.
3. Nếu CHƯA log gì cả (chỉ có ở CloudWatch raw, không structured) — ước tính effort cần
   để thêm structured logging (bảng mới hay cột mới trên bảng có sẵn, ví dụ gắn vào
   `acp_deliver.pieces` hoặc bảng run riêng).
4. Tính thử cost 1 N7 run gần nhất (dùng run_id thật từ Run History, VD 2026-09 W2) bằng
   cách MANUAL trace qua CloudWatch/log nếu có — ước tính số tiền thật đã tốn cho 1 run
   verify (bao nhiêu piece × bao nhiêu vòng repair × token trung bình × giá model) — đây
   là con số Nghiệp cần để hiểu "chạy nhiều lần tốn bao nhiêu", kể cả nếu chưa có dashboard.
5. Đề xuất (không code) 2-3 phương án khả thi để có cost/run visibility — từ đơn giản
   (thêm cột `estimated_cost_usd` tính lúc log, hiện trong Run History UI) đến đầy đủ hơn
   (dashboard riêng, breakdown theo gate/repair round).

Verify — vì đây là task khảo sát:
1. Không cần deploy gì (trừ khi Phần A bước 3 tạo PoC — nếu vậy, KHÔNG merge, chỉ báo số
   liệu đo được rồi xoá/giữ nhánh riêng theo hướng dẫn Nghiệp).
2. Lưu báo cáo đầy đủ (cả Phần A và B) vào `docs/claude_audit/AA-418-parallel-cost-investigation.md`
   — đây là audit report, không phải implementation-notes (task này không implement).
3. Kết thúc bằng khuyến nghị rõ ràng: nên làm gì trước (song song hoá hay cost tracking
   hay cả 2), độ phức tạp mỗi phần, và rủi ro nếu làm sai (VD phá gate invariant, tốn thêm
   engineering time không cần thiết).

Git context:
- Repo: AA-CIS-App
- Current branch: main
- Không tạo PR trừ khi Phần A bước 3 cần nhánh PoC riêng — nếu có, KHÔNG merge, chỉ để
  tham khảo, báo rõ tên nhánh cho Nghiệp.

Sau khi done:
- Paste báo cáo đầy đủ về Claude Chat (không chỉ tóm tắt — cần đủ chi tiết để quyết định
  hướng làm tiếp theo)
- KHÔNG tạo Linear issue mới cho việc implement — để Nghiệp đọc báo cáo trước, quyết
  hướng, rồi mới tạo issue + task code riêng.
