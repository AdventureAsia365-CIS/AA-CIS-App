# AA-404 — F5 atom density validator (new deterministic gate)

Separate file from `AA-404.md` (main file has an in-progress uncommitted section from a
concurrent session — same reason PR #159/#160 didn't touch it either).

## Context

`docs/claude_audit/AA-404-N0-N8-defense-layer-audit.md`'s Q2 confirmed
aa-marketing-v2/CONTEXT.md §1.6's highest-leverage anti-AI-voice layer ("Atom density
validator... AI-sounding text is an information-density problem, not a style problem") was
never built in this repo's port — F9 (the LLM judge, layer #4) has been carrying that load
alone, and `BODY_EXPERIENCE_DETAILS_TOO_GENERIC` is blog's #1 real F9 failure code (22/109
occurrences, `docs/implementation-notes/AA-404-F9-deep-dive.md`).

## Decisions

- **Faithful port of `aamc/gates.py::gate_atom_density()`, not a redesign.** The real original
  implementation exists (`docs/AI-gent-for automation works/aa-marketing-v2/aamc/gates.py:50-62`,
  `aamc/config.py:72`) — same algorithm (non-overlapping 300-word chunks, skip a trailing chunk
  under 150 words, flag any chunk with zero `[R:id]`/`[F:id]` tags), same `ATOM_DENSITY_WORDS =
  300` constant (the aamc original already resolved CONTEXT.md's "200–300" range to the upper
  bound — not re-decided here).
- **Claims the "F5" slot.** `gates.py`'s own docstring already documented this number as
  genuinely unused (AA-372's renumbering shifted atom density out without reassigning its
  number) — confirmed via grep before use, not assumed. The gate's functional position in the
  chain (right after F1, matching the aamc original's own F1→F2 order) is independent of this
  number — this repo's numbering was already non-sequential (F4 then F6, no F5) before this
  change, so gate-name and list-position are already decoupled by convention here.
- **Threshold: ANY zero-atom chunk fails the whole piece — no percentage/leniency knob.** This
  is not a threshold invented for this PR; it's the aamc original's own already-decided design
  (`if not TAG_RE.search(chunk): violations.append(...)`, unconditional). Flagged in this PR for
  Nghiep's explicit sign-off anyway, since it's a new gate with real production impact even
  though the strictness itself isn't a new decision.
- **No explicit `channel` parameter / no blog-only branch.** The aamc original's
  `gate_atom_density(piece)` never took a channel either — channel-agnostic by design. Real
  facebook (80-150 words)/tiktok (100-150 words) piece bodies fall entirely under the 150-word
  trailing-chunk floor, so the gate's own window-size guard exempts them naturally, before the
  tag-presence check ever runs — verified by test, not just asserted (see Verify below).
- **Wired right after F1 (grounding), before F2 (banned patterns)** — matches the aamc
  original's own order (F1 → F2 atom density) even though the repo's F2/F3/F4 numbers now refer
  to different gates (banned patterns, structural variance, brief compliance) than the aamc
  original's scheme. Position in `pipeline.py`'s `gate_fns` list, not the string label, is what
  determines evaluation order.
- **Reuses `gates.py`'s own module-level `TAG_RE`** (`\[(?:R|F):([^\]]+)\]`) — no new parser,
  same tag-matching F1_grounding already uses.
- **Violation strings carry enough context for repair** (word range + first-80-chars sample of
  the zero-atom stretch) — matches F1's own violation-message convention
  (`f"sentence states {novel} not present in its cited id(s): '{sent.strip()[:100]}'"`), no new
  evidence-field convention invented (DET gates in this repo return plain `violations: list[str]`
  consumed directly by `repair.py` — the F8/F9 `flagged_phrases` structured-evidence pattern is
  specific to those LLM gates' tuple-return contract, not something DET gates here use).

## Changed

- `services/acp_produce/gates.py` — new `ATOM_DENSITY_WORDS = 300` constant +
  `gate_atom_density(body_tagged: str) -> GateResult` ("F5_atom_density"), placed right after
  `gate_grounding()` (F1). Module docstring's Numbering note updated — no longer says atom
  density "is not built here."
- `services/acp_produce/pipeline.py` — imports `gate_atom_density`; new `_f5` closure; `gate_fns`
  list becomes `[_f1, _f5, _f2, _f3, _f4, _f6, _f7, _f8, _f9]`. Module + function docstrings'
  gate-order descriptions updated to include F5.
- `tests/unit/test_aa404_atom_density.py` — new, 11 tests direct on `gate_atom_density()`: pass/
  fail on a single window, multi-window (only the zero-atom one flagged, both flagged when both
  are), trailing-chunk boundary (149 skipped / 150 evaluated, exact `< window//2` semantics),
  empty body, `[F:id]` tag also satisfies density (not atom-only), facebook/tiktok-length bodies
  naturally exempted, violation message shape.
- `tests/unit/test_aa364_pipeline.py` — the one existing test asserting the FULL gate_ledger
  order (`test_piece_passing_all_gates_persists_passed_and_emits_metrics_but_not_usage_log`)
  updated to include `"F5_atom_density"` right after `"F1_grounding"` — confirmed this is the
  only such exact-order assertion in the suite (grepped before assuming).

## Tradeoffs

- **`gate_atom_density()` chunks mechanically on whitespace-split words, not markdown
  paragraphs** — matches the aamc original exactly (`body.split()` over the raw text, including
  H2 headers and the FAQ block in the word count). CONTEXT.md's own phrasing ("Zero-atom
  paragraphs are flagged") is looser than the actual aamc implementation, which the port follows
  faithfully rather than re-interpreting the prose description.
- **No new PieceInvariants field for atom-density repair.** A "zero-atom stretch" violation is
  fixable the same way any other content violation is (repair.py's existing CURRENT TEXT +
  VIOLATIONS TO FIX prompt shape) — no piece-wide structural fact needs to survive across rounds
  for this gate the way F3's section-ownership or F8's CTA-phrase do.
- **`run_gates()` runs the full gate_fns list every round regardless of which gate fails first**
  (confirmed by reading its implementation before assuming otherwise) — F5 failing does NOT skip
  F8/F9's Bedrock calls in the same round; it only means F5's violations are what gets targeted
  for repair first (first-failure-in-list-order). The real cost saving F5 offers is at the
  REPAIR level (a deterministic, free re-check vs. F9's LLM judgment call), not by short-
  circuiting evaluation.

## Should know

- **Threshold sign-off needed (see Decisions above)** — this PR proceeds with the aamc
  original's strict "any zero-atom chunk fails" design. If Nghiep wants a percentage-based
  leniency instead, that's a follow-up, not blocking this PR's merge (the current design is
  easy to loosen later — `ATOM_DENSITY_WORDS` and the all-or-nothing check are both isolated in
  one function).
- Not run against real N7 data in this PR (task scope: build + unit-test only, no live trigger).
  The real test of whether this measurably reduces F9's `BODY_EXPERIENCE_DETAILS_TOO_GENERIC`
  rate is a live N7 run after merge+deploy — same digest-verify → retrigger sequence as every
  prior AA-404 PR in this chain.
