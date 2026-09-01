STEP0 prompt — AA-515: Ranking/Atom Score stage

Bối cảnh: Phát hiện qua STEP0 AA-510 — Route/Hub cần atom đã qua ranking để dựng ordered_segment_ids đúng thứ tự, nhưng AA-CIS chưa có stage này. Đây là điều kiện tiên quyết mới, chặn cả chuỗi AA-507 còn lại (AA-510→511→512→513→514).

Chỉ đọc, không sửa gì. Câu hỏi cần trả lời bằng bằng chứng code thật:

Đọc repo Ms. Thư (/home/nghiep/projects/aa-cis/AA-CIS-App/docs/AI-gent-for automation works/aa-soscial-media-main) — tìm module/stage tính ranking/atom_score thật. Xác nhận chính xác: tiêu chí ranking là gì, công thức tính, chạy ở giai đoạn nào trong pipeline (trước/sau Segment).
Đối chiếu với ADR-2026-038 (đã Accepted trước đó, tại AA-CIS) — mục "hai trục atom scoring giữ riêng, không gộp" (distinctiveness vs DFS relevance, xác nhận qua score_distinctiveness()/score_dfs_relevance() đã tồn tại từ S165 STEP0). Đây có phải cùng 1 khái niệm với "ranking" mà Route cần, hay là 2 thứ khác nhau (1 cái để chấm điểm nội dung, 1 cái để sắp thứ tự trình bày)? Xác nhận rõ bằng đọc code, không suy đoán.
Nếu score_distinctiveness()/score_dfs_relevance() đã tồn tại và đang chạy — đọc code xác nhận: chúng có đang ghi kết quả vào cột/bảng nào (persist), hay chỉ tính tạm thời rồi bỏ? Nếu có persist, đây có thể là nền sẵn có cho AA-515, không cần xây từ đầu.
Xác nhận lại: T6 curation (HIGH/MED/LOW do người chọn) — có thật sự khác bản chất với ranking tự động không (STEP0 AA-510 đã loại trừ, nhưng cần xác nhận lại 1 lần rõ ràng bằng code, vì đây là quyết định quan trọng).
Đề xuất: ranking stage nên chạy ở đâu trong chain T5→T6→T7 — ngay sau T5 (trước Segment/AA-509), song song với Segment, hay sau Segment? Route cần atom đã ranking VÀ đã Segment — thứ tự 2 bước này ảnh hưởng gì tới nhau không?

Không build gì. Ghi kết luận vào docs/claude_audit/AA-515-step0-ranking-investigation.md (chưa commit). Báo lại để chốt thiết kế trước khi giao build prompt.
