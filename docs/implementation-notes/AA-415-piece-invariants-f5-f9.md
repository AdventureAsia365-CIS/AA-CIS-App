# AA-415 — extend PieceInvariants (atom_text_by_id) into F5/F9 repair rounds

Branch: `feature/aa-415-piece-invariants-f5-f9` | Task: `docs/claude_tasks/AA-415-01-piece-invariants-f5-f9-repair.md`
Source data: `docs/claude_audit/AA-404-n7-run6-results.md` (N7 run #6, `d0722ae3`, 2026-08-16)

## Root cause (confirmed, not re-derived here — see the source doc's Step 4 §F1_grounding)

Real trace for `d0722ae3:slot_140a1837492c88d70624:blog`: F1_grounding passed on the first
draft (`initial_failing_gate_count=1`), then 2 rounds of F9_brand_seo_audit repair + 1 round
of F5_atom_density repair rewrote prose to fix "too generic" / "under-cited" violations —
each round writing brand-new sentences with no atom/fact text to check them against. F1 then
failed for the first time on the FINAL gate-stack check, after the repair budget (sized off
the *original* 1-gate failure count) was already spent, so the piece never got a dedicated F1
repair round. `PieceInvariants` (PR #154) already exists as the mechanism that survives
cross-gate regressions for F3/F8 — it just never carried `atom_text_by_id`, the one field
AA-404's own STEP-0 doc named and explicitly deferred.

## Decisions

- **Wired generally, not F5/F9-specific.** `repair_piece()` has ONE prompt-builder for every
  gate — `run_gates()` targets "the first failing gate" each round and calls the same
  `_repair` closure regardless of which gate that is (see `gates.py::run_gates()` /
  `pipeline.py::run_piece_through_produce_gates()`). There is no F5-only or F9-only code
  path to hook into. Adding `atom_text_by_id` to `PieceInvariants` and gating its prompt
  block on `if invariants.atom_text_by_id:` (same pattern every other field already uses)
  means every repair round gets the grounding note, not just F5/F9-triggered ones — this
  matches the source doc's own recommendation ("extend it to carry atom_text_by_id into
  every repair round regardless of which gate triggered it") and needed zero new
  branching/plumbing.
- **Reused the existing `text_by_id` dict, no new data flow.** `run_piece_through_produce_
  gates()` already threads `text_by_id: dict[str, str]` into F1's (`gate_grounding`) and F2's
  (`gate_banned_patterns`) closures. `_build_repair_invariants()` now takes the same dict as
  an optional 5th param and copies it straight into `PieceInvariants.atom_text_by_id` — no new
  DB column, no new `Piece` field, no second parameter on `repair_piece()`.
- **`single_atom_required` interaction.** A facebook `hook_story_cta` piece's structural
  context already tells repair to cite ONLY the atom(s) already in the body. Showing the FULL
  atom pool in the same prompt would contradict that. `_build_grounding_note()` filters to
  only the currently-cited atom(s) when `single_atom_required` is set (re-derived from the
  current body via the existing `_currently_cited_atom_ids()` helper — same "re-derive, don't
  store" pattern the rest of `PieceInvariants` already follows).

## Changed

- `services/acp_produce/repair.py`: `PieceInvariants.atom_text_by_id: dict[str, str] = {}`
  (new field); `_build_grounding_note()` (new helper) + one new conditional block in
  `_build_structural_context()`.
- `services/acp_produce/pipeline.py`: `_build_repair_invariants()` gained an optional
  `text_by_id` param; its one call site (inside `run_piece_through_produce_gates()`) now
  passes the `text_by_id` already in scope there. Module docstring updated with an AA-415
  paragraph.
- Tests: `tests/unit/test_aa376_repair.py` (+5 tests — grounding note present for F5- and
  F9-triggered rounds, absent when `atom_text_by_id` is empty, restricted-to-cited-atom under
  `single_atom_required`), `tests/unit/test_aa404_repair_invariants.py` (+2 tests — pass-through,
  default-empty).

## Tradeoffs

- The grounding note lists the FULL known atom/fact pool (not just currently-cited ones)
  for non-single-atom pieces, same as `generation.py`'s batch prompts already do — this can
  make the repair prompt larger for blog pieces with many atoms. Accepted: `repair_piece()`'s
  `max_tokens=4096` ceiling is on the *output*, not the input, and giving repair the full pool
  is the whole point (F5's violation literally asks for "a specific, verifiable detail" — that
  detail has to come from somewhere real).
- Did not touch F1_grounding, F5_atom_density, or F9's own gate logic — per the task's own
  scope boundary ("chỉ đổi input mà vòng repair F5/F9 nhận được và hướng dẫn prompt").

## Should know / verification status — NOT fully verified yet

- **Unit-tested only, not live-verified.** All 47 relevant unit tests pass (45 pre-existing +
  7 new, minus dupes — see `pytest tests/unit/ -q`: 1328 passed) and `flake8` is clean. This
  confirms the new prompt content is built correctly; it does **not** confirm a real Bedrock
  Sonnet repair call actually stops introducing ungrounded claims, and does **not** confirm F1
  pass rate improves on a real N7 run (learned discipline from S149: unit-test-green ≠
  real-content-gate-passing).
- **Live verification (Verify steps 1/2/4/5 from the task) is deliberately NOT done in this
  session.** It requires this branch's code to actually be running on ECS, which only happens
  after this PR merges to `main` (push-to-main auto-deploys per this repo's CI/CD) — and per
  both the task's own instruction ("Sau khi done: ... KHÔNG tự merge") and this workspace's
  git rule ("DO NOT merge to main yourself — human does that manually"), this session opens
  the PR and stops there.
- **Next step (post-merge, for whoever runs it):** re-trigger N7 for a new/unused
  `(tenant_id, year, month, week)` slot tuple (run #6 used 2026-09 w2; next unused combo per
  the source doc's own method), pull real `gate_ledger` from `acp_deliver.pieces`, and compare
  F1_grounding first-fail rate against the run #6 baseline (4/9, 44%) — same methodology as
  `docs/claude_audit/AA-404-n7-run6-results.md` Step 3. Do not report AA-415 as fixed off unit
  tests alone.
- Baseline commit for comparison: `main` at merge of PR #163 (`e271ef5`, run #6's code state).
  This branch's base: `80c7a60` (task-prompt commit) off `main`.
