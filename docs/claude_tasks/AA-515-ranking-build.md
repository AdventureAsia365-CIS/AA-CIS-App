Build prompt — AA-515: Ranking/Atom Score stage (rank-sum + multi-market research loop)

Đã qua 4 vòng STEP0 (đọc đủ 3 file trước khi bắt đầu: AA-515-step0-ranking-investigation.md, AA-515-step0b-demand-research-loop.md, AA-515-step0c-multimarket-schema.md — chứa toàn bộ bằng chứng, đừng suy luận lại).

Build theo đúng thứ tự phụ thuộc:

Mở rộng DFS_LOCATION_MAP/MARKET_RANK (seed_builder.py) — thêm DE/FR/NL và bất kỳ quốc gia nào khác cần thiết để phủ đủ market thật của tenant hiện có. Xác nhận qua query shared.tenant_seo_config trước khi viết code cứng.
Hàm mới resolve_buyer_markets() (số nhiều, file seed_builder.py) — trả list[tuple[location_code, location_name, language_code]] từ toàn bộ target_market.countries của tenant, không chỉ 1 ưu tiên nhất. KHÔNG sửa resolve_buyer_market() cũ — giữ nguyên cho 3 call site hiện tại (handler.py:58, admin_pipeline.py:2296, admin_pipeline.py:2507).
Research loop mới (services/acp_contract/segment_research.py hoặc tương đương):
Gom Segment theo atom_segment.canonical_place (1 lần research/place, không phải/Segment).
LLM ReAct loop, 4 tool: volumes (bắt đầu bằng tên place trước, thêm action nếu place có volume), serp (chỉ cho keyword đã có volume, tối đa 2/place), suggestions (chỉ khi mọi keyword volume=0, tối đa 1/place), done. Giới hạn: tối đa 4 bước, tối đa 8 keyword/place.
Ràng buộc prompt: keyword là "cái traveller gõ tìm kiếm", không phải ngôn ngữ marketing.
Fan-out N market/place — gọi resolve_buyer_markets(), N request riêng biệt/market (API DataForSEO không cho gộp market, đã xác nhận qua tài liệu chính thức).
Coalescing trong cùng market: gộp nhiều keyword đang chờ vào 1 request volumes (tới 1000 keyword/request), đợi tối đa ~5 giây hoặc đủ loop "park" xong — theo đúng cơ chế Ms. Thư.
Bảng lưu keyword đã mua — (keyword, market, search_volume, retrieved_on, ...), cache 6 tháng (FRESH_FOR), đọc từ cache trước khi mua lại.
_demand()/attribution (chạy trong bước ranking, không phải trong research loop) — với mỗi Segment cần chấm điểm: đọc toàn bộ bảng keyword đã mua, so khớp bằng word-overlap thuần giữa từ trong keyword và place+action của Segment (sau normalise). KHÔNG dùng embedding-match (atom_matches) — quyết định có chủ đích, giữ nguyên.
Migration bảng ranking — acp_contract.atom_ranking (tenant_id, tour_id, segment_id, demand_rank, recurrence_rank, questions_rank, said_rank, total_rank, computed_at).
services/acp_contract/atom_ranking.py — port rank():
4 trục, mỗi trục là competition rank (1, 2, 2, 4 — ties chia sẻ hạng), tổng thấp nhất thắng.
demand_rank: theo market riêng, giữ market tốt nhất cho mỗi Segment. Segment không đo được demand → lấy median của các Segment đã đo (không phải hạng bét).
recurrence_rank: đếm trong phạm vi 1 tenant (không cross-tenant).
questions_rank: số câu PAA rơi vào Segment đó.
said_rank: số ký tự itinerary mô tả khoảnh khắc đó.
Không trọng số, không hằng số tune — giữ nguyên tinh thần rank-sum thuần.
Loại trừ 2 lớp Segment trước khi ranking (transit, unnamed place) nhưng vẫn xuất hiện trong output dưới heading riêng, không ẩn hoàn toàn.
Trigger: chạy tự động ngay sau Segment matching (AA-509) hoàn tất cho 1 (tenant_id, tour_id).

Live-verify trước khi báo xong:

Tenant có sẵn multi-market (dùng wanderlux-travel hoặc aa_internal, cả 2 đều US/UK/AU đã có trong DFS_LOCATION_MAP) → xác nhận research loop gọi đúng N=3 request/place (1 request/market), không gộp nhầm market.
Tenant exploreasia-co (DE/FR/NL) → xác nhận không còn fallback về US sau khi mở rộng map — gọi đúng DE/FR/NL.
2 Segment cùng canonical_place khác nhau về action → xác nhận chỉ 1 lần gọi LLM research cho place đó (dedupe đúng).
Chạy _demand() 2 lần liên tiếp không mua thêm keyword mới → xác nhận đọc cache, không gọi lại DataForSEO.
atom_ranking cho 1 tour → xác nhận rank-sum đúng công thức, tổng thấp nhất xếp trên.
Segment loại trừ (transit/unnamed) → xác nhận vẫn có trong output, đúng heading riêng, không lẫn vào danh sách ranking chính.

Ghi implementation notes vào docs/claude_audit/ hoặc docs/implementation-notes/, gộp PR build, không tách PR docs-only. Nhớ copy nguyên văn task prompt này vào docs/claude_tasks/AA-515-ranking-build.md trước khi bắt đầu (đúng quy ước đã bổ sung trong phiên này). Không tự set Linear Done.
