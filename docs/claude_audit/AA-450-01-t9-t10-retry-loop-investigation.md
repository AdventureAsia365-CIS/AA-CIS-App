# AA-450-01 — Phase 1: T9↔T10 retry-loop investigation (BEFORE schema/API)

Per the build task's explicit gate: this is written and presented for confirmation BEFORE any
`content_piece` schema, migration, or API code is touched. Investigate-only, no code changed
this pass. Saved locally per the new PR process (no separate PR — folds into the eventual build
PR on `feature/aa-450-build-t9-content-writing`).

**Headline: SKILL_v2.md describes NO retry loop at all — it's one write pass + one internal
revise pass, done. The retry-loop machinery (3 base rounds, scalable to 8) is entirely N7's own
invention (ADR-2026-029/AA-396), and N7's real, confirmed problem was NOT "infinite loop" — it
was a synchronous, single-request repair loop that (a) re-runs the ENTIRE gate stack including 2
blocking ~14s LLM calls after every round, which froze the shared event loop badly enough to
cause real production ALB-timeout/task-restart incidents before a fix, and (b) burns 60% of total
run cost on repair rounds that mostly don't even converge for the hardest gates (2.5%-14.6%
success rate). Recommendation below: keep T9's write endpoint fast and un-looped; put all retry/
convergence complexity in T10 (separate future issue), running async, calling T9's write function
as a bounded, capped set of independent attempts — never an in-request loop.**

---

## 1. What SKILL_v2.md actually says about retry — nothing

Grepped the full 365-line file for `retry|retries|loop|again|revise|attempt|limit` (case-
insensitive): zero hits describing a retry mechanism. The only relevant text is the workflow's
own step 10, "Run quality/editor pass internally" — one step, no stated count, no described
loop-back to step 9. The one real prior implementation of this exact step
(`services/acp_s4_social/quality.py::quality_pass()`, referenced not reused, per STEP0 §2b)
matches this exactly: **one more LLM call that revises inline and reports `passed`/`warnings` —
no loop, no re-invocation of the writer.**

**Conclusion: there is no retry-count number to inherit from the source skill, because the
source skill doesn't describe a retry loop at all.** Any retry/repair mechanism for the NEW T9↔T10
design is a genuinely new decision (like N7's own F1-F9 retry loop was), not a recovered spec.

---

## 2. N7's real retry loop — confirmed shape, confirmed problem

### 2a. Feedback shape (question 1) — confirmed specific, not generic

`services/acp_produce/pipeline.py::run_piece_through_produce_gates()` builds one closure per
gate (`_f1`..`_f9`), each returning a `GateResult(gate, passed, violations: list[str])`. On
failure, `gates.py::run_gates()` calls `_repair(body, violations)` → `repair_piece(body,
violations, invariants=...)` — **the exact violation strings from the exact gate(s) that failed
are passed to the repair LLM call, not a generic "something's wrong" message.** Confirmed real
and specific — not a guess.

### 2b. Retry limit (question 2) — no number in SKILL_v2.md; N7's own numbers, and why

`services/acp_produce/models.py`:
```
REPAIR_TOTAL_MAX = 3   # ADR-2026-029 — base budget, 1 attempt/failing gate up to 3 ROUNDS total
REPAIR_BUDGET_CAP = 8  # AA-396 follow-up — hard ceiling when compute_repair_budget() scales up
                        # for a piece with >1 gate failing at once (worst real case observed:
                        # 4 simultaneous failures -> budget 6; 8 leaves headroom for one more)
```
A "round" = 1 repair LLM call (E5, Sonnet) + a FULL re-run of every one of the 9 gates (P0-3,
AA-404's own fix — see 2c) — not just a re-check of the gate(s) that failed.

### 2c. The real problem N7 hit (question 2, "quan trọng hơn") — two confirmed, connected issues, not a guess

**Issue A — a real correctness bug that made the loop more expensive by design, not less
(AA-404).** Originally a repair round only re-checked the gate(s) it targeted. Real evidence (45
pieces across 4 N7 runs, `docs/implementation-notes/AA-404.md`): a repair round fixing one gate
could **silently regress an earlier, already-passing gate** the repair call had zero visibility
into — 14 events / 13 pieces, 4 causal pairs (F9-social→F8 6x, F4→F3 3x, F9-blog→F4 3x, F4→F2
2x). Fix: `run_gates()` now re-runs the ENTIRE 9-gate stack after every single repair round (not
just the targeted gate) — correct, but this is exactly what makes issue B expensive: every round
now costs a full stack re-run, including 2 LLM judge calls (F8/F9, Nova Pro), not just 1 repair
call.

**Issue B — the real production incident (AA-416/AA-418), confirmed by measured data, not
inferred.** `run_gates()` is a synchronous `while` loop. One real measured E5 repair call:
**`latency_ms=13790.6`** (~13.8s), blocking. Before AA-416's fix, this loop ran bare (no `await`/
`to_thread`) inside an `async def` call chain, on the SAME event loop as `/health` and all other
API traffic — because N7's background job (`_produce_slots_background`) shares the one ECS task
with the tenant/admin-facing API server. **A single piece needing multiple repair rounds could
block that event loop for 13.8s × up to 8 rounds — well over 100 seconds — and this genuinely
caused real ALB health-check timeouts and ECS task kill+restart, confirmed in a real run
(`docs/claude_audit/AA-404-n7-run6-results.md`, "run #6": 2 real ALB timeout incidents, 1 slot
had to regenerate from scratch).** AA-416 fixed the SYMPTOM (`asyncio.to_thread()` moves the
blocking call off the event loop) — it explicitly did NOT fix the underlying slowness; the piece
loop stays fully sequential today (AA-416's own "Tradeoffs": "deliberately did NOT add
concurrency"). AA-418 investigated true parallelism to actually speed this up and found 3 more
structural blockers (shared non-thread-safe DB connection, sync boto3 calls, unverified acc3 RPM
quota) and explicitly recommended NOT parallelizing yet.

**Issue C — low convergence, confirmed by real repair-round data, compounding both A and B.**
`services/acp_produce/generation.py`'s own comment, sourced from real repair-round outcomes:
**F8 repair success rate 14.6% (41 rounds, 6 passed); F3 2.8%; F9 2.5%.** Most repair rounds on
the LLM-judge-class gates simply do not converge. Cost confirms this is not free: E5 repair alone
was **60% of one real run's total cost** ($0.77 of $1.28, 35 repair calls in that run,
`docs/claude_audit/AA-418-parallel-cost-investigation.md` §B.4) — a large majority of spend goes
to repair attempts, and per Issue C, most of those specifically targeting judge gates fail
anyway.

**One-sentence synthesis of "the problem N7 vướng" (what NOT to repeat)**: a synchronous,
in-single-call repair loop that re-runs the entire gate stack (2 blocking LLM calls included)
after every round, up to 8 rounds deep at ~14s/call — this both froze a shared event loop badly
enough to cause a real production incident, AND burns most of the run's cost on repairs that
mostly don't even succeed for the hardest checks. It was worked around (moved off the event
loop), never actually solved (still slow, still low-converging, true parallelism explicitly
deferred as unsafe).

### 2d. What happens when the budget runs out (question 3) — confirmed, no "best draft" logic

`piece.status = "held"`, `piece.held_reason` set from the LAST round's `GateResult` (whichever
gate(s) still failed), full `gate_ledger` + `repair_log` (`RepairRoundLog` per round: which gate
targeted, violations, outcome) persisted to `acp_deliver.pieces` for a human (admin Review-Queue-
adjacent flow) to inspect. **There is no "return the best of N attempts" selection — the piece
simply holds wherever `body_tagged` landed after the last round, with the full attempt history
visible, not silently discarded.** One gate class is filtered OUT of repair entirely before even
entering the loop: F6 violations that are external caller/DB state ("no cta_target", "url_alive
not True") — `_is_f6_content_fixable()` holds those immediately, since no amount of rewriting
`body_tagged` can fix a missing DB row. **This is a directly relevant precedent for T9/T10's own
CTA handling (build task §3)** — if a piece is missing its CTA context entirely, that's an
immediate hold, not something to spend a repair round attempting to fix by rewriting prose.

### 2e. Architecture (question 4) — confirmed: N7 is Option A (one call, in-process loop) — and that's exactly where the real incident came from

`_produce_slots_background()` → `run_slot_production()` → `run_piece_through_produce_gates()` →
`run_gates()`'s while-loop — write, gate-check, and repair-rewrite all happen inside ONE
call chain, no separate async round-trips per attempt. This was tenable for N7 because it's a
**background admin job** — no interactive human is waiting on an HTTP response for it. **T9, as
this build task's own API design specifies, is a synchronous tenant-facing `POST .../write` —
not a background job.** Coupling a T10 gate-check-and-repair loop into that same request would
import N7's exact failure mode directly onto tenant-facing traffic, on infrastructure that has
not changed since the incident (still one ECS task, still admin+tenant traffic sharing whatever
process serves it).

---

## 3. Recommendation (for confirmation, not decided here)

**Keep T9 (this task) simple and un-looped, exactly matching what SKILL_v2.md actually
describes**: one endpoint, one LLM call, save `content_piece` with a not-yet-final status,
return immediately. No repair loop lives inside T9's own request.

**Push all retry/convergence complexity into T10's own scope (separate, not-yet-created issue)**,
and when it's built, have it call T9's write function as a bounded number of independent new
attempts — not an in-process loop nested inside T10's own gate-check call:
- T10 runs asynchronously relative to the tenant's write request (background task, matching N7's
  own `_produce_slots_background` pattern, or a queue — the exact mechanism is T10's own build
  decision, not this task's).
- If T10 fails a check, it triggers ONE new T9 write attempt (full independent call, T9's own
  endpoint, not a nested repair function) with the specific failure feedback attached — mirroring
  §2a's confirmed "specific, not generic" feedback shape, a real and worth-keeping part of N7's
  design even though the surrounding architecture changes.
- Cap attempts low — given §2c's real convergence data (judge-class checks converge on repair
  only 2.5%-14.6% of the time), a low cap (e.g. 2 total write attempts before holding) is better
  supported by N7's own real numbers than reusing N7's 3-8 round range, which was calibrated for
  a background job with no latency-to-a-human constraint.
- On exhausting the cap: mark the piece held/needs-review (mirroring §2d's real fallback — no
  best-of-N selection, keep the last attempt with full history visible), never loop further.

**Why this avoids issue B specifically**: no single tenant-facing HTTP request ever blocks for
multiple rounds of LLM calls; each write attempt is its own fast, independent request/response,
and whatever runs T10's check-and-possibly-retrigger logic is async and doesn't share a request
with a waiting tenant the way N7's loop shared an event loop with `/health`.

### Schema implication for `content_piece` (§4 of the build task) — flagged now, not built yet

If T10 will create new write attempts by calling T9's endpoint again, `content_piece` needs a way
to represent "which attempt is this, for which request" — **`attempt_number` (int, default 1)
scoped by `angle_gate_request_id`** is sufficient (mirrors `angle_gate_option`'s own established
`(request_id, idx)` pattern, T8's precedent for "ordered child rows under one parent"). A
`previous_piece_id` self-referencing chain is NOT needed under this design — attempts are
strictly "newest replaces what's shown for this request," not a branching tree, so
`(angle_gate_request_id, attempt_number)` as a unique pair is enough lineage. This is offered as
the concrete answer to the build task's own §4 open question, contingent on this whole
architecture being confirmed first.

---

## Open for confirmation before Phase 2 starts

1. **Architecture**: T9 = one fast, un-looped write call; T10 (separate issue) owns all retry/
   repair logic, running async, capped low, triggering new independent T9 write attempts rather
   than an in-process repair loop. Confirm or redirect.
2. **`content_piece` schema consequence**: `attempt_number` int scoped by
   `angle_gate_request_id`, no `previous_piece_id` chain. Confirm or redirect.
3. Everything else in the build task (CTA migration, `acp_content_writing/` service, API,
   frontend, verify) is unaffected by this architecture question and can proceed once 1-2 are
   confirmed.
