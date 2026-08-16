# AA-351-03 — GPT-4.1 as an alternative F8/F9 judge (trial, feature-flagged)

Task: `docs/claude_tasks/AA-351-03-gpt41-judge-f8-f9.md`. Branch
`feature/aa-351-gpt41-judge-trial`. Follows `docs/implementation-notes/AA-351-gpt56-judge-
trial.md` (AA-351-02, GPT-5.6 Sol — still blocked on AWS access as of this session).

## ⚠️ Headline finding — NOT what this trial set out to measure

**The OpenAI API key this app uses has zero credits.** Every real GPT-4.1 call this
session made — through the exact same client construction production already runs —
failed with `Error code: 429 - insufficient_quota / credit_balance_exhausted: "You have
no credits remaining."` This is not a bug in this trial's code (confirmed: the request
authenticated correctly — a wrong/invalid key gives a 401, not a 429 quota error — and
the 9 real gate calls all reached OpenAI and were rejected only for billing reasons).

**This means GPT-4.1 is currently non-functional everywhere in production it's used**,
not just in this trial:
- `services/content_generation/judge_node.py` — S1's brand-fit judge, called with
  `model_tier="gpt-4.1"` which `shared/llm_client/client.py::generate()` routes as
  **direct GPT-4.1, no Bedrock fallback** (`"Direct GPT-4.1 — no Bedrock fallback
  (explicit choice)"`, `client.py`'s own comment). Every real S1 pipeline run's
  brand-fit judge call is failing right now.
- The failure is **silent and non-blocking by design** (`judge_node.py`'s own
  docstring: *"Any failure is non-blocking: any GPT error or parse failure logs and
  leaves validate's quality_score untouched"*) — S1 content has been shipping without
  brand-fit judging, with only a `judge_failed_graceful` warning log line as evidence,
  since whenever the credits ran out (unknown from this session — not investigated,
  out of scope for this issue).
- `services/content_generation/brand_audit_node.py` and `services/acp_s4_social/
  llm_client.py` both also read `OPENAI_API_KEY` directly — same exposure, not
  individually re-verified this session (confirmed only by grep, not by triggering a
  real call).
- `shared/llm_client/client.py`'s T3 (GPT-4.1 last-resort fallback, used when both
  Bedrock Sonnet and Haiku — native and both satellites — fail) is also unusable until
  credits are restored, though T3 firing at all is already rare.

**This needs Nghiep's attention independent of the AA-351 judge trial** — recommend
adding credits at https://platform.openai.com/settings/organization/billing/ (the exact
URL OpenAI's own error message gives) as a priority ahead of any judge-model decision
below, since it's a live, silent quality-pipeline gap in production S1, not a trial
question.

## Decisions

- **Reused `judge_node.py`'s exact client construction, not `LLMClient.generate()`'s
  full T1-T3 chain.** `invoke_judge_gpt41()` calls `openai.OpenAI(api_key=os.environ.get
  ("OPENAI_API_KEY"))` directly — same SDK, same env var, same auth as production
  already runs for S1's judge. Deliberately NOT going through `LLMClient.generate
  (model_tier="gpt-4.1")`, because that class's `"gpt-4.1"` tier is designed as one
  option in a multi-tier fallback chain (or, for judge_node.py's own usage, a direct
  call with no Bedrock attempt) — this backend needs a single deterministic call every
  time it's selected, the same "no fallback, just this one backend" shape
  `invoke_judge_gpt56()` (AA-351-02) already established for its own satellite call.
  Consistent structural choice across all 3 alternative judge backends now in this file.
- **`temperature=0`**, matching the deterministic-judge convention both Nova Pro and
  GPT-5.6 already use (their `inferenceConfig.temperature: 0`) — OpenAI's Chat
  Completions API takes it as a top-level kwarg instead of a nested config object.
- **Extended (not rewrote) `aa351_compare.py`.** Added one env var, `COMPARE_MODELS`
  (comma-separated, e.g. `nova_pro,gpt41`) — unset preserves the exact original
  hardcoded `["nova_pro", "gpt56"]` behavior byte-for-byte, so AA-351-02's own
  reproducibility isn't disturbed. Output S3 key also branches on this (
  `aa351_compare_results_<models>.json`) so this run's output never overwrote
  AA-351-02's original `aa351_compare_results.json`.
- **Real cost impact of this trial's failed calls: effectively $0.** OpenAI does not
  bill for a request rejected at the quota-check stage before any tokens are
  generated — confirmed by the harness's own captured `input_tokens`/`output_tokens`
  fields being stale (see "Known harness limitation" below), which is itself consistent
  with the call never reaching generation.

## Changed

1. `services/acp_produce/judge_client.py`
   - `invoke_judge()`'s `model` routing extended: `model == "gpt41"` now routes to the
     new `invoke_judge_gpt41()`. `"gpt56"` and the Nova Pro default are both completely
     untouched — confirmed by a dedicated regression test (see below).
   - New `invoke_judge_gpt41()` — direct OpenAI API call, GPT-4.1, same
     `{text, model_used, provider, input_tokens, output_tokens}` return shape the other
     two backends use, so `gates.py`'s parsing code needs zero changes for any of the 3
     backends.
   - New constant `GPT41_MODEL = "gpt-4.1"`.
2. `tests/unit/test_aa351_judge_gpt41.py` (new) — 7 tests: default-stays-Nova-Pro,
   explicit `model=`/env var routing to gpt41, a regression check that gpt56 routing
   still works unaffected by the new branch, direct-OpenAI-not-Bedrock assertion,
   usage/text parsing, and the same "never imports generation/writer modules"
   structural isolation re-check (ADR-2026-014/027 L3) AA-351-02 already established the
   pattern for.
3. `docs/claude_tasks/AA-351-03-gpt41-judge-f8-f9.md` (new) — task prompt, committed
   first per the Implementation Notes Pattern.
4. `s3://aa-cis-bronze-005097885195/scripts/aa351_compare.py` — extended with
   `COMPARE_MODELS` (see Decisions above). Not part of this repo's git history (same as
   AA-351-02's original upload) — a throwaway ops harness, not a deployed app module.

**Not changed**: `gates.py` (all 3 call sites), `pipeline.py`, `repair.py`, the F8/F9
rubric content, `_JUDGE_SYSTEM_PROMPT`, `FRAMEWORK_RUBRICS`, `BRAND_SEO_FAILURE_CODES`,
`GENERIC_AI_WORDING_ANCHOR`, and `invoke_judge_gpt56()` — nothing about what gets judged
or how changed, only which model can optionally do the judging.

## Real run — what happened

Ran the extended `aa351_compare.py` (`COMPARE_MODELS=nova_pro,gpt41`) against the exact
same 9 real pieces from run `88f094b1-3e0a-4b28-9abb-205cb7d21287` (2026 W2) AA-351-02
used for its Nova Pro baseline — same read-only re-judge-via-real-gate-functions
methodology, no new N7 run, no writer cost. Executed via the S3-mediated ECS exec +
daemonize pattern (interactive SSM sessions reliably drop mid-run, per
`ecs-exec-long-sync-daemonize` — same as AA-351-02 hit).

**Nova Pro side: reproduced cleanly, consistent with AA-351-02's original numbers**
(same run, same content, same gate functions — expected to match exactly): F9 1/9 pass,
F8 5/6 pass (facebook+tiktok subset).

**GPT-4.1 side: 0/9 real judge calls succeeded** — all 9 pieces' `f9_gpt41` (and 6/6
`f8_gpt41`) came back as `{"passed": false, "violations": ["judge unavailable: Error
code: 429 - ...insufficient_quota...credit_balance_exhausted... — manual check"]}`. This
IS the correct, intended graceful-degradation behavior (`gates.py`'s existing
`except Exception as e: violations.append(f"judge unavailable: {e} — manual check")`) —
confirms the new backend's error handling integrates correctly with the real gate
functions, even though it produced no usable comparison data.

**Known harness limitation, found and left as-is (not worth fixing for a script that
produced no usable data to salvage):** the compare script's `_wrapped()` timing/token
capture (`_last_call` dict) only updates on a SUCCESSFUL `invoke_judge()` return — an
exception path (every gpt41 call here) leaves `_last_call` holding the PREVIOUS
successful call's stats, so the `latency_s`/`input_tokens`/`output_tokens` fields under
every `f9_gpt41`/`f8_gpt41` entry in the results JSON are actually stale copies of that
piece's own `f9_nova_pro` numbers, not real GPT-4.1 numbers (there are none — the calls
never got token-billed). Flagging this so nobody later reads those fields as real GPT-4.1
latency data.

## Comparison table — all 3 alternative judge backends

| | Nova Pro (production default) | GPT-5.6 Sol (AA-351-02) | GPT-4.1 (AA-351-03, this session) |
|---|---|---|---|
| **Status** | ✅ real data (2 independent runs, same numbers) | ⚠️ blocked — AWS access denied ~1h+ after agreement accepted + console-confirmed Active (AA-351-04 recheck) | ⚠️ blocked — OpenAI account has 0 credits |
| **F9 pass rate** (9 channels) | 1/9 (11%) | not measured | not measured (0/9 calls succeeded) |
| **F8 pass rate** (fb+tiktok, 6 channels) | 5/6 (83%) | not measured | not measured (0/6 calls succeeded) |
| **held_reason consistency** (AA-382's core question) | not yet re-tested across repair rounds in this trial | not measured | not measured |
| **Real latency/call** | 0.8–3.1s (measured, see AA-351-02's table) | not measured | not measured (calls rejected before generation) |
| **Real cost** (per real rate cards, verified not guessed) | ~$0.80/1M in, $3.20/1M out (AA-404 CloudWatch-derived) | $5.50/1M in, $33/1M out (Sol, standard tier, accepted rate card) — ~6x Nova Pro | $2.00/1M in, $8.00/1M out (verified 16/08/2026 via web search — matches this repo's own `client.py::COST_TABLE["gpt-4.1"]` exactly) — ~2.5x Nova Pro on paper, but $0 actually spent this session (every call rejected pre-billing) |
| **Blocker type** | none | AWS-side (Bedrock model-access authorization gap, console/runtime state mismatch — see AA-351-02's evidence block for an AWS Support case) | Billing (OpenAI org has zero credits — a Nghiep action, not an AWS/code issue) |
| **Next unblock step** | n/a | File AWS Support case (evidence already collected in AA-351-02's notes) | Add credits at platform.openai.com/settings/organization/billing |

**Net result: still only 1 real comparison point (Nova Pro) after 2 trial sessions.**
Both alternative backends are code-complete, unit-tested, and feature-flagged behind
`JUDGE_MODEL` — ready to produce real numbers the moment either external blocker
(AWS access / OpenAI billing) clears, with no further code changes needed.

## Verify

1. `pytest tests/unit/ -q` → **1347 passed** (was 1338 after AA-351-02; +7 new AA-351-03
   `gpt41` tests, plus the existing gpt56/Nova Pro tests all still pass unaffected). 0
   regressions. `flake8` clean on all changed files.
2. Comparison table above — GPT-5.6 column still pending (unchanged from AA-351-02);
   GPT-4.1 column attempted for real, blocked on billing, documented rather than
   fabricated.
3. Not deployed to Dev this session — feature-flagged, zero production risk either way,
   and there was no real comparison data to validate live against. Will deploy as part
   of normal PR merge; nothing about this change needs an isolated live-verify step
   beyond the unit tests (same reasoning AA-351-02 used for merging its own PR #173
   without deploying separately).
4. This report.

## Should know

- No production behavior changed by this PR — `JUDGE_MODEL` is still not set in the ECS
  task definition; every `gates.py` call site still defaults to Nova Pro exactly as
  before AA-351 started.
- The Dev ECS container's on-disk `judge_client.py` was temporarily overwritten (same
  S3-mediated exec pattern AA-351-02 used) to run this trial against the real acc2/OpenAI
  paths without deploying an unmerged branch — does not persist past the next real
  deploy, same caveat AA-351-02's notes already gave.
- `openai` package import happens inside the function (`import openai` inside
  `invoke_judge_gpt41()`), matching `invoke_judge_gpt56()`'s equivalent inline import of
  `get_satellite_client` — neither pulls its extra dependency into `judge_client.py`'s
  module-level import graph unless that specific backend is actually selected.

## Next steps (for Nghiep to decide — not done here)

1. **Add OpenAI credits** (see headline finding above) — this is the actual blocker on
   BOTH this trial's GPT-4.1 data AND a live, currently-silent gap in S1's production
   brand-fit judging. Recommend treating this with more urgency than the trial itself.
2. **Once credits are added**: re-run the already-uploaded, already-extended
   `aa351_compare.py` on the ECS Dev container with `COMPARE_MODELS=nova_pro,gpt41` (same
   S3-mediated exec + daemonize pattern documented here and in AA-351-02) — no code
   changes needed, just credits + a re-trigger. I can do this the moment credits exist.
3. **GPT-5.6 Sol** — still blocked on the AWS-side issue AA-351-02/04 already documented
   in detail; that path is unrelated to this session's OpenAI finding.
4. **Do not change the production `JUDGE_MODEL` default** regardless of what any future
   comparison shows — reserved for Nghiep, unchanged from AA-351-02's own constraint.
