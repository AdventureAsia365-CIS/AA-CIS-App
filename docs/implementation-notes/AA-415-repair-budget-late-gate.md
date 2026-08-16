# AA-415 — reserve repair-budget headroom for late-appearing gates

Branch: `feature/aa-415-repair-budget-late-gate` | Task:
`docs/claude_tasks/AA-415-03-repair-budget-late-gate.md`
Source data: `docs/implementation-notes/AA-415-verify-real-run.md` (real N7 run `363f22c9`,
2026-09 W3, 16/08/2026) — the exact piece that motivates this fix:
`363f22c9:slot_efb6c6d175e23bad4767:blog#tiktok`.

## Root cause (confirmed against real data, not re-derived here)

`initial_failing_gate_count=1` (only F9_brand_seo_audit_social failing on the first draft) →
`compute_repair_budget(1, 3) = 3`. Rounds 1-2 targeted F9 (both failed). By round 3's
gate-stack re-run, F1_grounding — never failing before — started failing, a real side effect
of the F9 repair rewrite (the exact class PR #170's `atom_text_by_id` narrows but does not
eliminate). F1 became `first_failure` (it's checked before F9 in gate order) and got exactly
ONE round (round 3) before `piece.repair_count(3) >= repair_budget(3)` held it. F1 never got
the same per-gate round allowance `compute_repair_budget()` already gives a gate that was
failing simultaneously from the start.

## Decisions

- **Extended the EXISTING budget mechanism, did not build a second one.** `compute_repair_
  budget()` already treats "one more distinct gate failing" as "+1 round," just only at the
  piece's FIRST gate-stack run. `run_gates()` now applies the identical +1 rule the FIRST time
  a gate that was NOT in that initial failing set is discovered mid-loop — same spirit,
  triggered by discovery time instead of only initial snapshot time. This was the task's
  option (b) framing extended just enough to actually work: a bare "reserve 1 slot within the
  EXISTING total" (never increasing the ceiling at all) can't be expressed without either (i)
  retroactively taking a round away from a gate that already used it — impossible, that round
  already happened — or (ic) pre-emptively reserving a slot for a late gate that might never
  materialize, which would just LOWER the effective budget for every gate on every piece that
  never hits this case (regressing the AA-396 sizing this repo already tuned against real
  data). A capped, per-distinct-late-gate +1 is the smallest correct extension of (a) that
  reuses the current formula's own reasoning instead of inventing a new one.
- **Bounded exactly like the existing formula.** `REPAIR_BUDGET_CAP` (8, unchanged) is still
  the one hard ceiling — a piece already at the cap via simultaneous initial failures gets NO
  further extension from a late gate (test:
  `test_run_gates_late_gate_extension_still_bounded_by_cap`). A late gate that keeps failing
  across many rounds only extends the budget ONCE (on first discovery), not once per round
  (test: `test_run_gates_late_discovered_gate_extension_happens_once_not_per_round`) — same
  non-runaway guarantee the original AA-396 fix established.
- **`initial_failing_gate_count` itself is unchanged/still set once** — only `repair_budget`
  (already a mutable `Optional[int]` field on `Piece`) can now be bumped mid-loop. Documented
  explicitly in `models.py` since the prior docstring there said "never recomputed mid-loop,"
  which was true before this change and is no longer quite right without a caveat.

## Changed

- `services/acp_produce/gates.py::run_gates()` — tracks `initial_failing_gates: set[str]`
  (captured alongside the existing `initial_failing_gate_count` on round 0) and
  `late_gates_extended: set[str]` (which late gates have already triggered their one-time
  bump); bumps `repair_budget` by +1 (capped) the first time `first_failure.gate` is neither
  of those. New log event `n7_repair_budget_extended_for_late_gate`.
- `services/acp_produce/models.py::Piece` — docstring correction on
  `initial_failing_gate_count`/`repair_budget` (see Decisions).
- Tests (`tests/unit/test_aa396_repair_budget.py`, +3): late gate discovery lets a piece that
  would have held now converge; extension fires once per distinct late gate, not per round;
  cap still bounds a late gate on top of an already-capped piece. 1331/1331 unit tests pass,
  flake8 clean.

## Tradeoffs

- **Cost, in words (per task's request, no code — see AA-418's cost investigation for the
  measurement method)**: this only spends 1 EXTRA Sonnet repair call, and only for a piece
  that both (a) had a gate genuinely appear late AND (b) would otherwise have run out of
  budget on it. From the one real run this fix is grounded in (`363f22c9`, 12 pieces), exactly
  1/12 pieces would trigger this — using AA-418's own per-call cost figure (~$0.02-0.03/Sonnet
  repair call at typical token counts), the realistic added cost is on the order of a few
  cents per N7 run, not a material change to the ~$1.28/run figure AA-418 measured.
- Does not address the 2/3 F1 failures in the verify run that were failing from the FIRST
  draft and never converged despite getting their full ORIGINAL budget already (see Should
  know below) — this fix only helps the "squeezed by budget sharing" failure mode, not a
  "repair genuinely can't fix this violation" failure mode. Those are a different problem.

## Should know — a genuine, CONFIRMED new bug found while investigating, NOT fixed here

Per the task's step 3, read the real `body_tagged` for both "loại 1" pieces from the verify
run (piece fails F1 from the first draft, gets its full dedicated budget, never converges) —
**this is a real F1_grounding bug, not a hallucination, not related to AA-415/PieceInvariants,
confirmed with a precise root cause, not just a hypothesis:**

`gates.py::_SENT_SPLIT_RE` (`r"(?<=[.!?])\*{0,2}\s+\*{0,2}(?=[A-Z\"'‘’“”])"`) fails to split a
sentence boundary when a `[R:id]`/`[F:id]` citation tag sits BETWEEN the sentence-ending
punctuation and the next structural markdown element (an H2 heading or a `**Q:` FAQ marker) —
the citation tag's `[`/`]` characters break the tight `\*{0,2}\s+\*{0,2}` pattern the regex
expects right after the period, even though AA-405 already hardened this same regex for the
plain (no-citation) heading/FAQ-marker case. Confirmed against BOTH real pieces:

- `slot_3485bd7d3513aaee9f89:blog` ("Ride 99"): `"...will find the network accommodating of
  exactly that. [R:atom_f915ce61ef]\n\n## Ride 99km along the Bukhangang River..."` — the
  citation `atom_f915ce61ef` (about private-arrangement services) gets merged with the NEXT
  section's heading text ("99 kilometres..."), so `find_novel_numeric_claims()` checks "99"
  against the WRONG atom's text and (correctly, given the wrong input) flags it as
  unsupported. The real Bukhangang paragraph's own citation (`atom_46cd54f569`) almost
  certainly DOES support "99 kilometres" — this piece is not fabricating anything, F1 is
  checking the right number against the wrong source.
- `slot_efb6c6d175e23bad4767:blog`: same mechanism, FAQ variant — `"...global export of
  Korean cuisine. [R:atom_ecd0b9aa65]\n\n**Q: What is the 3 day rule in Korea?**\nA: ..."` —
  the citation merges with the FOLLOWING FAQ question's own text ("3 day rule"), and the "3"
  gets checked against the wrong atom.

**Not fixed in this PR — out of scope per the task's own instruction, and it's a different
file/function (`_SENT_SPLIT_RE`) than what this fix touches (`run_gates()`/
`compute_repair_budget()`).** Recommend a separate issue: the fix is narrow and well-scoped
once someone picks it up — extend `_SENT_SPLIT_RE` (or add a citation-tag-aware pre-step) to
also treat `[R:id]`/`[F:id]` immediately before a heading/FAQ-marker boundary as a split point,
mirroring the AA-405 precedent exactly. This is confirmed, not speculative (2 independent real
occurrences, same root cause both times, real production content) — recommending a new issue
is warranted here, unlike an unconfirmed hypothesis.

## Verification status — code + unit tests only, live verify PENDING per task's own instruction

- ✅ 1331/1331 unit tests pass (3 new), flake8 clean.
- ❌ **NOT live-verified against a real N7 run.** The task's own git-context section says "tự
  `gh pr create` (KHÔNG tự merge)" — this fix is not deployed, so Verify steps 2 (new-week N7
  run, F1 pass-rate comparison against the 55.6%/75% baselines) and 4 (ECS digest match) genuinely
  cannot be done yet — they need this PR merged and deployed first, same gate the original
  PR #170 verification was under before Nghiep's explicit go-ahead to merge. Not doing it
  without that same signal here.
- **Next step (post-merge):** re-trigger N7 for an unused `(tenant, year, month, week)` — next
  candidate `(aa_internal, 2026, 9, 4)`, confirmed unused as of this writing — pull real
  `gate_ledger`/`repair_log`, and specifically check whether ANY held piece's F1 failure still
  shows the "budget exhausted right after a late discovery" shape (repair_log's LAST round
  targeting F1 with `repair_count == repair_budget` where F1 was NOT in the piece's own
  first-round gate_ledger). Do not report this fixed off unit tests alone.
