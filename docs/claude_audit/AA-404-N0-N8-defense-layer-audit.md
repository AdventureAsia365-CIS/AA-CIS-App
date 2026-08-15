> **Nguồn gốc:** viết bởi Claude Code, phiên 15-16/08/2026, task "F9 deep-dive audit mở rộng
> N0-N8" [AA-404]. Báo cáo gốc dẫn tới audit này:
> [`docs/implementation-notes/AA-404-F9-deep-dive.md`](../implementation-notes/AA-404-F9-deep-dive.md).

# N0-N8 Defense-Layer Completeness Audit [AA-404 follow-up]

**Phạm vi: đọc-only, đối chiếu implementation thật vs `aa-marketing-v2/CONTEXT.md` §1
(system-wide laws) + `aamc/*.py`. Ưu tiên ĐỘ RỘNG — quét hết module, không đào sâu từng cái
như F9 deep-dive. Không tự sửa code.**

## Kết luận tổng quan trước

**Đây LÀ pattern hệ thống lặp lại, không phải F9 xui riêng.** Tìm thấy ít nhất **4 cặp
writer/judge lệch chuẩn khác** (không chỉ F9), và cơ chế kiến trúc gốc lẽ ra ngăn được việc
này (`build_context()` một điểm assembly duy nhất, §1.4) **hoàn toàn không tồn tại** trong bản
port — mỗi module tự quyết định nội dung brand/rubric riêng, không có single source of truth
nào ép buộc đồng bộ. F9 là ca NẶNG NHẤT quan sát được (100% block rate, có số liệu thật) nhưng
cùng một lớp lỗi kiến trúc đang âm ỉ ở framework judge (F8) và ít nhất 1 chỗ atom-assignment
enforcement khác.

---

## Câu hỏi 1 — Writer vs Judge lệch chuẩn

| Cặp | Nguồn writer thấy | Nguồn judge/gate thấy | Lệch? | Bằng chứng |
|---|---|---|---|---|
| **E2/E3/E4/E5 (viết) vs F9 (chấm)** | `AA_BRAND_IDENTITY_PROMPT` hardcode, generic | `shared.tenant_brand_rules` thật (từ PR #158) | **CÓ — nặng nhất, đã có số liệu** | `generation.py:131`, `adapt.py:64`, `faq.py:62`, `repair.py:61` đều `+ AA_BRAND_IDENTITY_PROMPT.strip() +`; `gates.py` qua `slot_runner.py::fetch_brand_rubric_text()` |
| **E1/E2 (viết theo framework) vs F8 (chấm framework)** | Bare label `"FRAMEWORK: {brief.framework}"` — KHÔNG giải thích framework yêu cầu gì, cho `hub`/`PAS` | `FRAMEWORK_RUBRICS` đầy đủ, nhiều tiêu chí LLM cụ thể/framework | **CÓ — đã biết từ AA-404, CHƯA fix cho hub/PAS** | `generation.py:94-127` (`_AIDA_FRAMEWORK_GUIDANCE` chỉ có cho AIDA — docstring tự nói: *"hub/PAS have the same bare-label gap but no real failure yet — deliberately not touched here"*); `gates.py:315-326` `FRAMEWORK_RUBRICS` |
| **E3 tiktok (viết) vs F8 hook_beats_payoff (chấm)** | `_TIKTOK_INSTRUCTIONS` chỉ yêu cầu dòng `"HOOK:"` ≤15 từ, KHÔNG nói gì về "timed beats"/"payoff lands" | F8 chấm cả 2 tiêu chí "timed beats present"/"payoff lands" | **CÓ — đã biết, chưa fix (chưa có failure thật nên bị hoãn)** | `adapt.py:86-93` (đã trích trong AA-404.md STEP 0 §4) |
| **E1 outline (atom-per-section) vs E2 draft (atom thực dùng)** | E2 prompt liệt kê ĐÚNG atom được gán cho section đó (`s.atom_ids`) | F1_grounding kiểm `valid_ids` = TOÀN BỘ `atom_text_by_id` của cả piece, không phân biệt atom "đúng section" hay "sai section" | **NHẸ — writer được hướng dẫn đúng, nhưng KHÔNG có gate nào enforce "chỉ dùng atom đã gán cho section này"** | `generation.py:316-341` (`_build_batch_prompt` chỉ list `s.atom_ids`); `gates.py:70-99` (`gate_grounding` dùng `valid_ids: set[str]` toàn cục, không theo section) |
| **E1 outline vs F4 brief_compliance** | Cả 2 đọc CHUNG 1 object `Brief` (keyword, required_h2s, word_range, internal_links) | Cùng — không tạo rubric riêng | **KHÔNG lệch — case sạch, đối chứng tốt** | `generation.py` E1 deterministic từ `Brief`; `gates.py:201-235` `gate_brief_compliance` đọc thẳng `brief.*`, không có bản sao |

**Nhận xét:** case sạch (E1/F4) cho thấy khi 2 bên CÙNG đọc 1 object nguồn (`Brief`), không có
lệch chuẩn nào xảy ra — chứng minh nguyên nhân gốc đúng là thiếu 1 điểm assembly chung
(`build_context()`, §1.4), không phải "LLM vốn không đáng tin". Bất cứ chỗ nào 2 module tự
quyết định nội dung rubric riêng (thay vì đọc chung 1 nguồn), lệch chuẩn xuất hiện.

---

## Câu hỏi 2 — 6 tầng Anti-AI-voice stack (CONTEXT.md §1.6)

| # | Tầng gốc | Trạng thái | Bằng chứng |
|---|---|---|---|
| 1 | Atom density validator (deterministic, mỗi 200-300 từ phải cite ≥1 atom) | **KHÔNG có** | `gates.py:9-13` tự xác nhận: *"Atom density (the aamc prototype's original F2) is not part of this repo's gate set — AA-372 does not ask for it, and it is not built here."* Không có gate F-số nào làm việc này. |
| 2 | Banned-pattern lexicon (deterministic, global + tenant-extend) | **CÓ, nhưng thiếu phần "tenant-extend"** | `gates.py:104-128` (F2, `BANNED_PATTERNS_SEED`) — global-only, comment tự nói: *"No tenant-extension mechanism here — that needs the brand-rubric-compiler subsystem... AA-327 (Backlog)"* |
| 3 | Structural variance rules (≥1 câu-đơn-đoạn, 1 section dài hơn, ≤1 list) | **CÓ** | F3 (`gate_structural_variance`) + `research.py::_VARIANCE_DIRECTIVES` + `generation.py`'s rhythm/length notes (AA-404 fix) |
| 4 | Brand rejects / audit rubric | **CÓ, nhưng QUÁ TẢI** — đang gánh việc của tầng 1+5 | F9 — xem F9 deep-dive report, `docs/implementation-notes/AA-404-F9-deep-dive.md` |
| 5 | Human seam (chèn 1 câu thật/guest quote mỗi bài) | **KHÔNG có — chỉ còn cột DB rỗng** | `human_seam_notes` là cột schema (migration 079) nhưng `api/routers/v1_atoms.py:248-252` tự xác nhận: *"human_seam_notes... deliberately absent from this INSERT... stay at their migration-079 defaults"* — không có cơ chế nào ghi/dùng cột này trong N7. |
| 6 | Regression signal (AI-detector trend, chỉ log không phải gate) | **KHÔNG có** | 0 kết quả tìm `ai_detector`/`detector_score` trong toàn repo `services/`/`api/` |

**4/6 tầng thiếu hoặc thiếu 1 phần** (#1 thiếu hoàn toàn, #2 thiếu phần tenant-extend, #5 thiếu
hoàn toàn, #6 thiếu hoàn toàn). Chỉ #3 là đầy đủ đúng tinh thần gốc. #4 (F9) tồn tại nhưng đang
è cổ gánh cả phần việc của #1 và #5.

---

## Câu hỏi 3 — Determinism boundary (CONTEXT.md §1.5)

Spec gốc: *"Deterministic (pure Python, never LLM): runway math, lead-time offsets, slot
allocation, funnel-mix validation, budgets/caps, grounding checks, banned-pattern scans, atom
cooldowns, schema emission (FAQ JSON-LD), date math, metric roll-ups, confidence gates."*

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| Runway math | **Deterministic, đúng** | `runway.py::compute_runway_map()` — bảng tra cứu thuần Python |
| Lead-time offsets | **Deterministic, đúng** | Cùng file, offset math thuần |
| Slot allocation | **Deterministic, đúng** | `allocator.py::compute_slot_grid()`/`allocate_month()` — 0 LLM call |
| Funnel-mix validation | **Deterministic, đúng** | `constants.py::SLOT_MIX = {"evergreen": 0.65, "campaign": 0.25, "reactive_held_empty": 0.10}` — khớp CHÍNH XÁC tỷ lệ spec gốc (§3: "~65%/~25%/~10%") |
| Budgets/caps | **Deterministic, đúng** | `gates.py::compute_repair_budget()` — thuần math |
| Grounding checks | **Deterministic, đúng** | F1 — regex + set, 0 LLM |
| Banned-pattern scans | **Deterministic, đúng** | F2 — regex thuần |
| Atom cooldowns | **Deterministic, đúng** | `allocator.py::_eligible_atoms()` — so sánh `cooldown_until` thuần |
| Schema emission (FAQ JSON-LD) | **Deterministic, đúng** | `faq.py:24` tự xác nhận: *"JSON-LD is 100% deterministic code (build_faq_jsonld()) — no LLM"* |
| Date math | **Deterministic, đúng** (không tìm thấy vi phạm) | Rải rác, dùng `datetime`/`date` thuần khắp `allocator.py`/`runway.py` |
| Metric roll-ups | **KHÔNG XÂY, không phải vi phạm** | 0 kết quả `usage_log`/atom weight rollup trong `allocator.py` — module H (learning) chưa được build cho N7, không phải trường hợp "âm thầm đổi sang LLM" mà là "chưa tồn tại" |
| Confidence gates | **KHÔNG XÂY, không phải vi phạm** | Cùng lý do — atom weight sau ≥3 post / quarter-aggregate destination share shift không có trong `services/acp_planning/*` |

**Kết luận Q3: KHÔNG tìm thấy vi phạm §1.5 invariant #4 ("no number from prose") ở bất kỳ hạng
mục nào đã XÂY.** Mọi thứ được build đều build đúng deterministic. 2 hạng mục cuối (metric
roll-ups, confidence gates) đơn giản là chưa được build — khớp với module H (learning) chưa
scope cho N7, không phải một dạng lệch chuẩn writer/judge.

---

## Xếp hạng mức độ nghiêm trọng

| # | Hạng mục | Mức độ | Lý do |
|---|---|---|---|
| 1 | **E2/E3/E4/E5 vs F9 brand rubric lệch** | 🔴 NGHIÊM TRỌNG NHẤT | Đã có số liệu thật: F9 block 100% (65/65), repair success chỉ 2.5%. Đã confirm trong F9 deep-dive. |
| 2 | **Atom density validator không tồn tại** | 🔴 NGHIÊM TRỌNG | Trực tiếp lý giải code `BODY_EXPERIENCE_DETAILS_TOO_GENERIC` (22 lần, #1 code riêng blog) — 1 gate deterministic rẻ tiền lẽ ra bắt được trước khi tốn Bedrock call cho F9. |
| 3 | **Human seam không tồn tại** | 🟡 TRUNG BÌNH | Spec gốc coi đây là "1 câu thật de-AI cả bài" — thiếu hẳn 1 cơ chế chống-generic quan trọng, nhưng chưa có số liệu định lượng hậu quả trực tiếp (khác #1/#2 đã có). |
| 4 | **hub/PAS framework bare-label gap (F8)** | 🟡 TRUNG BÌNH | CÙNG PATTERN với F9 hệt (judge có rubric chi tiết, writer chỉ có label trơn) — nhưng đã biết trước, cố tình hoãn vì "chưa có failure thật" (real data hiện: F8 repair success chỉ 14.6%, thấp thứ 3 sau F3/F9 — đáng để xem lại quyết định hoãn này). |
| 5 | **TikTok hook_beats_payoff gap (F8/E3)** | 🟢 THẤP-TRUNG | Biết trước, chưa có failure thật trong 69 piece quan sát (TikTok F8 chưa từng fail — chỉ F9 fail). Rủi ro tiềm ẩn, chưa phải vấn đề đang xảy ra. |
| 6 | **Atom-per-section không được F1 enforce** | 🟢 THẤP | Writer được hướng dẫn đúng, chỉ thiếu 1 lớp double-check — chưa có bằng chứng writer thực sự vi phạm trong data thật. |
| 7 | **Banned-pattern lexicon thiếu tenant-extend** | 🟢 THẤP | Đã biết, đã có Backlog issue (AA-327) từ trước, không phải phát hiện mới. |
| 8 | **Regression signal / metric roll-ups / confidence gates** | ⚪ KHÔNG PHẢI BUG | Chưa build, đúng scope hiện tại (module H = learning, ngoài phạm vi N7 produce) — không phải lệch chuẩn, chỉ là roadmap item. |

---

## Đề xuất Linear issue (KHÔNG tự tạo — Nghiệp/Claude Chat quyết)

1. **Wire brand rubric thật vào E2/E3/E4/E5** (nối tiếp F9 fix #1) — cùng mức ưu tiên với F9
   deep-dive's đề xuất #1, thực chất là 1 issue.
2. **Build atom density validator** — F-số mới hoặc pre-check của F9, deterministic. Trùng với
   F9 deep-dive's đề xuất #2.
3. **Xây human seam mechanism** (nếu Nghiệp muốn theo đúng spec gốc) — cần thiết kế: lấy câu
   thật từ đâu (guest review? agency input?), atom annotation nào lưu, N7 pipeline đọc thế nào.
   Việc lớn hơn 1-2, cần thiết kế riêng.
4. **Review lại quyết định hoãn hub/PAS framework guidance** — với dữ liệu F8 repair success
   14.6% (thấp) đã có, có thể không còn "chưa có failure thật" như lúc quyết định hoãn ban đầu.
5. **(Backlog, đã biết) AA-327** — banned-pattern tenant-extend, không phải phát hiện mới.

Không đề xuất build metric roll-ups/confidence gates/regression signal ngay — đây là module H
(learning) nguyên chưa nằm trong scope N7 hiện tại, việc lớn, nên là quyết định roadmap riêng
chứ không phải "fix 1 gap".
