# AA-479 — Full schema audit từ dữ liệu thật, xác nhận lại phạm vi migration 121

Ngày chạy: 27/08/2026. Nguồn: live query trực tiếp trên RDS `aa-cis-dev-db` (S3-mediated ECS exec,
task `dc72740f72684a4fa06a3c2aa565defd`) — không dựa vào skill cũ, không dựa vào STEP0 cũ, đọc lại
từ đầu bằng `pg_catalog`/`information_schema`/`pg_constraint` thật.

**KHÔNG sửa DB, KHÔNG chạy migration nào trong task này** — toàn bộ là SELECT read-only.

---

## Bước 1 — Dump schema đầy đủ

| Chỉ số | Số liệu thật (27/08/2026) | Số liệu skill cũ (11/06/2026) |
|---|---|---|
| Schema (loại trừ pg_catalog/information_schema/pg_toast) | **11** | không ghi rõ |
| Bảng (relkind='r') | **76** | 47 |
| View (relkind='v') | **4** | không track |
| Cột | **1021** | 653 |
| FK constraint (pg_constraint, contype='f') | **81** | không track |
| Row `shared.schema_versions` | **88** | không track |

**Xác nhận số "47 bảng" cũ đã sai — thật ra là 76**, chênh +29 bảng, khớp đúng những gì
migration 100→119 (AA-397 tới AA-472, tổng 30 migration mới) đã thêm mà skill chưa từng cập nhật.

### Schema breakdown thật

| Schema | Bảng | View |
|---|---|---|
| `acp_contract` | 3 | 1 (`v_trip_registry`) |
| `acp_deliver` | 3 | 0 |
| `acp_gold_output` | 1 | 0 |
| `acp_shared` | **29** (cũ ghi 13) | 0 |
| `acp_silver_s2` | 2 | 0 |
| `acp_silver_s3` | 2 | 0 |
| `acp_silver_s4` | 2 | 0 |
| `gold_aa_internal` | 4 | 0 |
| `public` | 4 | 0 (LangGraph checkpoint tables — skill cũ chưa từng nhắc) |
| `shared` | 18 (cũ ghi 16) | 3 (`v_batch_stats`, `v_pipeline_summary`, `v_tenant_monthly_usage`) |
| `silver_aa_internal` | 8 | 0 |

**Phát hiện phụ:** **0 schema per-tenant** (`silver_{slug}`/`gold_{slug}`) tồn tại trên DB thật,
dù kiến trúc "schema-per-tenant Medallion" được ghi trong migration 003 (v3.0) và README cũ. Tất
cả 14 tenant hiện tại (kể cả B2B) đều chỉ dùng `shared.*`/`acp_shared.*`/`gold_aa_internal.*` —
pattern per-tenant-schema chưa từng thật sự được kích hoạt. Không thuộc phạm vi audit này để điều
tra sâu hơn, chỉ ghi nhận vì skill cũ nói sai (ngụ ý các schema này tồn tại).

**Migration:** `shared.schema_versions` có 88 row, mới nhất **119** (AA-472, 26/08/2026 14:49
UTC). Xác nhận trực tiếp: `'120' NOT IN schema_versions`, `'121' NOT IN schema_versions` — **cả 2
migration (AA-473 Gate A drop, AA-477 ACPv1 cluster drop) đều CHƯA apply**, dù code của cả 2 PR đã
merge từ lâu (draft SQL file tồn tại trong repo, nhưng chưa ai chạy INSERT vào schema_versions).

---

## Bước 2 — Xác nhận lại phạm vi migration 121

Đọc lại `api/migrations/121_drop_acpv1_stage_chain.sql` (đã merge, main branch) — 15 bảng đúng
như draft:

| # | Bảng | Row count thật (27/08, vừa đếm lại) | Khớp draft? |
|---|---|---|---|
| 1 | `acp_silver_s4.blog_drafts` | 0 | ✅ |
| 2 | `acp_shared.acp_hitl_requests` | 0 | ✅ |
| 3 | `acp_shared.acp_lessons_agency` | 0 | ✅ |
| 4 | `acp_shared.acp_lessons_shared` | 0 | ✅ |
| 5 | `acp_shared.acp_run_context` | 0 | ✅ |
| 6 | `acp_shared.acp_stage_checkpoints` | 0 | ✅ |
| 7 | `acp_shared.pipeline_checkpoints` | 0 | ✅ |
| 8 | `acp_silver_s3.ads_plan` | 0 | ✅ |
| 9 | `acp_silver_s3.content_calendars` | 0 | ✅ |
| 10 | `acp_silver_s4.social_content` | 0 | ✅ |
| 11 | `acp_gold_output.published_content` | 0 | ✅ |
| 12 | `acp_silver_s2.visibility_reports` | 0 | ✅ |
| 13 | `silver_aa_internal.tour_content_versions` | 0 | ✅ |
| 14 | `acp_shared.acp_stage_runs` | 0 | ✅ |
| 15 | `acp_shared.acp_runs` | 0 | ✅ |

**Cả 15/15 bảng khớp chính xác 100% với dump thật — không bảng nào bị đổi tên, đổi schema, hay
phát sinh row mới kể từ khi migration 121 được draft.** Phạm vi 15 bảng vẫn đúng, không cần điều
chỉnh.

### Quét toàn bộ dump tìm bảng chết khác — TÌM THẤY 6 BẢNG BỔ SUNG, KHÔNG nằm trong 121

Quét toàn bộ 76 bảng theo tiêu chí: 0 row + không caller thật trong `api/`/`services/` (grep trực
tiếp, không suy đoán) + không nằm trong 15 bảng migration 121:

| Bảng | Row | Caller code | Nguồn gốc | Vì sao STEP0 cũ bỏ sót |
|---|---|---|---|---|
| `acp_shared.acp_cms_publish_queue` | 0 | **0** (grep toàn `api/`, `services/` — rỗng) | Migration 039 (AA-100), CMS publish queue CHO `v1_s4_blog.py` cũ (đã xóa ở AA-477 Phase 1) | **Không có FK constraint thật** — cột `run_id`/`draft_id` là `uuid` trần, không FK. STEP0's `pg_constraint`-based FK-graph traversal (đúng phương pháp, nhưng chỉ bắt được FK CÓ constraint) không thể thấy bảng này vì nó không FK-link vào `acp_runs` ở tầng DB, dù link ở tầng ứng dụng |
| `acp_shared.idempotency_keys` | 0 | **0** | Migration 029 (AA-43), tạo riêng "for S2 run dedup" | S2 (`services/acp/s2/`) **đã bị xóa source từ trước** (khả năng cao ở AA-467 "remove ACPv1 S2 dead code" — chỉ còn `__pycache__` rác, `git ls-files services/acp/s2/` rỗng). Bảng idempotency riêng của S2, không FK vào `acp_runs`, không nằm trong "cụm 14 bảng" mà STEP0 tìm |
| `shared.lessons_registry` | 0 | **0** | Migration 002/003 (schema v2/v3, **thời điểm sớm nhất trong toàn bộ lịch sử schema**, trước cả khi ACP tồn tại) | Không phải ACPv1, không nằm trong `acp_shared` namespace — ngoài phạm vi tìm kiếm "acp_*" của STEP0 hoàn toàn |
| `public.checkpoints` | 0 | 0 caller `AsyncPostgresSaver`/`PostgresSaver`/`checkpointer` bất kỳ đâu trong `api/`, `services/`, `shared/` | LangGraph runtime tự tạo (KHÔNG migration file nào trong `api/migrations/` tạo bảng này) | Ở schema `public`, không phải `acp_*` — hạ tầng LangGraph dùng chung, khả năng cao từ S2's checkpointer cũ (test `tests/acp_s2/test_checkpointer.py` xác nhận trực tiếp bằng thực nghiệm — xem dưới) |
| `public.checkpoint_blobs` | 0 | (cùng cơ chế) | (cùng cơ chế) | (cùng lý do) |
| `public.checkpoint_writes` | 0 | (cùng cơ chế) | (cùng cơ chế) | (cùng lý do) |

**Bằng chứng thực nghiệm cho nhóm checkpoint (không chỉ suy luận):**
```
$ python3 -c "import services.acp.s2.graph"
ModuleNotFoundError: No module named 'services.acp.s2.graph'

$ pytest tests/acp_s2/test_checkpointer.py -v
FAILED test_checkpointer_type — AttributeError: module 'services.acp.s2' has no attribute 'graph'
(1 failed, 3 passed)
```
`services/acp/s2/` chỉ còn `__pycache__` (bytecode rác), source `.py` đã mất, `git ls-files` xác
nhận không track gì trong thư mục này. 7 file test (`tests/acp_s2/*.py`, `tests/acp/
test_s1_state_bridge.py`, `test_s2_keyword_cap.py`, `test_confidence_scorer.py`,
`test_s2_cannibalization.py`) vẫn import `services.acp.s2.*` — đây chính là 7/62 trong danh sách
"pre-existing failures" mà session trước đã diff-confirm (không phải lỗi DB-dependent như giả
định trước đó — thật ra là lỗi vì module đã bị xóa mà test chưa dọn theo).

**Bằng chứng cho `acp_cms_publish_queue` bị "kế thừa tinh thần" bởi T11 (giống pattern
`wordpress.py` ở STEP0 lần 2), không phải kế thừa dữ liệu:** migration `116_acp_shared_publish_log.sql`
(T11's bảng `publish_log` thật, đang sống) tự ghi trong comment:
> *"Mirrors the real precedent already in this schema for 'a delivery/publish queue as its own
> table' — acp_shared.acp_cms_publish_queue (migration 039) — but scoped to content_piece instead
> of the old pre-T-series blog_drafts."*

Xác nhận: đây là quan hệ THIẾT KẾ (T11 học theo pattern cũ), KHÔNG phải bảng cũ vẫn được dùng —
`publish_log` là bảng MỚI, HOÀN TOÀN TÁCH BIỆT, không phải `acp_cms_publish_queue` được viết tiếp.

**Không tự ý thêm 6 bảng này vào migration 121** — giữ nguyên phạm vi 15 bảng đã go-ahead, đúng
yêu cầu. Đề xuất xử lý ở đợt sau (AA-480 hoặc số issue mới), theo đúng mẫu STEP0 đã dùng.

---

## Bước 3 — Phân loại toàn bộ 76 bảng theo trạng thái dùng thật

### Nhóm 1 — A/T-series đang dùng thật (33 bảng)

| Bảng | T-stage/N-nhịp | Ghi chú |
|---|---|---|
| `acp_shared.tenant_atom_state` | N1/T6 | 18 row |
| `acp_shared.tenant_onboarding` | N1 | 2 row (Gate A đã xóa AA-473, cột vẫn còn) |
| `acp_shared.marketplace_portfolios` | Marketplace/N1 seed | 11 row — giữ lại làm seed source (AA-472) |
| `acp_shared.competitor_index_cache` | B4 CompetitorIndex | 1 row |
| `acp_silver_s2.competitor_inputs` | B4 CompetitorIndex | 0 row nhưng có caller thật (`v1_competitors.py`) |
| `acp_shared.quarter_plan` / `quarter_plan_version` | Gate B / N5 | 5 / 11 row |
| `acp_shared.year_plan` | T7/N4 | 1 row |
| `acp_shared.content_metric_snapshot` | T7/N4 | 0 row, caller `services/acp_shared/content_metrics.py` |
| `acp_shared.tenant_config` | N4-N6 | 1 row |
| `acp_shared.angle_gate_request` / `angle_gate_option` | T8 | 6 / 15 row |
| `acp_shared.content_piece` | T9/T10 | 0 row (data lifecycle, KHÔNG chết — caller `v1_publish.py`, `acp_content_writing/service.py`) |
| `acp_shared.publish_log` | T11 | 0 row, caller `v1_publish.py`, `admin_a4.py` |
| `acp_shared.acp_v2_runs` / `acp_v2_slots` | N7/N8 | 14 / 47 row |
| `acp_shared.unknown_ledger` | N7 C3 | 35 row |
| `acp_deliver.packets` / `pieces` / `tenant_tour_pages` | N7/N8 | 4 / 135 / 87 row |
| `acp_contract.tour_atoms` / `atom_decompose_jobs` / `s1_from_atom_runs` | N2/T5/T6 | 7 / 87 / 2 row |
| `acp_contract.v_trip_registry` (view) | N4-N6 contract | — |
| `shared.tenant_integrations` | T11 (WordPress) | 0 row (chưa tenant nào connect thật — khớp phát hiện STEP0 lần 2 "0 secret") |
| `shared.tenant_brand_rule_versions` | T0 | 0 row, caller `acp_brand_brief_parser/db.py` |
| `shared.tenant_brand_rules` | T0 | 1 row |
| `shared.tenant_brand_rules_deleted_aa404` | T0 (archive) | 6 row — bảng lưu trữ tay từ điều tra AA-404, không phải bảng nghiệp vụ |
| `shared.tenant_export_config` / `tenant_seo_config` | tenant config | 3 / 3 row |
| `gold_aa_internal.tenant_tour_versions` | T2 rewrite output | 10 row |
| `acp_shared.acp_quota_ledger` | GDPR/quota | 0 row, caller `admin.py` |

### Nhóm 2 — CIS S1 core (aa_internal, KHÁC ACPv1, sống độc lập) — 10 bảng

`silver_aa_internal.raw_tours` (793), `raw_sources` (37), `generated_content` (228),
`quality_scores` (206), `seo_context` (50), `review_queue` (42), `upload_staging` (4),
`gold_aa_internal.published_tours` (71), `content_exports` (0, caller `v1_exports.py` —
**đính chính CLAUDE.md tech debt note "content_exports table does not exist" — SAI, bảng CÓ tồn
tại ở `gold_aa_internal`, chỉ không tồn tại ở `shared`**), `webhook_deliveries` (0, tech debt biết
trước, deferred P2 — khớp CLAUDE.md).

### Nhóm 3 — Hạ tầng chung (11 bảng + 3 view)

`shared.schema_versions` (88), `audit_log` (2), `tenants` (3), `admin_users` (4),
`membership_plans` (5), `notifications` (39), `tenant_api_usage` (3100), `prompt_eval_runs` (3),
`pipeline_jobs` (46), `pipeline_runs` (38), `pipeline_lessons` (0, caller `admin_pipeline.py` +
`content_generation/flag_fix_node.py` — CIS S1 lesson mechanism, KHÔNG chết), `shared.v_batch_stats`
/ `v_pipeline_summary` / `v_tenant_monthly_usage` (view).

### Nhóm 4 — Nghi ngờ chết/mồ côi, NGOÀI phạm vi 15 bảng migration 121 (6 bảng, đã liệt kê chi
tiết ở Bước 2) — CHỈ GẮN CỜ, KHÔNG đề xuất xóa ngay

`acp_shared.acp_cms_publish_queue`, `acp_shared.idempotency_keys`, `shared.lessons_registry`,
`public.checkpoints`, `public.checkpoint_blobs`, `public.checkpoint_writes`.

Riêng `shared.acp_runs` (khác `acp_shared.acp_runs`) — **không xếp vào nhóm 4** vì đã có caller
thật (`services/export/handler.py`, A0-A3 pipeline) — đây là "naming trap" đã biết (AA-438 #15),
không phải bảng chết, chỉ trùng tên.

---

## Kết luận — trả lời trực tiếp câu hỏi Nghiệp đặt ra

**Migration 121 (15 bảng đã go-ahead): AN TOÀN CHẠY NHƯ CŨ, không cần điều chỉnh.**

Cơ sở: cả 15 bảng khớp 100% dump thật hôm nay (schema, tên, 0 row) — không có gì thay đổi từ lúc
draft. Audit từ đầu bằng dữ liệu thật (không dựa lại vào STEP0 cũ) xác nhận độc lập, không mâu
thuẫn với kết luận trước.

**PHÁT HIỆN THÊM 6 bảng chết khác — KHÔNG gộp vào 121, để xử lý đợt sau:**
`acp_shared.acp_cms_publish_queue`, `acp_shared.idempotency_keys`, `shared.lessons_registry`,
`public.checkpoints`, `public.checkpoint_blobs`, `public.checkpoint_writes`. Tất cả đều 0 row + 0
caller code thật, có bằng chứng cụ thể riêng từng bảng (xem Bước 2). Đề xuất Nghiệp mở issue mới
(gợi ý AA-480) nếu muốn dọn tiếp — không tự ý mở rộng phạm vi 121.

**Ghi chú phụ đáng chú ý** (không phải bug, chỉ để biết): migration 120 (AA-473) cũng chưa apply
— nếu Nghiệp định chạy 121, có thể cân nhắc chạy cả 120 cùng lúc (không thuộc phạm vi task này,
chỉ nêu ra để Nghiệp quyết).

---

*Chưa chạy migration 121, chưa xóa bảng nào. Dừng chờ Nghiệp review.*
