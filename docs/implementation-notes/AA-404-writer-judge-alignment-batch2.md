# AA-404 — writer/judge alignment batch 2 (N0-N8 audit Q1 items #2/#3/#4)

Separate file from `AA-404.md` (main file has an in-progress uncommitted section from a
concurrent session — same reason PR #159/#160/#162 didn't touch it either).

## Context

`docs/claude_audit/AA-404-N0-N8-defense-layer-audit.md`'s Q1 table found 4 writer/judge
divergence pairs beyond F9 (already fixed by PR #161). This PR closes the 3 remaining ones
it flagged as real gaps (not the 4th, atom-per-section-vs-F1, listed there too but scoped
differently than the audit worded it — see mục 6 below):

- **hub/PAS bare-label vs FRAMEWORK_RUBRICS** (audit severity: 🟡 medium — "F8 repair success
  only 14.6%, worth revisiting the original deferral")
- **TikTok hook_beats_payoff gap** (audit severity: 🟢 low-medium — "no real failure yet")
- **Atom-per-section not enforced by F1** (audit severity: 🟢 low — "writer already guided
  correctly, only missing a double-check")

## Mục 4 — hub/PAS framework guidance

### Decisions
- **Revisits, doesn't override, the original deferral.** The AIDA fix's own comment
  (`generation.py`, pre-existing) said hub/PAS were deliberately left alone: *"no real failure
  yet — deliberately not touched here, flagged as a follow-up... same Mistake-to-Rule stance
  ADR-2026-009 already established for F9-social."* That reasoning is preserved verbatim in
  the updated comment — this PR adds why it's being revisited now (F8's 14.6% overall repair
  success rate, third-worst of every gate, same class of whole-piece/multi-criterion gate as
  F3/F9) rather than deleting the record of the original call.
- **Honest data gap flagged, not hidden**: an exact hub/PAS-only repair-success rate isn't
  available (framework mix isn't logged per repair round) — the PR explains this rather than
  fabricating a number.
- **Hub gets ONE general per-batch guidance line, no positional per-section notes** — its F8
  rubric ("comprehensive coverage" + "each section a distinct sub-question") is a
  whole-piece/every-section property, not positional, unlike AIDA's 4-beat arc. A per-section
  note here would have no natural "which section" to pin to.
- **PAS gets the SAME shape as AIDA** — general guidance + opening-problem/closing-resolve
  notes pinned to the outline's actual first/last section — because PAS's rubric
  ("opens with the reader's problem" / "resolves with the trip as solve") IS positional, same
  class of gap as AIDA's, same fix shape.
- **`_FRAMEWORK_GUIDANCE` dict replaces the single `if framework == "AIDA"` branch** — same
  pattern `_CHANNEL_INSTRUCTIONS`/`_SOCIAL_RUBRIC_FIELDS` already use elsewhere in this
  package for a framework/channel → content lookup, not a new convention.

### Changed
- `services/acp_produce/generation.py` — new `_HUB_FRAMEWORK_GUIDANCE`, `_PAS_FRAMEWORK_
  GUIDANCE`, `_PAS_OPENING_PROBLEM_NOTE`, `_PAS_CLOSING_RESOLVE_NOTE` constants;
  `_FRAMEWORK_GUIDANCE` dict; `_build_batch_prompt()`'s bare `if framework == "AIDA"` branch
  replaced with a dict lookup; `_build_extra_section_directives()` gets a PAS branch mirroring
  the existing AIDA one.
- Tests: 4 new in `tests/unit/test_aa370_generation.py` (PAS positional directives, hub's
  absence of positional directives, hub prompt-level guidance, PAS prompt-level guidance +
  positional notes).

## Mục 5 — TikTok hook_beats_payoff

### Decisions
- **Extended the existing SCRIPT block's instructions rather than adding new labeled blocks.**
  `_CHANNEL_REQUIRED_MARKERS["tiktok"]` (`HOOK:`/`SCRIPT:`/`VISUAL:`) stays exactly 3 markers —
  changing that would touch the response-parsing contract (`adapt_channels()`'s
  `_invoke_channel_with_retry()`) for no real benefit; "timed beats" and "payoff" are properties
  of HOW the SCRIPT block is written, not separate content blocks CONTEXT.md's own phrasing
  ("shoot kit: hook / timed beats / payoff / paste-ready caption...") could be read either way,
  but the simpler, lower-risk reading was chosen.
- Built even though the audit noted "no real failure yet" — closing a known gap proactively,
  per the task's own instruction, rather than waiting for a failure to accumulate first.

### Changed
- `services/acp_produce/adapt.py` — `_TIKTOK_INSTRUCTIONS`'s SCRIPT line now requires "TIMED
  BEATS" (2-3 distinct sequential moments) ending in a "PAYOFF" (the moment that delivers on
  the HOOK's promise) — same style/tone as the existing HOOK/VISUAL guidance in the same
  constant, not a separate new prompt block.
- Tests: 1 new in `tests/unit/test_aa371_adapt_faq.py` — confirms the tiktok system prompt
  contains both new keywords and the facebook system prompt does NOT (channel isolation).

## Mục 6 — atom-per-section vs F1 grounding

### ⚠️ Built, NOT enabled in the live pipeline — needs Nghiep's explicit decision

Real-data impact analysis (all 23 real blog pieces across all 6 N7 runs to date,
`body_tagged` pulled live from `acp_deliver.pieces`) found:

- **9/23 (39%) real blog pieces already cite at least one atom in more than one H2 section**
  (excluding FAQ, which the mechanism already exempts by design — `generation.py::
  build_outline()` never assigns FAQ a key in `atoms_by_section` in the first place).
- Reading the actual cases: most look like an **overview/intro section legitimately
  previewing a detail** a later dedicated section develops in depth (e.g. the intro section
  mentions the Gyeongju bullet train briefly; a later section titled specifically about that
  train covers it in depth — same atom, two sections, both legitimate prose).

**Decision: implement the check as an opt-in parameter (`atoms_by_section`, default `None` —
zero behavior change for every existing caller), but do NOT pass it from `pipeline.py`'s live
blog call site in this PR.** Enforcing this unconditionally today would very likely convert
some currently-passing or already-marginal real pieces into new F1 failures, compounding
gates that are already near-0% pass rate. This mirrors how the F5 atom-density gate's
threshold question was handled (PR #162) — build the mechanism, surface the real-data impact,
let Nghiep decide whether/how to turn it on (e.g. maybe only flag it as a softer warning
first, or exempt "intro/overview" sections specifically, or accept the 39% impact and enable
it as-is).

### Decisions
- **Additive check, not a replacement** — the existing closed-world (`valid_ids`) and
  entailment (numeric-fabrication) checks are completely unchanged; `atoms_by_section` adds a
  THIRD, independent violation category on top.
- **Segments `body_tagged` the same way F4_brief_compliance already does**
  (`re.findall(r"^## (.+)$", body, re.MULTILINE)`) — reused convention, no new H2-parsing
  logic invented.
- **A section title that isn't a key in `atoms_by_section` (FAQ, or any future E4-owned
  section) is silently skipped**, not flagged as an error — it contributes no section-scoped
  check for that stretch of text, but the whole-piece checks above still cover it.

### Changed
- `services/acp_produce/gates.py` — new `_H2_RE` constant (reused H2-header pattern);
  `_check_section_atom_scoping()` helper; `gate_grounding()` gains the opt-in `atoms_by_section`
  parameter, default `None`.
- `services/acp_produce/pipeline.py` — **NOT touched**. `_f1` closure still calls
  `gate_grounding(body, valid_ids, text_by_id)` exactly as before — the new parameter is never
  passed from the live orchestrator in this PR.
- Tests: 5 new in `tests/unit/test_aa298_gates.py` — `None` behaves exactly like before
  (backward compat), same-section-only citation passes, cross-section citation fails, FAQ
  exempted, and a real corpus case (the Gyeongju bullet-train atom, from the same piece
  PR #155's F9 anchor sentence came from) reproduced as a concrete test proving the mechanism
  catches the exact real-data pattern the impact analysis found — not just a synthetic
  example.

## Verify (all 3 mục)
- Full suite: 1587 passed (was 1563 before this PR — the intervening jump also includes PR
  #161's own new tests, already on `main`), same 24 pre-existing unrelated failures (need
  local Postgres/creds, confirmed identical set).
- flake8 (CI's exact invocation): clean.
- Not run against real N7 data — build + unit-test only, per task scope.
