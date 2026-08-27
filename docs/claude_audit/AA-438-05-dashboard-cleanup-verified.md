# AA-438-05 — Dashboard/pipeline_runs: 6 mục còn treo, verified 27/08/2026

Đối chiếu 6 mục từ `AA-438-00-SUMMARY-admin-tier-audit.md` (#1, #2, #3, #4, #6, #11) với code +
data hiện tại. 5/6 mục đối chiếu qua code (grep/git log). #6 verify lại qua live query thật (RDS
`aa-cis-dev-db`, S3-mediated ECS exec, task `1a8e3a7de32747dcac9fff7ed244512e`) vì tenant nguồn
của 11 row mồ côi (`test-agency`, `9fb0a3db-...`) vừa bị xóa data hoàn toàn ở AA-473 sáng nay.

Không sửa code trong task này.

---

## #6 — Verify chi tiết (live query)

**Kết quả: #6 gốc đã hết — nhưng phát sinh 1 hit mới, KHÔNG PHẢI cùng loại bug, là false-positive
do schema đổi (migration 107, AA-425).**

Query lại đúng logic audit gốc (`silver_aa_internal.review_queue` JOIN
`silver_aa_internal.generated_content` qua `generated_content_id`, lọc `review_status='pending'`):

| Chỉ số | Giá trị |
|---|---|
| Tổng `review_queue` `review_status='pending'` | 37 (audit gốc: 48 — giảm 11, khớp với AA-473 xóa data) |
| Row mồ côi (LEFT JOIN generated_content → NULL) | **1** (audit gốc: 11) |
| Tenant `test-agency` (`9fb0a3db-59aa-468a-a082-ded01ac50bee`) còn tồn tại trong `shared.tenants`? | **Không** — 0 row |
| Row `review_queue` còn lại của tenant đó (bất kỳ status) | **0** |

→ **11 row mồ côi gốc của `test-agency`: xác nhận đã hết, do tenant bị xóa hoàn toàn trong đợt
cleanup AA-473 (xóa cả tenant lẫn data liên quan), không phải do code được sửa.**

**Nhưng 1 row mồ côi mới xuất hiện khi chạy lại đúng query gốc:**

```json
{
  "id": "00cbd888-bdd8-42ce-9abd-ddc02cc3709a",
  "tour_id": "b0e111a9-aa18-4293-99dd-e2ee5b7820a3",
  "generated_content_id": null,
  "tenant_id": "a1b2c3d4-0001-4000-8000-000000000001",
  "review_status": "pending",
  "created_at": "2026-08-24 10:50:20+00:00",
  "tenant_tour_version_id": "4dff663e-69d0-4d79-b890-068d92c3bffb",
  "failure_summary": "T3 QA failed after 2 repair attempt(s) — 3 structural, 0 grounding issue(s)",
  "escalate_detail": "[structural:MISSING_FIELD, structural:FORBIDDEN_WORD, structural:ITINERARY_DAY_COUNT_MISMATCH]"
}
```

- `tenant_id` = `a1b2c3d4-0001-...` → `shared.tenants.slug = 'wanderlux-travel'`, `is_active=true`
  — **một tenant thật, đang hoạt động** (nằm trong danh sách "Real-looking business tenants to
  keep" của chính audit gốc), **không phải test/dev tenant**.
- Root cause: **migration `107_aa425_tenant_qa_gate.sql`** (AA-425, T3 tenant-facing QA gate,
  merged sau ngày audit gốc chạy 22/08) đã chủ đích đổi schema:
  `ALTER TABLE silver_aa_internal.review_queue ALTER COLUMN generated_content_id DROP NOT NULL,
  ADD COLUMN tenant_tour_version_id uuid` — comment trong migration ghi rõ: *"reuse
  `review_queue` for T3 escalate + tenant-facing filtered view ... generated_content_id [is now
  nullable for T3 rows] ... tenant_tour_version_id links an escalate row back to its real
  source"*.
- Nói cách khác: `review_queue` giờ được **2 luồng khác nhau** dùng chung — luồng A1→A2 gốc
  (admin, `aa_internal`, luôn có `generated_content_id`) và luồng T3 QA gate mới (tenant-facing,
  dùng `tenant_tour_version_id` thay vì `generated_content_id`, nên `generated_content_id=NULL`
  là **thiết kế đúng, không phải lỗi**). Row trên là kết quả thật của việc T3 QA gate reject 1
  bản rewrite của `wanderlux-travel` sau 2 lần repair (structural checks fail: MISSING_FIELD,
  FORBIDDEN_WORD, ITINERARY_DAY_COUNT_MISMATCH) — hoạt động đúng như thiết kế AA-425.

**Kết luận #6:**
- 11 row mồ côi gốc (test-agency): **✅ đã hết**, do xóa tenant ở AA-473 — không phải do fix bug,
  cần lưu ý nếu tenant tương tự phát sinh lại (mismatch giữa `review_queue` schema dùng chung và
  per-tenant-schema pattern tài liệu ghi trong CLAUDE.md) thì vẫn có thể tái diễn.
- Query "orphan-detection" gốc của audit **đã lỗi thời sau AA-425** — cần thêm điều kiện loại
  trừ row có `tenant_tour_version_id IS NOT NULL` (tức là row T3, không phải row A1/A2) mới đúng
  logic hiện tại. Không phải bug code cần sửa, nhưng bất kỳ ai chạy lại đúng câu query gốc để
  audit trong tương lai sẽ bị false-positive nếu không biết điều này.

---

## Bảng tổng hợp 6 mục

| # | Mô tả (rút gọn) | Nơi | Trạng thái hiện tại | Có ảnh hưởng người dùng thật? | Ưu tiên fix |
|---|---|---|---|---|---|
| 1 | `pipeline_runs.status` kẹt ở `'ingesting'` mãi mãi khi batch có ≥1 tour hitl | `services/export/handler.py` | **Còn nguyên trạng** — file không bị đụng bởi bất kỳ commit S157-161 nào | Không — chỉ dashboard hiển thị sai, không gate hành vi pipeline thật (đã double-check ở audit gốc) | **P3 — thấp.** Chỉ cosmetic, không chặn luồng thật |
| 2 | Dashboard "Pipeline Activity/Pass Rate" bucket theo `started_at` + filter `status != 'ingesting'` → kết hợp với #1 khiến bảng luôn trống dù đang rewrite thật | `admin_pipeline.py` (`GET /admin/metrics`, hiện ~dòng 3194-3204, số dòng dịch chuyển do file dài thêm) | **Còn nguyên trạng** | Không — chỉ dashboard | **P3 — thấp.** Cùng gốc với #1, nên fix chung 1 PR nếu làm |
| 3 | Nghi ngờ double-fire ingestion: Lambda S3-trigger + admin Upload page's `process_file()` cùng chạy trên 1 S3 object | `admin_pipeline.py` upload path (dòng ~1204-1205) | **Còn nguyên trạng, vẫn unconfirmed** — chưa verify qua CloudWatch | **Nếu có thật: CÓ ảnh hưởng thật** — double-fire nghĩa là 1 tour có thể bị ingest/rewrite 2 lần, tốn cost Bedrock thật, có thể tạo duplicate rows | **P1 — cần verify trước khi định ưu tiên.** Chưa biết có xảy ra không; nếu confirm có, đây là bug nặng nhất trong 6 mục (tốn tiền thật + data duplicate), không phải cosmetic |
| 4 | `pipeline_runs` accounting UPDATE bị skip âm thầm khi `batch_id` không phải UUID hợp lệ (run ad-hoc/verify) | `admin_pipeline.py` (`_is_uuid()` guard, dòng ~37-39, 691-712) | **Đã đủ, không cần sửa thêm** — có log cảnh báo `AA-210` khi skip, đúng như audit mô tả "logged only". Đã re-confirm hôm nay, kết luận AA-446 vẫn đúng | Không — chỉ ảnh hưởng run ad-hoc/verify, có log để trace nếu cần | **➖ Đóng, không đưa vào backlog fix** |
| 6 | 11 row `review_queue` mồ côi của tenant `test-agency` (`9fb0a3db-...`) | live data | **✅ Đã hết** — tenant bị xóa hoàn toàn ở AA-473 (0 row `shared.tenants`, 0 row `review_queue`). Query gốc chạy lại phát sinh 1 false-positive mới do schema đổi ở AA-425 (migration 107) — không phải bug, là T3 QA-gate escalation hợp lệ của tenant thật `wanderlux-travel` | Không (row false-positive là hoạt động đúng thiết kế) | **➖ Đóng mục gốc.** Ghi chú riêng: nếu audit lại `review_queue` trong tương lai, thêm điều kiện loại `tenant_tour_version_id IS NOT NULL` để tránh false-positive |
| 11 | Dashboard "Model Usage/LLM Calls": `calls = COUNT(*)` số row `generated_content`, không phải số lệnh gọi LLM thật (undercounts do bỏ sót retry/judge/brand_audit/flag_fix/nudge sub-calls) | `admin_pipeline.py` (`models`/`llm_calls` query, hiện ~dòng 3227-3269) | **Còn nguyên trạng** | Không — chỉ dashboard hiển thị số liệu sai, không ảnh hưởng chi phí/luồng thật (chi phí thật đã track đúng qua `cost_usd`, chỉ riêng con số "calls" hiển thị sai) | **P3 — thấp.** Sai số liệu hiển thị, không sai tiền thật |

---

## Khuyến nghị ưu tiên tổng thể

1. **#3 (double-fire ingestion) là mục duy nhất cần xử lý trước** — không phải vì đã confirm là
   bug, mà vì đây là mục duy nhất trong 6 mục **có khả năng** ảnh hưởng dữ liệu/chi phí thật nếu
   đúng. Bước tiếp theo hợp lý: verify qua CloudWatch Logs (`/ecs/aa-cis-dev` + Lambda
   `aa-cis-dev-ingestion` log group) xem có 2 lần ingest cho cùng 1 `s3_key` trong cùng 1 khoảng
   thời gian ngắn hay không — việc này AA-438-01 đã để ngỏ, chưa ai làm.
2. **#1, #2, #11 là nhóm "dashboard hiển thị sai, không chặn luồng thật"** — có thể gộp lại làm
   1 PR nhỏ nếu Nghiệp muốn dashboard đúng số, nhưng không cấp bách, không có deadline nào ép.
3. **#4 và #6 đóng, không đưa vào backlog** — #4 đã đủ tốt (có log), #6 đã tự hết nhờ cleanup dữ
   liệu (không phải nhờ sửa code — lưu ý nếu tenant test tương tự phát sinh lại, vấn đề gốc vẫn
   có thể tái diễn vì code chưa thực sự sửa).

## Should know (cho người đọc PR/báo cáo này sau)

- Query "orphan review_queue" của audit gốc (`AA-438-02`) **không còn đúng 100%** sau migration
  107 (AA-425) — bất kỳ ai tái sử dụng câu query đó cần biết `generated_content_id IS NULL` giờ
  là trạng thái hợp lệ cho row T3, không chỉ là dấu hiệu mồ côi.
- Việc #6 "hết" là do xóa tenant, không phải do sửa code — nếu coi đây là một dạng "regression
  test", nó không pass theo nghĩa thông thường (không có unit test nào bảo vệ trường hợp
  per-tenant-schema mismatch mà audit gốc nghi ngờ).
- Không có thay đổi code nào trong task này — toàn bộ là read-only (query SELECT, grep, git log).
