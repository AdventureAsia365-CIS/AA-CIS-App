Build prompt AA-500 (BẢN SỬA, dùng bản này, bỏ bản trước) — giao Claude Code (01/09, S170).

Nguồn đúng cho fetch_trips()/T7 Slate KHÔNG PHẢI lọc v_trip_registry (763 trip Master Content chung) theo tenant_id — mà là đọc qua Marketplace view (AA-444): tenant_tour_versions (T4, có tenant_id — tour tenant đã rewrite) JOIN tour_atoms (T5, có owner_scope — đã atomize xong). v_trip_registry chỉ đúng vai trò cho T1 (chọn tour để bắt đầu viết), không phải cho T7/Slate.

Tóm gọn: fetch_trips() cần trả về tour đã qua chuỗi T1→T5 của đúng tenant đó — không phải toàn bộ Master Content lọc tenant_id.

## Trước khi sửa

1. git worktree riêng.
2. Đọc services/acp_planning/runway.py thật — xác nhận fetch_trips() hiện đọc v_trip_registry đúng như mô tả.
3. Đọc Marketplace view (AA-444) — tìm đúng view/query đang dùng để list tour tenant đã rewrite+atomize (khả năng cao là 1 view SQL có sẵn, hoặc join tenant_tour_versions+tour_atoms thủ công ở đâu đó khác trong codebase, vd trong T7/T8 router cũ). Xác nhận qua code thật, không đoán tên view.
4. Xác nhận cột nào trên tenant_tour_versions/tour_atoms mang tenant_id/owner_scope thật — tên cột chính xác, không giả định.
5. Tìm mọi call site gọi fetch_trips() hiện tại — xác nhận sau khi đổi nguồn dữ liệu, shape trả về (tour_id, tên cột...) có đổi không, các nơi gọi có cần sửa theo không.
6. BẮT BUỘC: lưu nguyên văn prompt này vào docs/claude_tasks/AA-500-build-tenant-filter.md trước khi sửa code.
7. git stash khi cần dọn working tree — không git reset --hard.

## Việc cần sửa

Viết lại fetch_trips() để đọc nguồn tour đã qua T1→T5 của đúng tenant (Marketplace view hoặc join tương đương xác nhận ở bước 3-4) — thay hoàn toàn nguồn v_trip_registry không lọc, không phải chỉ thêm WHERE tenant_id = $1 lên trên nguồn cũ. Không đụng compute_runway_map().

## Live-verify bắt buộc (2 lần: trước merge + sau merge)

- Với ≥2 tenant thật khác nhau: fetch_trips() chỉ trả về tour tenant đó đã rewrite+atomize (T1-T5 xong) — không thấy tour tenant khác, không thấy tour Master Content chưa ai rewrite.
- aa_internal (tenant nhiều tour nhất) vẫn ra đúng số tour đã atomize của chính nó, không bị 0 tour do sai điều kiện join.
- Đối chiếu số tour trả về với số tour thật sự có tour_atoms cho tenant đó (query trực tiếp DB để so sánh, không chỉ tin qua API).
- Chạy lại toàn bộ luồng RunwayMap hiện có — không nơi nào vỡ.

## Sau khi build xong

Không tự set Done. Báo cáo lại, chờ soát. PR riêng bình thường.

---

## STEP0 note (this session, before the revised prompt arrived)

A first version of this prompt (asking to add `WHERE tenant_id = $1` directly onto
`v_trip_registry`) was received first. Live DB check (ECS-exec, aa365-admin) BEFORE writing
any code found:

- `silver_aa_internal.raw_tours.tenant_id` / `acp_contract.v_trip_registry.tenant_id`: 100%
  `aa_internal` (793 / 763 rows respectively) — zero rows for any other tenant.
- `gold_aa_internal.tenant_tour_versions.tenant_id`: real per-tenant data exists —
  `wanderlux-travel` has 10 rows.
- `acp_contract.tour_atoms.owner_scope`: `wanderlux-travel` has 34 atoms.

So a literal `WHERE tenant_id = $1` on `v_trip_registry` would have returned 0 rows for every
real non-`aa_internal` tenant — reproducing the exact AA-323-round-6 "0 eligible trips" bug via
a different code path, and would have additionally broken N5 (`quarter.plan_quarter`) / N6
(`allocator.allocate_month`) for any tenant with T5 atoms, since their `atoms_by_trip` would no
longer match any entry in an empty `trips_by_id`. The revised prompt above (received mid-session,
replacing the first) reaches the same conclusion independently and was used for the actual build.

---

## Follow-up build prompt (same day, after PR #271 merged+deployed) — "Cách B", verbatim

Chốt: Cách B — fetch_trips() chỉ trả về tour đã có ≥1 atom (đã qua atomize T5), không trả về tour
mới rewrite xong nhưng chưa atomize.

Lý do: Slate (T7, AA-511) hiển thị/đề xuất theo atom (qua Segment/Route), không theo tour. Tour
chưa atomize = không có atom nào cho Slate dùng = xuất hiện trong danh sách chỉ gây nhiễu, tenant
bấm vào thấy trống. Lọc ngay từ gốc ở fetch_trips(), không đẩy việc lọc xuống Slate.

Việc cần sửa: đổi câu query hiện tại từ không điều kiện atom (LEFT JOIN hoặc không JOIN
tour_atoms) sang INNER JOIN tour_atoms (hoặc EXISTS subquery tương đương) — chỉ giữ tour có ít
nhất 1 dòng trong tour_atoms. Với ví dụ thật đã đo (wanderlux-travel: 8 tour rewrite, 2 đã
atomize) — sau khi sửa, fetch_trips() phải trả về đúng 2, không phải 8.

Live-verify bổ sung: đối chiếu số tour trả về mới với đúng số tour có DISTINCT tour_id trong
tour_atoms cho tenant đó (query trực tiếp DB) — phải khớp chính xác.

exploreasia-co vẫn 0 tour là đúng (chưa rewrite gì) — không phải vấn đề.

See `docs/implementation-notes/AA-500.md`'s "Follow-up (same day...) — 'Cách B'" section for the
implementation + live-verify evidence (exact tour_id-set match, not just count match, confirmed
for `wanderlux-travel`: 8 → 2).
