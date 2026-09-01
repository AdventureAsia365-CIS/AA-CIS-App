Build prompt AA-510 — giao Claude Code (01/09, S170). AA-515 đã Done, hết block.

Trước khi viết bất kỳ code/migration nào
Dùng git worktree riêng cho phiên build này (không làm việc trực tiếp trên checkout chính) — dọn sạch worktree sau khi xong.
Đọc lại routes.py thật tại /home/nghiep/projects/aa-cis/AA-CIS-App/docs/AI-gent-for automation works/aa-soscial-media-main/src/aa_social/routes.py (và ADR 0024 liên quan trong docs/adr/) — xác nhận qua code thật (không đoán):
Cách route_id được sinh trong repo gốc (hash? uuid? chuỗi ghép?) — báo cáo lại trước khi quyết định cách sinh ở AA-CIS. Nếu repo gốc không cho câu trả lời rõ ràng, mặc định dùng uuid4() dạng text cho route_id ở AA-CIS — ghi rõ lý do trong docs/claude_tasks/.
derive_routes()/family detection thật hoạt động thế nào (union-find? threshold áp dụng ở bước nào?).
BẮT BUỘC: lưu nguyên văn prompt này vào docs/claude_tasks/AA-510-build-route-hub.md trước khi bắt đầu code.
Khi cần dọn working tree, dùng git stash — không dùng git reset --hard.
Bối cảnh

Sub-issue AA-507. AA-515 (Ranking, điều kiện tiên quyết) đã Done — bảng acp_contract.atom_ranking đã tồn tại với (tenant_id, tour_id, segment_id, demand_rank, recurrence_rank, questions_rank, said_rank, total_rank).

Schema — Migration mới

1. acp_contract.hub

sql
CREATE TABLE acp_contract.hub (
  hub_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES shared.tenants(tenant_id),
  hub_name     text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

2. acp_contract.route

sql
CREATE TABLE acp_contract.route (
  route_id             text PRIMARY KEY,
  tenant_id            uuid NOT NULL REFERENCES shared.tenants(tenant_id),
  tour_id              text NOT NULL REFERENCES silver_aa_internal.raw_tours(tour_id),
  hub_id               uuid REFERENCES acp_contract.hub(hub_id),
  hub_name             text NOT NULL,
  ordered_segment_ids  jsonb NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now()
);

KHÔNG có cột family_id — Hub thay thế hoàn toàn qua FK hub_id.

3. acp_contract.subject

sql
CREATE TABLE acp_contract.subject (
  subject_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES shared.tenants(tenant_id),
  hub_name         text NOT NULL,
  route_snapshot   jsonb NOT NULL,
  selected_at      timestamptz NOT NULL DEFAULT now(),
  selected_by      text
);

route_snapshot KHÔNG FK sống vào route.route_id (ADR 0024).

Logic cần xây
services/acp_contract/route_detection.py — derive Route từ Segment đã ranking (JOIN atom_ranking, loại transit/unnamed-place), DELETE+INSERT whole mỗi lần chạy, chỉ Channel=Blog.
Hub matching: union-find Jaccard ≥ 0.3 (config, không hardcode) nhóm Route mới → match Hub cũ qua tour_id set/hub_name → tái dùng hub_id nếu khớp, tạo mới nếu không.
Service tạo Subject snapshot Route lúc user chọn.
Đóng AA-504 khi AA-510 Done.
Live-verify bắt buộc (trước + sau merge)

Route đúng thứ tự total_rank; rebuild-whole sạch không rác; hub matching gộp đúng family, tái dùng hub_id qua rebuild; subject snapshot bất biến khi route gốc đổi/xoá; xác nhận không FK sống subject→route.

Sau khi build xong

Không tự set Done — báo cáo, chờ soát. PR mang migration không auto-merge.
