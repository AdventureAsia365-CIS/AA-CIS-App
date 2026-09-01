STEP0 prompt — AA-510: Route/Hub schema + phát hiện hành trình

Bối cảnh: Sub-issue của epic AA-507, trả lời AA-504 (Blog multi-atom/pillar). Route dựng từ chuỗi Segment (AA-509, vừa Done) theo đúng thứ tự hành trình thật trong itinerary. Chỉ Blog dùng Route — 7 channel còn lại đi thẳng Segment → Slate.

Chỉ đọc, không sửa gì. Câu hỏi cần trả lời bằng bằng chứng code/schema thật:

Kiểm tra route.tour_id — mô tả gốc ghi REFERENCES silver_aa_internal.raw_tours(tour_id) (tour gốc Master Content). Đối chiếu: atom_segment/atom_segment_member (AA-509 vừa build) group atom theo tenant_id, còn atom bản thân thuộc về tour_atoms với owner_scope = tenant. Route join thẳng về raw_tours (Master Content) có đúng không, hay phải join qua tenant_tour_versions/tour đã tenant rewrite (giống bài học đã sửa ở AA-500 — tránh nhầm Master Content với tour tenant sở hữu thật)? Xác nhận rõ: Route đại diện cho hành trình của TOUR NÀO — bản gốc hay bản tenant đã viết lại.
Đọc CONTEXT.md phần Route/Hub + reference/channels.toml (repo Ms. Thư, path: /home/nghiep/projects/aa-cis/AA-CIS-App/docs/AI-gent-for automation works/aa-soscial-media-main) — xác nhận cơ chế takes_route thật, và cách Route được dựng cụ thể (thuật toán nào quyết định thứ tự ordered_segment_ids).
Đọc code dựng Route thật trong repo Ms. Thư (nếu có, ví dụ route_detection.py/tương đương) — port gần nguyên văn nếu có sẵn logic pure function.
Xác nhận kiểu dữ liệu JOIN: route.tenant_id (UUID) so với cách atom/segment hiện tại xác định tenant (đã biết từ AA-509: owner_scope = tenant_id::text) — Route cần dùng đúng pattern JOIN nào để lấy đúng Segment của đúng tenant, đúng tour.
family_id — cơ chế "gộp Route trùng hành trình khác tên" (ví dụ 6 itinerary cùng bán 1 route thật như "Nakasendo Way") dựa trên gì? Có thuật toán cụ thể trong repo Ms. Thư không, hay cần tự thiết kế?

Không build gì. Ghi kết luận vào docs/claude_audit/AA-510-step0-route-hub-investigation.md (chưa commit). Báo lại để chốt thiết kế trước khi giao build prompt — đúng quy trình 2 vòng STEP0 đã áp dụng cho AA-508/AA-509.
