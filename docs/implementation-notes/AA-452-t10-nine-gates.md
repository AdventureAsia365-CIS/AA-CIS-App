# AA-452 — T10: extend F1/F2/F6/F8/F9-adjusted to the full F1-F9 gate set (blog-only F3/F5/F7)

Follows the investigation in `docs/claude_audit/AA-452-t10-nine-gates.md` (STEP0-equivalent for
this task — read before this file for the full reasoning behind every decision below).

## Decisions

1. **The task's own premise was corrected after investigation, not built as originally stated.**
   AA-450 already shipped 6 T10 gates, not 5 (`F4_extreme_length` already existed). The real gap
   was 3 missing gates (F3/F5/F7), not 4. Confirmed with Nghiep before writing any gate code.

2. **F3 (structural variance)/F5 (atom density)/F7 (FAQ dedup) are added scoped to
   `channel == 'blog'` only** — Option 3 (Nghiep's choice, over "port unconditionally" or "leave
   removed"): fix `prompts.py`'s blog instructions to actually produce the markdown H2/FAQ
   structure and `[R:atom_id]` citation tags these gates need FIRST, verify the model reliably
   produces both, THEN port the gates. The other 7 channels' prompts and gate stacks are
   byte-for-byte unchanged (verified by test — see `test_aa452_prompts_blog_format.py`'s
   `test_non_blog_channel_gets_no_blog_instructions`).

3. **Citation tags are internal-only, never tenant-visible, for any channel, at any status.**
   `strip_citation_tags()`/`deep_strip_citation_tags()` (`quality_gates.py`) run once in
   `service.write_and_check()`, after the attempt loop, on `content_text` + every
   `gate_ledger`/`repair_log` violation string + `held_reason` — for both `'approved'` and
   `'held'` outcomes. See the audit doc's "tag+strip mechanism" section for why this can't lean
   on any existing N7 precedent (N7 itself never solves this — confirmed by reading
   `acp_produce/packets.py` and grepping the rest of that package/`acp_deliver` for a strip step;
   found none, because T11 publish, N7's own natural place to do this, isn't built yet).

4. **No new DB column for the tagged intermediate text.** Considered a nullable
   `content_text_tagged` debug column on `acp_shared.content_piece` and decided against it — no
   real consumer exists yet (T10's admin review-queue UI is still out of scope, same as AA-450).
   The tagged text is a local variable inside `write_and_check()`, discarded once the final scrub
   runs. Revisit only against a real, evidenced debugging need, not speculatively. No migration
   needed for this task.

5. **`gate_extreme_length` (F4) now measures the tag-stripped text, not raw `content_text`.** A
   citation tag is internal markup, not something a length ceiling meant to bound tenant-facing
   copy should count. No-op change for the 7 non-blog channels (they never have a tag to strip).

6. **All 3 new gates are pure DET (rule-based), confirmed against `acp_produce/gates.py`'s own
   "(DET)" labels before writing any code** — no new LLM call, so no new `asyncio.to_thread()`
   wrapping needed beyond what `service.py` already does for the whole `run_quality_gates()` call.

7. **Retry budget unchanged** — still `MAX_ATTEMPTS = 2` (service.py), not scaled by gate count,
   per the build task's own instruction. Adding 3 more gates to a `blog`-channel attempt does not
   change how many rewrite attempts a request gets.

## Changed

- **`services/acp_content_writing/prompts.py`**: `_BLOG_FORMAT_INSTRUCTIONS` (new module
  constant), appended to `build_user_prompt()`'s output only when
  `channel_style['channel'] == 'blog'`. New keyword-only `atom_id: str | None = None` param
  (default keeps every pre-AA-452 caller/test unaffected) — fills the tag's literal id; falls
  back to the placeholder `"atom"` rather than emitting a malformed `[R:]` tag if omitted.
- **`services/acp_content_writing/generate.py`**: `write_content()`/`rewrite_with_feedback()`
  gain the same `atom_id` passthrough param (default `None`), forwarded to `build_user_prompt()`.
- **`services/acp_content_writing/quality_gates.py`**:
  - New: `TAG_RE`, `ATOM_DENSITY_WORDS`, `strip_citation_tags()`, `deep_strip_citation_tags()`
    (module-level, near the top, since `gate_grounding()` also uses `strip_citation_tags()` in
    its own violation message).
  - New gates: `gate_atom_density()` (F5), `gate_structural_variance()` (F3), `gate_faq_dedup()`
    (F7) — all channel-agnostic functions; channel dispatch lives entirely in
    `run_quality_gates()`, not inside the gate functions themselves (matches how F3/F7 already
    behave in N7 — the gate doesn't know about channel routing, the caller does).
  - `run_quality_gates()`: new required `channel: str` kwarg (no default — every real caller
    always has one; existing tests updated to pass it explicitly, same "explicit over implicit"
    discipline this codebase already applies elsewhere). Appends the 3 new gates between F4 and
    F8 only when `channel == 'blog'`. `gate_extreme_length()` now called on
    `strip_citation_tags(content_text)`, not raw `content_text` (Decision 5).
  - `gate_grounding()`'s violation message now runs the quoted sentence excerpt through
    `strip_citation_tags()` too — defense in depth on top of the final `deep_strip_citation_tags()`
    pass in `service.py`, so this one specific violation shape is never tagged even at the source.
- **`services/acp_content_writing/service.py`**: `write_content`/`rewrite_with_feedback` calls
  now pass `atom_id=req["atom_id"]`; `run_quality_gates` call now passes `channel=req["channel"]`.
  New scrub block after the attempt loop, before `_persist_piece()` (Decision 3).
- **Docs fix (no code)**: corrected the stale "T10 = 5 gates" line in
  `docs/claude_audit/AA-450-02-t10-gate-map.md` and `docs/implementation-notes/
  AA-450-t9-content-writing.md` to the real count (6), with a pointer forward to this task.
- **New tests**: `tests/unit/test_aa452_t10_nine_gates.py` (gate_atom_density/
  gate_structural_variance/gate_faq_dedup direct tests; strip_citation_tags/
  deep_strip_citation_tags tests; run_quality_gates channel-dispatch tests confirming exact gate
  lists for blog vs. non-blog; the tag-leak-prevention tests for `write_and_check()` — see
  "Should know" below), `tests/unit/test_aa452_prompts_blog_format.py` (blog-only instruction
  block). **Updated**: `tests/unit/test_aa450_quality_gates.py`'s 3 direct `run_quality_gates()`
  calls now pass `channel="facebook"` explicitly (signature change, not a behavior change —
  these tests still assert the same 6-gate, non-blog outcomes as before).

## Tradeoffs

- F3/F5/F7 depend on the writer model reliably following the new markdown H2/FAQ/tag
  instructions — unlike F1/F2/F4/F8/F9, which check semantic/structural properties the model was
  always somewhat likely to get right by default, F3/F5/F7's entire signal comes from markup the
  model must be explicitly told to emit. A model that drifts on this instruction (e.g. stops
  emitting `## ` headers under prompt pressure from `revision_feedback` on attempt 2) would fail
  these gates for a reason unrelated to actual content quality. Live-verify below checks this
  directly on real Bedrock output, not assumed from the prompt text alone.
- F9's rubric fields are still N7's real facebook rubric reused verbatim across all 8 channels
  (AA-450's own flagged tradeoff, unchanged by this task) — not revisited here.
- The tag+strip mechanism adds one more moving part to `blog`-channel requests specifically
  (tagged-write → gate-check-with-tags → strip → persist) that the other 7 channels don't have.
  Kept as simple as possible (single strip pass at the very end, no intermediate tagged storage)
  precisely because of this — see Decision 4.

## Should know

- **The most important test in this PR is a regression test on the test itself, not just the
  code.** The first version of `TestWriteAndCheckStripsTagsBeforeOutput`'s two leak tests
  asserted against a hand-typed, static mocked `RETURNING` row — which would have kept passing
  even if the real strip step were silently deleted from `service.py`, since the mock never
  reflected what was actually computed. Caught by running the tests immediately after writing
  the strip logic (they failed, correctly, exposing the mock's own gap) and fixed by making the
  mocked `fetchrow`'s second call echo back the ACTUAL positional args `_persist_piece()` sent —
  simulating what Postgres's own `RETURNING` clause really does. See
  `_echo_insert_as_returning_row()` in the test file.
- No T10 admin review-queue UI, T11 (publish) — same exclusions AA-450 already named, unchanged
  by this task.
- Retry budget (`MAX_ATTEMPTS = 2`), single-endpoint architecture, non-blocking
  `asyncio.to_thread()` pattern — all unchanged, per the build task's explicit instruction not to
  touch them.

## Live Verify

(To be filled in after AWS access is available this session — MFA-gated, pending.)
