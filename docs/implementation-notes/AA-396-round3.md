# AA-396 round 3 — dynamic repair budget per gate-failure count (option C) + repair-round logging

Follow-up to AA-396 round 2 (`AA-396-round2.md`, PR #147/#148). Round 2's "Should know" section
explicitly left the shared `max_repairs=3` budget starving pieces with multiple simultaneous
gate failures as open, unresolved. This round fixes that specific gap — piece
`slot_b09166b7f2fdc28c87fd:blog` (4 gates, F3+F4+F8+F9, all failing at once) could not
mathematically converge under the old flat budget: `run_gates()` only ever targets ONE gate per
round, so 3 rounds can fix at most 3 of 4 simultaneous failures.

## STEP 0 findings (reported before building, per the task)

1. `run_gates()` (`services/acp_produce/gates.py`) re-runs the entire gate stack after every
   repair (P0-3), targets the first-failing gate per round in `gate_fns` declaration order
   (F1→F2→F3→F4→F6→F7→F8→F9, set by `pipeline.py`), and holds once
   `piece.repair_count >= max_repairs`. `repair_piece()` (`repair.py`) is gate-agnostic — one
   function handles any gate's violations, unchanged by this fix.
2. **The "less-log.md" pattern referenced in the task does not exist anywhere in this repo** —
   grepped the whole `~/projects/aa-cis` workspace for `less-log`/`less_log`/`ADR-2026-009`; the
   only hit is `gates.py`'s own aspirational comment about a future "N8 flywheel". The REAL
   Mistake-to-Rule mechanism is `services/acp_shared/h3_rule_extractor.py::extract_and_save_rule()`
   (H-3): async, triggered after a **human reviewer's HITL rejection**, requires a real
   `acp_shared.acp_hitl_requests` row + `acp_runs.tenant_id`, calls Haiku to extract a
   block/replace/flag pattern, inserts into `acp_shared.acp_output_rules` when confidence ≥ 0.80.
   **N7 (`acp_produce`) has zero wiring into H-3** — confirmed by grep, zero references either
   direction. N7 pieces are held by automated gate-exhaustion, not human rejection, so there is
   no `rejection_note`/`hitl_id` to hand H-3 as-is — full wiring is a bigger lift than this task,
   see Should-know.
3. Corpus check (`docs/implementation-notes/AA-391-report-data.json`, the 9 real
   `aa394_followup_test` held pieces): max simultaneous failing-gate count observed across all 9
   is **4** (the piece named above). No piece exceeded that. Used to calibrate the cap.

## Decisions

- **Option C, as specified**: `max_repairs` (models.py `REPAIR_TOTAL_MAX = 3`, ADR-2026-029) is
  now read as the BASE budget for the common single-gate-failure case, not always the piece's
  final ceiling. `gates.py::compute_repair_budget(initial_failing_gate_count, base_repairs=3)`
  returns `min(base_repairs + max(0, initial_failing_gate_count - 1), REPAIR_BUDGET_CAP)`.
  Computed exactly once per piece, from that piece's FIRST full gate-stack run (round 0, before
  any repair) — never recomputed on a later round, so the budget is fixed at the outset, not a
  moving target chasing whatever happens to fail later.
- **`REPAIR_BUDGET_CAP = 8`** (models.py). Calibrated off STEP 0's corpus finding: worst real
  case is 4 simultaneous failures → budget 6 under the formula. 8 leaves headroom for one more
  simultaneous failure than anything seen in production while still bounding a pathological
  piece's Sonnet-repair spend (a piece somehow failing 10 gates at once does NOT get 12 rounds).
- **Repair strategy unchanged, as explicitly instructed**: still one gate targeted per round
  (first-failing, in `gate_fns` order), still a full-stack re-run after every repair (P0-3). Only
  the round ceiling is dynamic now. Did not touch F3/F4 threshold calibration or attempt
  multi-gate-per-round repair (option B) — both explicitly out of scope.
- **Backward compatibility verified, not assumed**: every existing `run_gates()` caller/test that
  only ever sees 0 or 1 gates fail at round 0 gets `compute_repair_budget(...) == base_repairs`
  exactly — confirmed by running the full pre-existing `test_aa298_gates.py` suite unmodified
  (12/12 pass) before writing any new tests.
- **Logging: structlog (real-time) + persisted `repair_log` (durable, human-reviewable), not a
  new bespoke log file.** `run_gates()` now emits `n7_repair_budget_computed`,
  `n7_repair_round_attempt`, `n7_repair_round_result`, and `n7_repair_loop_summary` structlog
  events (CloudWatch `/ecs/aa-cis-dev`). It also builds `piece.repair_log`
  (`list[RepairRoundLog]`, models.py: round, gate_targeted, violations, outcome) and sets
  `piece.initial_failing_gate_count`/`piece.repair_budget` on the `Piece` itself —
  `pipeline.py::_persist_piece()` writes all three to new `acp_deliver.pieces` columns
  (migration 102), the SAME row a human already opens for `held_reason`/`gate_ledger`. This was
  the deliberate choice over inventing a separate log store, per the task's own fallback
  instruction (see Should-know for what's NOT wired).

## Changed

- `services/acp_produce/models.py`: `REPAIR_BUDGET_CAP` constant; new `RepairRoundLog` model;
  `Piece` gains `initial_failing_gate_count`/`repair_budget`/`repair_log` fields.
- `services/acp_produce/gates.py`: new `compute_repair_budget()` (pure function); `run_gates()`
  rewritten to compute the budget once from round 0's gate-stack run, build/log `repair_log`
  per round, and log a final `n7_repair_loop_summary`. Control flow (gate order, one-gate-per-
  round targeting, full re-run after repair, `is_repairable` filter, exception-holds-without-
  incrementing semantics) is byte-for-byte the same as before — only the budget source and the
  added logging/bookkeeping are new.
- `services/acp_produce/pipeline.py`: docstring updated; `_persist_piece()` writes
  `repair_log`/`repair_budget`/`initial_failing_gate_count`.
- `api/migrations/102_acp_deliver_pieces_repair_log.sql`: adds the 3 columns above to
  `acp_deliver.pieces` (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, no backfill — pre-fix rows
  have no meaningful history to backfill).
- Tests: `tests/unit/test_aa396_repair_budget.py` (new) — `compute_repair_budget()` unit tests
  (1-gate unchanged, piece-1-shaped 4-gate scaled budget + convergence proof, 8-gate cap
  enforcement, repair_log exception/clean-body bookkeeping). `tests/unit/test_aa364_pipeline.py`
  — one existing test (`test_piece_that_never_repairs_holds_after_max_repairs_rounds`) updated:
  its real fixture fails 5 gates simultaneously through the actual pipeline (not 1, despite the
  name), so it now correctly asserts budget=7/repair_count=7 instead of the old flat 3 — this is
  the fix working as intended, not a regression papered over.

## Tradeoffs

- `run_gates()`'s per-round bookkeeping (tracking `pending_round`, resolving its outcome on the
  NEXT loop iteration) makes the function longer than the flat-budget version. Kept as a single
  function rather than splitting, since the state (which gate a round targeted, whether it
  passed) only becomes knowable on the following iteration's gate re-run — splitting it would
  need to pass that same state back out anyway.
- `repair_log`'s `outcome` reflects whether the TARGETED gate passed on the next full re-run, not
  whether the piece as a whole passed — a round can show `outcome="passed"` for its targeted gate
  while a DIFFERENT gate regressed (P0-3's own scenario) and the piece still holds overall. This
  is intentional (matches what `run_gates()` actually checks per round) but means reading
  `repair_log` in isolation without also checking `gate_ledger`/`held_reason` could
  misrepresent a held piece as "each round succeeded."

## Should know

- **Mistake-to-Rule (H-3) auto-promotion is NOT wired here — deliberately, per the task's own
  escape valve.** `repair_log`/`repair_budget`/`initial_failing_gate_count` are the minimal
  structured record a human needs to manually promote a recurring repair-loop pattern into an
  `acp_shared.acp_output_rules` row (the same way the original 22 seed rules, migration 020, were
  authored by a human reading real output — not by an automated extraction). Automatically
  calling `extract_and_save_rule()` (H-3) from a held N7 piece was NOT built: H-3 requires a real
  `acp_hitl_requests.hitl_id` + a human-authored `rejection_note`, neither of which an
  auto-repair-exhausted piece has — synthesizing a fake reviewer note to satisfy H-3's shape
  would be inventing a new state category the task didn't ask for. Wiring N7 into H-3 (or a
  purpose-built variant) is a separate follow-up.
- This does not close AA-396. Per round 2's own note (unchanged by this round): F8's "ends with
  CTA" judge reliability (fixed separately, `f8_deterministic_cta`) aside, F3/F4 threshold
  calibration against real writer output remains open, out of scope here.
- Not re-run against live Bedrock/Nova Pro/DB as part of this fix (AWS is stopped this session,
  per repo convention) — verified by unit test only, using the real piece-1 failing-gate SET
  reconstructed from `AA-391-report-data.json`. A live re-verify (re-running `run_slot_production()`
  against the same South Korea trip data) would be the natural next step before calling the
  held-rate problem solved.
