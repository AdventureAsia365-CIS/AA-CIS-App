# Build prompt: AA-518 Việc C + AA-505 — GỘP 1 ĐỢT (per-stage model config + cost/quality tracking)

Source: Linear AA-518 comment `dc253419-f07d-4462-8e92-43c203e01be1`, posted by nghiep pham quoc,
2026-09-02T16:23:31.867Z. Saved verbatim per the build prompt's own instruction (STEP0 step 0)
before any code was written.

---

**Nguồn:** dùng bản này, bỏ mọi bản trước (round 1 account_route, round 2 task_class đều superseded). Đây là quyết định cuối: build thật, không chỉ thiết kế nữa.

Trước khi bắt đầu: lưu nguyên văn prompt này vào `docs/claude_tasks/AA-518-AA-505-per-stage.md`.

## 2 quyết định mới chốt (02/09/2026, S171) — áp dụng xuyên suốt

1. **quality_signal bắt buộc cho MỌI stage có gọi LLM** — kể cả stage không có Judge/Gate thật (ví dụ T5 atomize). Với stage không có judge, tự đề xuất 1 heuristic đơn giản đo được (ví dụ: T5 atomize — tỷ lệ atom bị soft-delete sau đó, hoặc số atom sinh ra/ngày so với kỳ vọng; không để trống, không bịa số nếu không đo được thật — nếu 1 stage cụ thể thực sự không thể đo được gì dù đã cân nhắc, báo cáo rõ lý do thay vì tự chế 1 con số vô nghĩa).
2. **Ghép làm 1 đợt build** — không tách phase (1) config trước / (2) dashboard sau như dự tính ban đầu. Build cả schema + persist call + UI admin chọn model + trang giám sát cây phân cấp trong cùng 1 đợt.

## STEP0 bắt buộc trước khi thiết kế cụ thể

1. Đọc `docs/implementation-notes/AA-518.md` — bảng 16 điểm gọi LLM đã điều tra (STEP0 Việc 1, round 3 build prompt trước). Với MỖI điểm, xác nhận lại: đã gán đúng `stage` cụ thể chưa (A0, A1, T2, T5, T7, T8, T9...), đã phân biệt `role` (`writer`/`judge`/`validate`) chưa. Đây là danh sách nền — không audit lại từ đầu, chỉ xác nhận/bổ sung nếu STEP0 lần này phát hiện thiếu.
2. Đối chiếu AA-434 audit gốc (`docs/claude_audit/AA-434-llm-usage-tracking-per-tenant-audit.md`) — AA-434 audit trước khi T8/T9 redesign, có thể chưa tính đủ các điểm judge/validate mới (`judge_client.py`, `judge_node.py`, các gate trong `quality_gates.py`). Bổ sung nếu thiếu.
3. Đọc `shared/llm_client/client.py` thật — xác nhận hàm nào hiện đọc hằng số cứng (`BEDROCK_SONNET` và tương tự), cần đổi sang đọc config DB. Xác nhận cơ chế cache trong process khả thi (tránh query DB mỗi lần gọi LLM) — đề xuất cache + invalidate khi admin đổi config qua UI.
4. Xác nhận provider/model thực sự khả dụng hôm nay (đã điều tra ở STEP0 Việc 1 AA-518): Claude (writer, qua acc1/acc3 satellite, KHÔNG qua acc2), GPT-4.1 (judge, qua OpenAI API trực tiếp, KHÔNG qua Bedrock vì GPT-5.6 AccessDenied). Palmyra X5 loại hẳn (throttle cứng). Thiết kế UI phải phản ánh đúng thực trạng — không tạo dropdown cho model không dùng được, nhưng có thể hiện nhãn "chưa dùng được, lý do X" để admin biết roadmap (theo yêu cầu round 3 trước).

## Schema (đề xuất, điều chỉnh nếu STEP0 phát hiện cần khác)

Bảng chung phục vụ cả 2 mục đích (Việc C: admin chọn model theo stage; AA-505: log mỗi lần gọi thật) — dùng chung 1 danh sách `stage` thống nhất, không lệch tên gọi:

```sql
-- Việc C: cấu hình admin chọn model theo stage (chỉ admin sửa, tenant không có quyền)
CREATE TABLE shared.llm_role_config (
  stage         text PRIMARY KEY,        -- 'A0','A1','T2','T5','T7','T8','T9',... giá trị cụ thể, không phải nhóm
  role          text NOT NULL,           -- 'writer' | 'judge' | 'validate'
  provider      text NOT NULL,           -- 'claude' | 'openai'
  model_id      text NOT NULL,
  account_route text,                    -- 'acc1' | 'acc3' | NULL (chỉ áp dụng cho Claude)
  is_active     boolean NOT NULL DEFAULT true,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  updated_by    uuid REFERENCES shared.admin_users(admin_user_id)
);

-- AA-505: log mỗi lần gọi LLM thật (persist per-call, không discard như hiện tại)
CREATE TABLE shared.llm_call_log (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid REFERENCES shared.tenants(tenant_id),  -- NULL cho A-series (aa_internal)
  stage                 text NOT NULL,   -- khớp enum/danh sách với llm_role_config.stage
  role                  text NOT NULL,   -- 'writer' | 'judge' | 'validate'
  model                 text NOT NULL,
  tokens_in             integer,
  tokens_out            integer,
  cost_usd              numeric,
  quality_signal        jsonb,           -- gate pass/fail, điểm judge, hoặc heuristic tự đề xuất — BẮT BUỘC có giá trị cho mọi stage, không để NULL mặc định
  content_piece_id       uuid,           -- liên kết ngược nếu áp dụng được, NULL nếu không
  angle_gate_request_id  uuid,           -- liên kết ngược nếu áp dụng được, NULL nếu không
  created_at            timestamptz NOT NULL DEFAULT now()
);
```

Điều chỉnh cột/kiểu dữ liệu nếu STEP0 phát hiện khác thực tế (không tự tin theo đề xuất trên khi code thật khác) — báo cáo rõ nếu đổi.

## Việc cần làm

1. Migration 2 bảng trên (hoặc điều chỉnh theo STEP0).
2. Seed `llm_role_config` với mặc định đã duyệt: việc dài (writer nội dung dài, ví dụ T9 write, T2 rewrite) → Sonnet; việc ngắn (T5 atomize, validate nhỏ) → Haiku; Judge (mọi vị trí) → GPT-4.1 qua OpenAI trực tiếp. Fallback Sonnet→Haiku→GPT giữ nguyên như đã có.
3. Sửa `shared/llm_client/client.py` — đọc config từ `llm_role_config` theo `stage` thay vì hằng số cứng, có cache trong process + invalidate khi admin đổi.
4. Thêm persist call ở toàn bộ điểm gọi LLM đã xác nhận (16 điểm AA-518 + bổ sung nếu STEP0 tìm thêm) — ghi vào `llm_call_log`, bao gồm `quality_signal` cho MỌI stage (theo quyết định 1 ở trên — heuristic riêng cho stage không có judge thật).
5. UI admin — trang chọn model theo stage:
   - Danh sách từng stage cụ thể (không gộp nhóm), mỗi dòng: stage name, role, model hiện tại, dropdown đổi model (chỉ hiện option thực sự khả dụng, nhãn rõ cho option chưa dùng được).
   - Luồng: chọn model mới → confirm dialog (đổi model ảnh hưởng toàn hệ thống, không phải hành động cá nhân) → lưu.
   - Trạng thái UI: loading khi lưu, lỗi giữ giá trị cũ không đổi ngầm, thành công hiện rõ model đang active.
   - Viết wireframe/luồng/trạng thái đầy đủ trước khi code (theo quy ước chung).
6. UI trang giám sát cây phân cấp — Tenant → Model → Stage:
   - Mỗi nhánh hiện cost_usd + chỉ số chất lượng (tỷ lệ pass gate, điểm judge, hoặc heuristic).
   - Tự đề xuất cấu trúc hợp lý (accordion expand từng cấp, hoặc bảng pivot) — báo cáo thiết kế trong implementation notes trước khi hoàn thiện, không cần dừng lại chờ duyệt vì đã gộp 1 đợt.
   - Viết wireframe/luồng/trạng thái đầy đủ trước khi code.
7. Endpoint đọc lại — dùng chung cho AA-501 (góc AA/A4) và trang giám sát mới nếu hợp lý.

## Live-verify bắt buộc

- Đổi model cho 1 stage qua UI thật → gọi LLM thật ở stage đó → xác nhận model mới được dùng (log/trace xác nhận, không chỉ tin UI).
- `llm_call_log` ghi đúng sau ít nhất vài lần gọi thật qua nhiều stage khác nhau (bao gồm ít nhất 1 stage có judge thật và 1 stage dùng heuristic) — query trực tiếp DB xác nhận `quality_signal` có giá trị thật, không NULL, không giả định.
- Trang giám sát hiện đúng dữ liệu thật vừa ghi — cây Tenant→Model→Stage khớp với DB.
- Cache invalidate đúng: đổi model qua UI, gọi lại LLM ngay sau đó (không cần đợi restart service) → xác nhận dùng model mới, không phải model cũ do cache chưa invalidate.
- Regression: mọi stage cũ (không đổi model) vẫn chạy đúng hành vi như trước.

## Sau khi build xong

Không tự set Done cho AA-518 hoặc AA-505. Comment evidence đầy đủ lên CẢ HAI issue riêng biệt (không gộp chung 1 comment) — vì đây là 2 issue Linear khác nhau dù build chung 1 đợt. Nêu rõ schema cuối cùng dùng (nếu khác đề xuất), danh sách stage đã cover, và bất kỳ stage nào không đo được quality_signal (nếu có, kèm lý do).

---

## Session note (added by Claude Code, not part of the original prompt)

Nghiệp's mid-turn instruction when this build was kicked off: create a fresh worktree (done —
`feat/aa-518-aa-505-per-stage-llm-config`, off `origin/main`), and this is understood to be a
large scope (2 UIs + new schema + edits at 16+ LLM call sites) that may take multiple turns —
that's fine, this build prompt already says not to self-set Done, wait for Nghiệp's review.
