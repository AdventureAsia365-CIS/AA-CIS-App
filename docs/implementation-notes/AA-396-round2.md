# AA-396 round 2 — F8 "ends with CTA" split into a deterministic check

Follow-up to `AA-396-round1`'s (docs/implementation-notes/AA-396.md) explicit non-fix
of F8's "ends with CTA" judge reliability, and to the investigation that preceded this
PR (not written up as its own notes file — investigation-only, reported directly in
conversation). That investigation traced the real corpus
(`docs/implementation-notes/AA-391-report-data.json`) and found the failure was NOT a
wiring/truncation bug: the judge (Nova Pro) genuinely received a clean, untruncated
body ending in a real CTA and still scored it 0, while a sibling piece whose CTA link
was followed by more prose scored 1 — the opposite of what a positional bug would
predict. Root cause: genuine LLM judgment inconsistency on a question that doesn't
need semantic judgment at all.

## Decisions

- **Scoped the fix to `hook_story_cta`'s "ends with CTA" only** — AIDA's "single clear
  action (CTA)" and reader_as_hero's "single CTA" stay on the LLM judge. Those ask
  about clarity/singularity of the ask (genuinely semantic, no evidence either is
  unreliable), not literal position in the text. Did not generalize the deterministic
  pattern to every CTA-shaped rubric line — narrow, evidence-based, per the same
  discipline round 1 used for its leak-guard.
- **Anchored the regex on the brand's one canonical CTA phrase ("Design This
  Journey"), not a generic URL/markdown-link pattern.** Checked this against real
  routing (`services/acp_planning/constants.py::FRAMEWORK_TABLE`) before writing the
  regex: `hook_story_cta` is assigned to `("ANY", "facebook")` — blog channels map to
  hub/PAS/AIDA by funnel stage, never hook_story_cta, in real production routing (the
  blog pieces in the AA-391 report data that DID get scored against hook_story_cta are
  synthetic live-verify-script pieces that set `framework="hook_story_cta"` directly,
  bypassing the real Brief-driven routing — `pipeline.py`'s own docstring confirms C3/
  brief-compile doesn't exist in this repo yet). Since facebook is the real target
  channel and `gate_route_to_sellable()`'s own docstring confirms FB/TikTok captions
  "reference the trip conversationally, never embedding a literal URL," a URL-only
  regex would have broken every legitimately-passing social piece. Every real CTA
  instance across the whole corpus — markdown-linked or plain prose — used the literal
  phrase "Design This Journey" (grepped, no variants found), matching
  `services/content_generation/brand_standards.py`'s documented brand constant, so the
  check anchors on that phrase.
- **Checks the final `\n\n`-delimited paragraph, not the literal last characters.**
  Real corpus evidence for both sides: `slot_c5471`'s blog piece (this PR's motivating
  bug) has the CTA link as the literal last content — must pass. `slot_4139`'s blog
  piece (already passing under the old LLM judge, not something to regress) has the
  CTA link followed by a ~30-word coda sentence in the SAME final paragraph — under a
  strict "must be the literal last token" reading this would have flipped to a new
  failure. Chose the more lenient "CTA phrase appears anywhere in the final paragraph"
  reading because it matches both real examples without contradiction, and because a
  closing paragraph that opens with the CTA link and adds one more editorial sentence
  is a normal, legitimate copywriting pattern, not something F8 should start blocking.
- **Did not touch the TikTok fixture/framework question the original investigation
  flagged as puzzling** (a piece with "Design This Journey" buried mid-script,
  followed by an entire separate VISUAL section, passed F8 under the old judge). Once
  `FRAMEWORK_TABLE` was actually read for this PR, that puzzle dissolved on its own:
  TikTok routes to `hook_beats_payoff` (`"hook stated"`, `"timed beats present"`,
  `"payoff lands"`), never `hook_story_cta` — TikTok pieces were never evaluated
  against "ends with CTA" in the first place. No regression risk, nothing to fix.

## Changed

- `services/acp_produce/gates.py`:
  - `FRAMEWORK_RUBRICS["hook_story_cta"]`: dropped `"ends with CTA"`, now
    `["first line is the hook", "one atom, one emotion"]` — the Nova Pro prompt for
    this framework no longer asks about CTA position at all.
  - New `_CTA_PHRASE_RE` / `_ends_with_cta(piece_body)` — deterministic check, see
    Decisions above for exactly what it matches and why.
  - `gate_framework()`: runs `_ends_with_cta()` when `framework == "hook_story_cta"`,
    appending `"framework criterion failed: ends with CTA"` to `violations` before the
    LLM call — same violation string the old LLM path used, so `repair_fn`/
    `held_reason` consumers downstream see no format change, and the fix flows through
    the same `_format_audit_reason()`/repair-context path AA-396 round 1 fixed rather
    than bypassing it (no new plumbing needed — `gate_framework()` doesn't call
    `_format_audit_reason()` at all; that helper is F9-specific, `violations` here goes
    straight to `run_gates()`'s `first_failure.violations` same as before).
  - The judge-unavailable exception path now appends to the existing `violations` list
    (which may already carry the deterministic CTA failure) instead of returning a
    fresh single-item list — so a judge outage no longer silently drops a real
    deterministic failure that was already found.
- Tests (`tests/unit/test_aa298_judge.py`):
  - Updated `test_gate_framework_treats_score_1_without_evidence_as_fail` — was mocking
    a `"ends with CTA"` LLM item under `hook_story_cta`, which the LLM is no longer
    asked about; switched to `"first line is the hook"` and gave the fixture body a
    real trailing CTA phrase so it isn't incidentally also failing the new det check.
  - 6 new tests reconstructing the real corpus scenarios: rubric no longer asks the LLM
    about CTA; piece-4-shaped pass (literal last content); slot_4139-shaped pass (CTA +
    coda sentence, same paragraph); genuine no-CTA fail (facebook hashtag-only body);
    det violation surfaces even when all LLM criteria score 1; det check does not fire
    for AIDA/other frameworks.
- Tests (`tests/unit/test_aa364_pipeline.py`):
  - `test_facebook_piece_routes_f8_to_hook_story_cta_not_blog_hub` and
    `test_facebook_piece_fails_only_f9_then_repair_round_passes` both reused a shared
    facebook fixture body (`"Ride the tuk-tuk..."`) with no CTA phrase at all — this
    used to pass through undetected because F8's Nova Pro response was fully mocked
    (`_passing_framework_response()`, content-independent). With the det check wired
    in, that body would now make F8 genuinely fail, which for the second test would
    have silently triggered a REAL (unmocked) `repair_piece()` Sonnet call instead of
    exercising the F9-only repair path the test is actually about. Added `"Design This
    Journey."` to both the original and repaired bodies in both tests.

## Tradeoffs

- Anchoring on one literal brand phrase means the check will false-negative on any
  future CTA wording that departs from "Design This Journey" (e.g. a tenant-specific
  CTA phrase, if that's ever built). No such mechanism exists yet — `hook_story_cta`
  is currently facebook-only and this repo's only CTA copy is the single hardcoded
  brand constant — so this is a real but currently-inert limitation, not a live gap.
  Revisit if/when tenant-specific CTA wording is built.
- "CTA anywhere in the final paragraph" is more lenient than a strict trailing-token
  check. It would pass a piece where the CTA phrase appears early in a long final
  paragraph with substantial unrelated content after it — not present in the real
  corpus (both real examples have the CTA at or very near the paragraph's start/only
  content), so untested against that shape. Considered adding a max-distance-from-
  paragraph-end bound; didn't, because there's no real example motivating it and it
  would be a guess, not evidence.
- The synthetic blog-with-hook_story_cta pieces in `AA-391-report-data.json` (piece 4
  and slot_4139) are NOT reachable via real production routing today (blog always
  resolves to hub/PAS/AIDA per `_resolve_framework()`). They remain useful as
  regression fixtures (real writer-shaped prose, real bug), but "ends with CTA" is, in
  live traffic as of this PR, exclusively a facebook-channel check. Flagging this so a
  future reader doesn't assume blog pieces exercise this path in production.

## Should know

- This closes the "F8 ends with CTA judge reliability" line item AA-396 round 1 left
  open. F3/F4 threshold calibration and the shared `max_repairs` budget question
  (piece 1's class, `slot_b09166...`) remain open and untouched — out of scope for this
  PR, same as round 1.
- `tests/verify_scripts/aa376_repair_verify.py` (live Bedrock, not collected by
  pytest — no `test_`-prefixed functions) has a facebook scenario A fixture that likely
  has the same no-CTA-phrase gap as the two unit fixtures fixed here. Not updated in
  this PR (it needs real Bedrock/Postgres to even run, out of scope for an automated
  fix) — flagging so whoever next runs it live isn't surprised by a new F8 failure
  where the script's own comments say "F8 pass."
- Verified via direct real-corpus replay (not just the new unit fixtures) that
  `_ends_with_cta()` produces the intended flip: piece 4 (`slot_c5471` blog) goes
  False→True (the bug), `slot_4139` blog stays True (no regression), both facebook
  pieces (`slot_c5471`/`slot_4139`) stay False (genuine failures, correctly still
  caught).
