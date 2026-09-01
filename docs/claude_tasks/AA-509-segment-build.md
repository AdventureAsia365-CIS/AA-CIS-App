[Ghi chú phục dựng: bản chat gốc gửi phiên Claude Code trước đã mất theo `/clear`, không nằm
trong context phiên ghi file này. Nội dung dưới đây ghép từ 2 nguồn Linear thật (qua MCP
`get_issue`/`list_comments`): (1) issue description gốc, (2) comment "chốt thiết kế" của Nghiệp
lúc 01/09 05:05:41 UTC — đúng thời điểm "sẵn sàng build" theo lời chính comment đó. Không đảm bảo
khớp 100% byte cho byte với prompt đã gõ vào chat, nhưng là nội dung thật của quyết định đã chốt,
không suy diễn.]

---

# [Segment] Lớp mới — group atom cùng moment thật, schema + thuật toán matching — issue description gốc

## Bối cảnh

Sub-issue của AA-507. Segment gom các atom mô tả cùng 1 địa điểm/hoạt động thật qua nhiều tour của
cùng tenant (KHÔNG merge nội dung — atom tả khác giọng vẫn là atom riêng, chỉ chung 1 Segment).
Đây là nền cho T6 (curation theo nhóm), Route (T7 Blog), Atom Score, Slate.

## Schema (migration, số hiệu thật do Claude Code STEP0 xác nhận — tạm đề xuất 127)

```sql
CREATE TABLE acp_contract.atom_segment (
  segment_id       text PRIMARY KEY,
  tenant_id        uuid NOT NULL REFERENCES shared.tenants(tenant_id),
  canonical_place  text NOT NULL,
  canonical_action text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE acp_contract.atom_segment_member (
  segment_id  text NOT NULL REFERENCES acp_contract.atom_segment(segment_id),
  atom_id     text NOT NULL REFERENCES acp_contract.tour_atoms(atom_id),
  is_alias    boolean NOT NULL DEFAULT false,
  PRIMARY KEY (segment_id, atom_id)
);
```

⚠️ `tour_atoms.owner_scope` là text tự do (không phải `tenant_id` UUID sạch) — kiểm tra kiểu dữ
liệu khớp khi JOIN trước khi viết migration thật.

## Thuật toán tham chiếu (port gần nguyên văn — pure function, không I/O)

`src/aa_social/matching.py` trong repo Ms. Thư — token similarity trên `place` + khớp động từ
trên `action`. `segment_id` phải derive từ danh tính atom thành viên lúc Segment lần đầu xuất
hiện (không theo thứ tự tới), đọc `docs/adr/0002-vector-store-scoped-to-search-matching.md` để
hiểu lý do (grouping deterministic, embedding chỉ dùng cho matching search-demand, không dùng để
group).

## Việc cần làm

1. Viết `services/acp_contract/segment_matching.py`, chạy tự động ngay sau T5 hoàn tất (mỗi lần
   atomize xong 1 tour version).
2. Migration bảng trên.
3. T6 UI (`t6-atoms/page.tsx`) thêm group-by-Segment (header expand/collapse), giữ nguyên hành vi
   chọn HIGH/MED/LOW theo atom.

## Tham chiếu

ADR-2026-040. Epic: AA-507. Blocked by AA-508 (cần atom_id ổn định trước).

---

## Thiết kế cuối AA-509 — chốt sau STEP0 (comment Linear, 01/09 05:05:41 UTC, Nghiệp)

**Thiết kế cuối AA-509 — chốt sau STEP0 đối chiếu schema thật + repo Ms. Thư. Sẵn sàng build.**

**STEP0** (`AA-509-step0-schema-matching-investigation.md`) xác nhận mô tả gốc issue lỗi thời ở 2
điểm (do AA-508 vừa đổi schema): `tour_atoms` không có `place`/`action` tách riêng (chỉ `text`
gộp + `activity_type` enum 7 giá trị); `owner_scope` là chuỗi `tenant_id` thật dạng text với atom
T5 (không phải rác), literal `'platform'` với atom platform-level.

**3 quyết định đã chốt với Nghiệp (01/09):**

1. **Hướng A** — thêm `place`/`action` tách riêng vào T5 decompose, port đúng nguyên văn thiết kế
   Ms. Thư thay vì suy yếu thuật toán theo `text`+`activity_type` hiện có. **Chấp nhận hệ quả: đổi
   `SYSTEM_PROMPT` của T5 → invalidate toàn bộ `fingerprint_hash` đã lưu từ AA-508 (deploy cùng
   ngày) → cần re-atomize lại atom hiện có.** Quyết định có chủ đích: đúng thiết kế gốc ngay từ
   đầu, tránh nợ kỹ thuật kép (build B trước rồi vẫn phải đổi sang A sau).

2. **`is_alias`** — bỏ khỏi `atom_segment_member` (sai chỗ, alias là khái niệm cấp segment không
   phải cấp atom). Thêm bảng riêng:
   ```sql
   CREATE TABLE acp_contract.atom_segment_alias (
     segment_id_old        text PRIMARY KEY REFERENCES acp_contract.atom_segment(segment_id),
     segment_id_canonical  text NOT NULL REFERENCES acp_contract.atom_segment(segment_id),
     merged_at             timestamptz NOT NULL DEFAULT now()
   );
   ```

3. **Migration 129** (không phải 127 như tạm ghi ban đầu) + JOIN:
   `tour_atoms.owner_scope = shared.tenants.tenant_id::text` (so sánh dạng text 2 chiều, không ép
   `::uuid` lên cả cột `owner_scope` vì có literal `'platform'` không parse được). Atom
   `owner_scope='platform'` **loại trừ hoàn toàn khỏi Segment** — không thuộc về 1 tenant cụ thể.

**Scope build (thứ tự phụ thuộc):**
1. Đổi T5 decompose: thêm `place`/`action` vào output LLM (đổi `SYSTEM_PROMPT`,
   `atom_extraction.py`), đổi `atom_id` hash input theo đúng công thức gốc Ms. Thư (`place`+
   `action` riêng thay vì `text` gộp — quay lại literal spec ban đầu, không còn cần workaround
   `text` gộp nữa).
2. Xử lý invalidation: fingerprint cũ (từ AA-508) không còn khớp SYSTEM_PROMPT mới → tự động
   re-atomize khi gọi lại (đúng cơ chế fingerprint-skip đã có, không cần code riêng để "xoá" —
   chỉ cần fingerprint mới không khớp cache cũ là tự trigger gọi lại LLM).
3. Migration 129: `atom_segment`, `atom_segment_member` (bỏ `is_alias`), `atom_segment_alias`.
4. `services/acp_contract/segment_matching.py` — port `matching.py`/`segments.py` gần nguyên văn
   (Jaccard trên place + verb-match trên action qua bảng đồng nghĩa hẹp), chạy tự động ngay sau T5
   hoàn tất.
5. `segment_id` derive từ member identity lúc lần đầu xuất hiện, giữ nguyên qua các lần chạy sau —
   đúng ADR 0002 (deterministic, không dùng embedding để group).
6. T6 UI (`t6-atoms/page.tsx`): group-by-Segment, giữ nguyên hành vi chọn HIGH/MED/LOW theo atom.

**Known trade-off đã ghi nhận, chưa cần giải quyết ở bước này:** `derive_segments()` gốc là O(n²)
trên toàn bộ atom của tenant (không chỉ atom tour vừa atomize) — nếu trigger "chạy ngay sau mỗi
T5" recompute toàn tenant mỗi lần, cost tăng theo quy mô dữ liệu. Theo dõi khi tenant có nhiều
tour, chưa optimize trước.

**Không đổi:** ADR 0002 (grouping deterministic, không embedding) — giữ nguyên như thiết kế gốc.
