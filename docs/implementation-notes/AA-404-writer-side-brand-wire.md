# AA-404 writer-side brand rubric wire (E2-E5)

**Supplement to `AA-404.md` / `AA-404-F9-deep-dive.md` / `AA-404-f9-fix1-content-wire.md`, not a
replacement.** This session closes the exact gap the F9 deep-dive's TL;DR #1 identified: F9 fix #1
(PR #158) wired real per-tenant `shared.tenant_brand_rules` content into ONLY the F9 judge
(`gates.py::gate_brand_seo_audit()`/`gate_brand_seo_audit_social()`), while the 4 writer/repair
modules (`generation.py` E2, `adapt.py` E3, `faq.py` E4, `repair.py` E5) kept hardcoding the
generic `AA_BRAND_IDENTITY_PROMPT` constant. Judge and writer were scoring/aiming at two different
targets. No new investigation was done this session — STEP 0 was reading the 2 already-merged
audit docs named in the task, per their own explicit instruction not to re-investigate.

## Decisions

- **New shared leaf module `services/acp_produce/brand.py`**, not a re-export from one of the
  writer modules. `slot_runner.py` already imports `generation.py`/`adapt.py`/`faq.py` directly (it
  is the E1-E5 orchestrator) — if any of those three needed to import `fetch_brand_rubric_text`
  from a sibling module or from `slot_runner.py` itself, that would either invert the orchestrator's
  own import direction or create a cycle. A leaf module with no dependents in this package (only
  `services.content_generation.brand_standards` for the fallback constant) sits below every module
  that needs it — same layering principle F9 fix #1 itself already used to justify NOT importing
  `admin_pipeline.py::_resolve_brand_rule()` directly ("api.routers.\* is a higher layer than
  services.acp_produce.\*").
- **`fetch_brand_rubric_text()` itself is unchanged, only moved** — same query, same fallback,
  same warning log. `slot_runner.py` re-imports it (`from services.acp_produce.brand import
  fetch_brand_rubric_text`) rather than reimplementing, so every existing
  `@patch("services.acp_produce.slot_runner.fetch_brand_rubric_text", ...)` test call site and
  `from services.acp_produce.slot_runner import fetch_brand_rubric_text` import keeps working
  unchanged — verified by running the pre-existing test suite before writing any new test.
- **Fetched once per slot, BEFORE E2** (moved earlier than F9 fix #1's original fetch point, which
  was right before the F9 gate loop) — now the single value threads through E2 → E3 → E4 → (F1-F9,
  including E5 repair via `PieceInvariants`), never refetched. Same "1 DB query per slot, not per
  piece/module" property F9 fix #1 established, extended to cover 4 more call sites instead of 1.
- **E5 (repair.py) reuses the existing `PieceInvariants` mechanism** (PR #154) — added
  `brand_rubric_text: str = AA_BRAND_IDENTITY_PROMPT` as one more field, rather than adding a
  second, disconnected parameter to `repair_piece()`. Matches the task's own explicit instruction
  and the class of piece-wide state `PieceInvariants` already exists to carry through every repair
  round regardless of which gate triggered it.
- **Every writer function's system prompt is now built per-call** (`_build_draft_system_prompt()`,
  `_build_adapt_system_prompt_base()`, `_build_faq_system_prompt()`,
  `_build_repair_system_prompt()`) instead of a module-level constant computed once at import time
  from `AA_BRAND_IDENTITY_PROMPT`. This was the actual mechanical reason the old constants existed
  — `AA_BRAND_IDENTITY_PROMPT` never changes at runtime, but `brand_rubric_text` now varies per
  tenant/call, so it can no longer be baked in at module-import time.
- **`brand_rubric_text` is a plain parameter with `AA_BRAND_IDENTITY_PROMPT` as its default** on
  `generate_draft()`, `adapt_channels()`, `answer_faq()`, `apply_faq()` — not a required argument.
  All fallback logic (empty/missing tenant row → generic constant, logged as a warning) already
  lives entirely in `fetch_brand_rubric_text()` (unchanged from F9 fix #1); by the time a `str`
  reaches these functions it's already resolved. The parameter default exists so every pre-AA-404
  caller/test that doesn't pass one reproduces the exact old behavior, not as a second fallback
  path.

## Changed

- `services/acp_produce/brand.py` — new. `fetch_brand_rubric_text()` moved here from
  `slot_runner.py`, byte-identical logic.
- `services/acp_produce/slot_runner.py` — imports `fetch_brand_rubric_text` from `brand.py`
  instead of defining it; fetch moved to before E2; `generate_draft()`/`adapt_channels()`/
  `apply_faq()` calls now pass `brand_rubric_text`.
- `services/acp_produce/generation.py` — `generate_draft()` takes `brand_rubric_text` (default
  `AA_BRAND_IDENTITY_PROMPT`); `_DRAFT_SYSTEM_PROMPT` (module constant) replaced by
  `_build_draft_system_prompt(brand_rubric_text)`; `_invoke_sonnet_with_retry()` takes `system` as
  a parameter instead of closing over the old constant.
- `services/acp_produce/adapt.py` — `adapt_channels()` takes `brand_rubric_text` (same default),
  threaded to both channel calls; `_ADAPT_SYSTEM_PROMPT_BASE` → `_build_adapt_system_prompt_base()`.
- `services/acp_produce/faq.py` — `answer_faq()`/`apply_faq()` take `brand_rubric_text`;
  `_FAQ_SYSTEM_PROMPT` → `_build_faq_system_prompt()`.
- `services/acp_produce/repair.py` — `PieceInvariants` gained `brand_rubric_text` field (default
  `AA_BRAND_IDENTITY_PROMPT`); `_REPAIR_SYSTEM_PROMPT` → `_build_repair_system_prompt()`;
  `repair_piece()` resolves the value from `invariants.brand_rubric_text` (or the default when
  `invariants is None`, same as every other `PieceInvariants` field).
- `services/acp_produce/pipeline.py` — `_build_repair_invariants()` takes `brand_rubric_text` and
  sets it on the returned `PieceInvariants`; its one call site passes the same `brand_rubric_text`
  already threaded to F9's `_f9` closure.
- `services/acp_produce/gates.py` — docstring pointer updated (`slot_runner.py::
  fetch_brand_rubric_text()` → `brand.py::fetch_brand_rubric_text()`), no behavior change.
- Tests: `test_aa370_generation.py` (+3), `test_aa371_adapt_faq.py` (+5),
  `test_aa376_repair.py` (+3), `test_aa364_pipeline.py` (+1 assertion on an existing test),
  `test_aa404_repair_invariants.py` (updated 7 existing calls for the new 4th positional param +
  1 new assertion), `test_aa375_slot_runner.py` (updated 4 existing tests whose mocked
  side_effect/patch signatures didn't yet account for the new parameter/call-order), new
  `test_aa404_brand_module.py` (3 tests: module importable standalone, `slot_runner`'s re-export is
  the same function object not a drifting copy, no import cycle from any writer module).

## Tradeoffs

- **No live-DB or live-Bedrock verification** — same limitation every AA-404 session so far has
  carried (`AA-404.md`'s own "Should know" section already flags this pattern). All tests mock
  `invoke_claude`/`db.fetchrow`. The real test is a post-merge N7 run, same as PR #153/#154/#158's
  own follow-up pattern.
- **`test_aa404_repair_invariants.py`'s 7 existing test calls to `_build_repair_invariants()` were
  edited to add a 4th positional argument** rather than giving that internal helper a default value
  for `brand_rubric_text`. `_build_repair_invariants()` has exactly one real caller
  (`pipeline.py`'s own `run_piece_through_produce_gates()`) and no reason to ever run without a
  real rubric string, so treating the parameter as required (and updating the tests explicitly)
  seemed more honest than giving an internal-only helper a silent default that production code
  never actually uses.
- **The public writer functions (`generate_draft`/`adapt_channels`/`answer_faq`/`apply_faq`) DO get
  a default**, unlike the internal pipeline helper above — these have test-only callers today, but
  are the more likely surface for a future non-`slot_runner.py` caller (e.g. a verify script), and
  matching `repair_piece()`'s existing `invariants: Optional[...] = None` backward-compatible
  convention seemed like the safer default for functions further from the one real call site.

## Should know

- This closes the F9 deep-dive's #1-ranked, highest-confidence recommendation. It does NOT touch
  recommendations #2-5 (atom-density validator, TikTok rubric redesign, `_GENERIC_AI_WORDING_
  ANCHOR` expansion, repair-strategy change for F3/F9) — those remain open, undecided, per the
  deep-dive's own explicit "not proposing to merge/code any of these now" stance.
- Real-world effect is unverified until the next N7 run. The F9 deep-dive's own root-cause
  reasoning (writer/judge target mismatch) is the basis for expecting this to help blog pass rates,
  but F9's `GENERIC_AI_WORDING`/`SUMMARY_OFF_BRAND` codes are still fundamentally a subjective LLM
  judgment with no deterministic anchor — this fix closes a real, confirmed gap, not a guarantee of
  convergence to 0 held pieces.
