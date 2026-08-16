# AA-351-06 — GPT-4.1 judge through a real multi-round N7 repair loop

Task: `docs/claude_tasks/AA-351-06-gpt41-multiround-real-n7.md`. No branch — docs-only,
env-var experiment on `main`. Follows `docs/implementation-notes/AA-351-gpt41-judge-trial.md`
(AA-351-03/05), which explicitly flagged its own limitation: single-pass judging on
already-scored content cannot answer AA-382's real question (does a judge keep flagging a
*new* phrase every repair round even after the old one was fixed?). This task ran the real
thing: one live N7 week, `JUDGE_MODEL=gpt41`, through the actual multi-round repair loop.

## Headline finding

**The core question is still open — this run produced zero F9 repair-round data to
answer it with.** Across all 6 real pieces produced this run, GPT-4.1's F9 judge
(`gate_brand_seo_audit`/`gate_brand_seo_audit_social`) **passed clean on the very first
attempt, every single time — 6/6, 0 repair rounds ever triggered for F9.** Nothing failed
F9 for GPT-4.1 to re-judge, so there is no round-2/round-3 held_reason to compare for
drift or convergence. This is a real, honest result, not a null result to explain away —
but it is not the result the task set out to measure.

**What this run DOES add**: a second independent real-world sample (after AA-351-05's
9-piece single-pass comparison) of GPT-4.1 passing essentially everything on F9. Two
different sampling methods (single-pass re-judge of existing content vs. live production
through the real pipeline) now both show the same pattern — GPT-4.1 F9 failures are rare
to the point of not occurring at all in 15 real pieces total (9 + 6) across two sessions.
That is more consistent with **"GPT-4.1 rarely fails F9 in the first place"** than with
either "converges better" or "converges worse" across repair rounds — the leniency
question AA-351-05 raised is reinforced, not resolved, by this data point.

## What actually held this run, and why it's not evidence either way

2 of 6 pieces held. **Neither held reason involves the judge model at all**:

- `slot_979cb5427fefac167325:blog` — held on **F1_grounding** (`sentence states ['63']
  not present in its cited id(s)`), unchanged across all 4 repair rounds. F1_grounding is
  a **deterministic** citation-matching check (`gate_grounding()`, gates.py:115,
  docstring literally says "F1 grounding (DET)") — it never calls `invoke_judge()`, so
  `JUDGE_MODEL` has zero effect on it. This is a real repair-convergence failure (4
  rounds, same exact violation text every time — the repair never fixed the citation gap)
  but it says nothing about GPT-4.1 vs Nova Pro.
- `slot_979cb5427fefac167325:blog#facebook` — held on **F8_framework: "ends with CTA"**,
  unchanged across rounds 2-4. Confirmed by reading `gate_framework()` (gates.py:530-543):
  `_ends_with_cta()` is a **deterministic pre-check evaluated before `invoke_judge()` is
  even called** — the violation text this piece got every round is this hard-coded
  string, not LLM output. `JUDGE_MODEL` doesn't touch this criterion either (the same
  piece's F9_brand_seo_audit_social passed clean both before and during the hold).

So both held pieces are real "same violation every round" non-convergence cases — exactly
the AA-382 *shape* of problem — but both are deterministic-gate failures, structurally
immune to which judge model is selected. This run had no case where an actual LLM judge
(F8's judge component or F9) failed more than once on the same piece to observe whether
GPT-4.1 re-flags a stable or a moving target.

## Real numbers

**Piece-level outcome (6 pieces, 2026 W2/month10):**

| piece | channel | status | repair_count | held_reason |
|---|---|---|---|---|
| slot_5216…:blog | blog | passed | 4 | — (F1_grounding→F5_atom_density→F5→F1, all eventually fixed) |
| slot_5216…:blog#facebook | facebook | passed | 0 | — (clean first try) |
| slot_5216…:blog#tiktok | tiktok | passed | 3 | — (F1_grounding fixed on round 3) |
| slot_979c…:blog | blog | **held** | 4 | F1_grounding (deterministic, unchanged 4 rounds) |
| slot_979c…:blog#facebook | facebook | **held** | 4 | F8_framework ends-with-CTA (deterministic, unchanged rounds 2-4) |
| slot_979c…:blog#tiktok | tiktok | passed | 1 | — |

**F8/F9 gate_ledger final state, all 6 pieces**: F9 6/6 pass (100%), F8 5/6 pass (the 1
failure is the deterministic sub-check above, not the judge's rubric scoring).

**Multi-round pass rate vs. AA-351-05's single-pass baseline**: not a fair comparison —
AA-351-05 was single-pass judging of ALREADY-HELD Nova Pro content, deliberately sampling
the pieces Nova Pro found hard (1/9 F9). This run judged NEW content through the real
pipeline, with real repair rounds available to fix whatever GPT-4.1 flagged — and it
flagged nothing on F9 to need fixing. Comparing 9/9 (AA-351-05, re-judge of known-hard
content) to 6/6 (this run, judge of typical fresh content) would overstate GPT-4.1's
apparent leniency gap; the honest read is both numbers independently show GPT-4.1 failing
F9 rarely, on two different content populations.

**Real GPT-4.1 cost this run** (from CloudWatch `/ecs/aa-cis-dev`, `judge_llm_success`
events, 17:41–17:49 UTC 16/08/2026 — real `usage` fields, not estimated):
- **44 real GPT-4.1 calls** (22× F8_framework + 22× F9_brand_seo_audit[_social]) — matches
  the expected count exactly: `run_gates()` re-runs the FULL gate stack every round (P0-3,
  "full re-run of every gate"), so both judge-gates fire on the initial pass AND every
  repair round regardless of which gate triggered that round. Sum of (1 + repair_count)
  across the 6 pieces × 2 judge-gates/piece = (5+1+4+5+5+2)×2 = 44. ✓
- **83,002 input tokens / 7,106 output tokens total**
- **Real cost: $0.2229** (at GPT-4.1's $2.00/1M in, $8.00/1M out rate card) — well inside
  the ~$5.03 remaining budget (AA-351-05 spent ≈$0.07 of the $5.10 grant; this run leaves
  ≈$4.80 available).
- **0 errors, 0 `judge unavailable` fallbacks** across all 44 calls.

**Run timing**: triggered 17:41:23 UTC, completed 17:48:40 UTC — ~7m17s for 2 slots/6
pieces (materially faster than the ~65min 9-12 piece Nova Pro runs in Run History, mostly
piece-count, not a judge-model latency claim).

## Method — how JUDGE_MODEL was set for one run only

**Architecture constraint discovered**: `JUDGE_MODEL` is read via `os.environ.get(...)`
inside `judge_client.py`, evaluated in the **same long-running ECS API process** that
`POST /admin/produce/run`'s `BackgroundTask` executes in (confirmed by reading
`api/routers/admin_produce.py` — N7 is not a one-off Fargate task, it runs inside the
already-running `aa-cis-dev-api` service). `RunRequest` has no per-request judge-model
override field. This ruled out the "no task-def touch" option the task prompt asked to
prefer first — there is no live way to set an env var for one in-process background job
without changing what the running container's process sees.

**What was done** (least-risky remaining option, as the task prompt allowed as fallback):
1. Registered `aa-cis-dev-api:107` = revision `:106` (the prior live revision) + one
   added env var, `JUDGE_MODEL=gpt41`. No other change.
2. `update-service` to `:107`, waited `services-stable`, confirmed `/health` 200.
3. Triggered the real run (`run_id 8fb78649-b37e-4448-883a-9a2230a67da0`).
4. Polled `GET /admin/produce/run/{run_id}` until `status=completed` (background poller,
   since the run takes several minutes and the run happens in the same container being
   toggled — reverting mid-run would have killed the in-flight `BackgroundTask`).
5. Immediately on completion, `update-service` back to `:106`, waited `services-stable`.

**Total window `JUDGE_MODEL=gpt41` was live in any ECS task**: ~9 minutes (registered
17:41 alongside the trigger, reverted 17:49 right after `status=completed`).

## Verify

1. **Confirmed reverted**: `aws ecs describe-services` shows the service back on
   `aa-cis-dev-api:106`, `running=1/desired=1`. `describe-task-definition :106`'s
   `environment` array has no `JUDGE_MODEL` key — byte-identical to before this task.
   Revision `:107` still exists as a registered task definition (harmless — ECS doesn't
   let you delete revisions, only stop using them) but is not referenced by the service.
2. **Cost**: $0.2229 real, verified via CloudWatch `judge_llm_success` log events with
   real `usage.prompt_tokens`/`usage.completion_tokens` — not estimated, not the stale
   "same as Nova Pro's numbers" bug AA-351-05 flagged in the older `aa351_compare.py`
   harness (this task read production's real log line instead of that harness).
3. **No code changes** — this task only touched an ECS task definition's environment
   array (registered as a new revision, then abandoned) and triggered/observed a real
   production API call. `git status` on the repo shows no diff from this task besides
   the two doc files.
4. This report + `docs/claude_tasks/AA-351-06-gpt41-multiround-real-n7.md`.

## Should know

- **Do not read "6/6 F9 pass" as "GPT-4.1 solves AA-382."** It is 6 pieces from one
  week's content, and — as the headline section says — the mechanism AA-382 is worried
  about (re-flagging a fixed sentence as a NEW violation next round) simply never got a
  chance to fire, because nothing failed F9 to begin with. A held/repaired F9 case is
  what the next real test needs, and this run didn't produce one.
- **A genuinely conclusive test of AA-382 would need either**: (a) several more real N7
  weeks under `JUDGE_MODEL=gpt41` until an actual F9 failure-and-repair sequence occurs
  (uncontrollable which week that'll be — content quality varies), or (b) a synthetic
  harness that deliberately feeds GPT-4.1 the SAME known-Nova-Pro-hard piece across
  simulated repair rounds (closer to what AA-351-05 did, but repeated ≥2 rounds instead
  of once) — cheaper and controllable, at the cost of not being "real" pipeline behavior.
  Neither was in this task's explicit scope (one real week, no more).
- **Both held pieces this run are real, unresolved 4-round non-convergence cases** — just
  not judge-related. `slot_979c…:blog`'s F1_grounding violation is textually identical
  from round 1 to round 4 (repair never touched the actual problem sentence); `…facebook`'s
  F8 CTA violation is identical rounds 2-4 for the same reason. Worth a separate look
  (repair.py's grounding-note guidance, `_build_grounding_note()`) but out of this task's
  scope — flagging so it isn't lost, not fixing it here.
- Production `JUDGE_MODEL` was never set on the actually-referenced task definition
  outside this ~9-minute window — `nova_pro` was the default before, during (only on the
  abandoned `:107` revision, never the default target), and after this task.

## Next steps (for Nghiep to decide)

1. **AA-382's core question remains open.** Two independent real-data sessions
   (AA-351-05's 9-piece single-pass, this task's 6-piece real multi-round) both show
   GPT-4.1 rarely/never failing F9 — this is evidence GPT-4.1 may be lenient on F9,
   not evidence it converges well or poorly under repair. Don't change the production
   `JUDGE_MODEL` default off the back of either result alone.
2. If resolving AA-382 for real matters before a production judge decision, the cheapest
   next step is the AA-351-05-style single-pass-repeated-N-times harness against a KNOWN
   Nova-Pro-hard piece (option (b) above) rather than more real N7 weeks — real weeks are
   giving 0% F9 failure rate for GPT-4.1 so far, so more of the same real-run approach may
   just burn OpenAI budget without new signal.
3. The two real 4-round non-convergent deterministic-gate holds found this run (F1
   grounding, F8 CTA) are unrelated tech debt worth their own look, not urgent.
