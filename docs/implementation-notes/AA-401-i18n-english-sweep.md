# AA-401 — Dịch nốt text tiếng Việt còn sót sang tiếng Anh

Nguồn: `docs/claude_audit/i18n-tenant-layout-audit.md` (STEP0, phiên trước) + phần Mirror
tab trong issue AA-401 gốc. Sửa string trực tiếp, không dựng i18n library (quy mô nhỏ).

## Decisions

- **Backend `ASSIGNED_ANGLES` (api/routers/admin.py) dịch khớp CHÍNH XÁC với bản FE đã có
  sẵn** (`frontend/app/admin/tenants/page.tsx`, tự dịch từ AA-389) thay vì tự dịch lại từ
  đầu — 2 bên vốn được comment ghi rõ "mirrored, keep in sync", và FE side đã là câu chữ
  đã qua review/dùng thật (angle-picker buttons). Dùng lại nguyên xi tránh 2 câu tiếng Anh
  khác nhau cho cùng 1 khái niệm ở 2 nơi.
- **Phát hiện thêm 1 chỗ ngoài 8 mục liệt kê trong issue**: hàm `_derive_field_failures()`
  (`api/routers/admin_pipeline.py`, dùng bởi `GET /admin/review-queue`, AA-240/AA-241) có
  9 message tiếng Việt (`reason` field) render trực tiếp ở `frontend/app/admin/review/
  page.tsx:136` (`{f.reason}`). STEP0 audit trước không bắt được vì quét theo keyword
  `detail/error/message/msg/reason` TRÊN CÙNG DÒNG — các dòng này gọi `add(field, code,
  reason)` (positional, không có tên field `reason=` trên dòng). Tìm thấy qua verify-grep
  bắt buộc của chính issue này (quét toàn bộ `admin_pipeline.py`, không chỉ 3 dòng đã liệt
  kê). Dịch nốt luôn vì đúng tinh thần "toàn bộ text tiếng Việt còn sót" của tên issue, và
  vì verify step của issue yêu cầu "xác nhận 0 kết quả còn lại trong phần UI/message thật"
  — để lại sẽ fail chính verify step này. Không tự ý mở rộng gì khác ngoài phát hiện cụ
  thể này.
- Message ngắn (label/reason fragment, không phải câu đầy đủ) giữ **không dấu chấm cuối**,
  khớp style sibling có sẵn cùng dict/array (`"distinctiveness"`, `"subtitle generic/off-
  brand"`) — theo đúng convention AA-387/AA-389 đã dùng ("sentence case, no trailing
  punctuation on headings/labels/buttons; full sentences keep normal punctuation").

## Changed

1. `frontend/app/admin/master-content/page.tsx` — 3 dòng (2 tooltip `ScoreBar` + 1 caption
   dưới score bar, dòng ~629/633/636) — dịch cả câu, không giữ mixed VN/EN.
2. `frontend/app/admin/curation/page.tsx` — 2 dòng: `StatCard` sub-label (~562, "chưa có"
   → "none yet", giữ nguyên `(AA-317)` reference + cấu trúc ternary không đổi) và câu thân
   dialog xác nhận xoá atom (~791).
3. `api/routers/admin_pipeline.py`:
   - `POST /admin/pipeline/ingest-s3` (dry_run) — 3 message (~1127/1153/1159). Field name
     `reason` (`"duplicate_tour"` etc.) giữ nguyên — đó là code, không phải display text,
     đúng chỉ dẫn issue.
   - `_derive_field_failures()` (~2113-2152) — 9 `reason` string (phát hiện thêm, xem
     Decisions) — `META_INCOMPLETE_SENTENCE`, `BRAND_SEO_META_VIOLATION`,
     `HIGHLIGHTS_NOT_LIST`, `HIGHLIGHTS_TOO_FEW`, `MISSING_FIELD` (dynamic per-column),
     `FORBIDDEN_WORD`, và 3 static-label trong `_static` dict
     (`HIGHLIGHTS_TOO_GENERIC`/`ITINERARY_STRUCTURE_WEAK`/`DFS_INTENT_UNDERUSED`).
4. `api/routers/admin.py` — Mirror tab:
   - `ASSIGNED_ANGLES` dict (7 giá trị) — dịch khớp bản FE (xem Decisions).
   - `message` dựng động trong `get_tenant_mirror()` (2 nhánh: có/không ước tính được
     runway).
5. `tests/unit/test_aa309_tenant_onboarding.py` — 1 assertion sửa theo giá trị mới
   (`"Ẩm thực & Con người"` → `"Culinary & people"`).
6. `tests/unit/test_aa240_field_failures.py` — 1 assertion sửa theo giá trị mới (kiểm tra
   substring `"cần"` → `"need"` trong `HIGHLIGHTS_TOO_FEW` reason).

**Không đổi:** `api/migrations/098_acp_shared_tenant_atom_state.sql:13` có 1 dòng comment
SQL liệt kê nhãn tiếng Việt cũ (chỉ để tham khảo lịch sử, không phải code chạy) — migration
đã apply, không sửa migration cũ theo convention repo. Toàn bộ comment/docstring tiếng Việt
khác trong 2 file `.py` và các file `.tsx` khác (không nằm trong 6 file Changed ở trên) giữ
nguyên — đúng scope issue ("comment code vẫn được phép giữ tiếng Việt").

## Tradeoffs

Không có — thay đổi string thuần, không đổi field name/response shape/logic (xác nhận qua
test + tsc + flake8, xem Verify).

## Should know

- Có 2 test bị breaking bởi chính thay đổi này (assertion cũ check literal tiếng Việt) —
  đã sửa cùng lúc, không tách PR riêng, vì chúng chỉ là hệ quả trực tiếp của việc dịch
  string, không phải thay đổi hành vi.
- 2 file FE (`master-content/page.tsx`, `curation/page.tsx`) có sẵn ESLint findings từ
  trước (set-state-in-effect, no-explicit-any, unused vars) — xác nhận qua line number
  không trùng bất kỳ dòng nào trong 5 chỗ tôi sửa, pre-existing, không phải do thay đổi
  này (xem Verify).

## Verify

### Grep tiếng Việt — TRƯỚC khi sửa (từ STEP0 audit, phiên trước)
5 dòng UI FE (`master-content/page.tsx` x3, `curation/page.tsx` x2) + 3 message backend
(`admin_pipeline.py` ingest-s3 dry-run) — xem đầy đủ trong
`docs/claude_audit/i18n-tenant-layout-audit.md` phần 1.2/1.3.

### Grep tiếng Việt — SAU khi sửa (quét lại đúng phạm vi issue yêu cầu:
`frontend/{app,lib,components}` + `api/routers/admin_pipeline.py` + `api/routers/admin.py`,
regex ký tự có dấu à-ỹ/đ/Đ)

```
TOTAL HITS: 62 | NON-COMMENT (kiểm tra thủ công): 9
```

Toàn bộ 62 dòng còn khớp regex là comment (`//`, `{/* */}`, `#`, docstring `"""`) — đã
kiểm tra thủ công từng dòng trong 9 dòng "non-comment" heuristic không nhận diện được
(continuation line của comment nhiều dòng, hoặc trailing `//` sau code) — xác nhận **0
dòng UI/message thật còn tiếng Việt** trong phạm vi quét. Chi tiết 9 dòng đã kiểm (đều là
comment/docstring, không phải regression):
- `frontend/app/layout.tsx:33` — dòng đóng `{/* ... */}` (comment JSX nhiều dòng)
- `frontend/app/admin/quarter-plan/page.tsx:471` — continuation `{/* ... */}`
- `frontend/app/admin/produce/PieceReviewModal.tsx:265` — trailing `//` sau khai báo type
- `api/routers/admin_pipeline.py:1743,1750` — continuation của docstring nhiều dòng
- `api/routers/admin_pipeline.py:2296-2298` — docstring `"""..."""` 3 dòng
- `api/routers/admin.py:1035` — continuation của docstring

### Kỹ thuật
- `npx tsc --noEmit -p tsconfig.json` (frontend) — **0 lỗi** (đã `rm -rf .next` trước khi
  chạy — cache cũ từ phiên AA-427 khác gây lỗi giả `Cannot find module` không liên quan).
- `.venv/bin/python -m flake8 api/routers/admin.py api/routers/admin_pipeline.py` — **0 lỗi**.
- `npx eslint app/admin/master-content/page.tsx app/admin/curation/page.tsx` — 8 lỗi + 8
  warning, xác nhận **toàn bộ pre-existing** (line number không trùng 5 dòng đã sửa:
  562/791 curation, 629/633/636 master-content).
- `.venv/bin/python -m pytest tests/unit -q` — **1347 passed**, 0 fail (bao gồm 2 test đã
  cập nhật assertion theo string mới, và toàn bộ suite còn lại không bị ảnh hưởng).
- Cấu trúc JSON response `POST /admin/pipeline/ingest-s3` (dry_run) và `GET /admin/tenants/
  {id}/mirror` — không đổi field name, chỉ đổi giá trị string (xác nhận qua đọc diff +
  test pass).
- Không chạy qua UI thật (ECS/RDS không khởi động trong phiên này — không cần thiết vì
  đây là thay đổi string thuần, đã verify đủ qua test + tsc + flake8 + grep).
