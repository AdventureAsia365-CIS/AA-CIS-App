# AA-416 — fix event loop blocking bằng asyncio.to_thread

Task: `docs/claude_tasks/AA-416-01-fix-event-loop-blocking.md`. Branch: `feature/aa-416-
async-to-thread-bedrock`, off `main` @ `4092933`. Implemented 16/08/2026.

## Decisions

- **Wrap at the async/sync BOUNDARY (5 call sites), not inside every helper function.**
  `invoke_claude()`/`invoke_judge()` are called from deep inside a chain of plain
  synchronous functions (`_invoke_sonnet_with_retry`, `_invoke_channel_with_retry`,
  `repair_piece`, `gate_framework`, `gate_brand_seo_audit(_social)`, `run_gates`,
  `build_gap_statement` — none of them `async def`). `asyncio.to_thread()` returns an
  awaitable, so it can only be called from `async def` code — converting every one of
  those ~10 sync functions across 5 files (gates.py/generation.py/adapt.py/faq.py/
  repair.py) to `async def` would be a much larger, riskier refactor for the same
  outcome. Instead, each of the 5 places where an `async def` function calls straight
  into that sync call graph is wrapped in `await asyncio.to_thread(sync_fn, *args)` —
  every Bedrock call inside still ends up running on a worker thread, never the event
  loop thread, exactly satisfying the task's goal ("bọc các lệnh gọi Bedrock đồng bộ
  trong thread pool riêng") with a 4-file, ~25-line diff instead of a sprawling one.
- **The 5 call sites** (identified by tracing every `async def` -> sync call graph that
  reaches `invoke_claude`/`invoke_judge`, confirmed exhaustively via `grep` — see
  "Changed" below for the full list including one (`research.py`'s C3 gap statement)
  that isn't named in the task's E2/E5/F8/F9 list but is a real sync Bedrock call inside
  the async N7 path, so it's fixed too for completeness ("không bỏ sót điểm nào").
- **`shared/llm_client/client.py` (`LLMClient.generate()`) is untouched** — confirmed by
  grep that N7 (`services/acp_produce/*`) never imports or calls it; it's the S1-S4
  pipeline's client, a different call path entirely. Read per the task's file list, not
  modified — out of scope for this issue.
- **No retry/timeout logic changed anywhere** — `_MAX_INVOKE_ATTEMPTS` loops,
  `time.sleep()` backoff, `BedrockUnavailable` exception handling all execute exactly as
  before, just now inside a worker thread instead of the event loop thread.

## Changed

1. `services/acp_produce/research.py::compile_brief()` — `build_gap_statement(...)` (C3
   gap statement, `invoke_claude(model="haiku")`) now `await asyncio.to_thread(...)`.
2. `services/acp_produce/slot_runner.py::run_slot_production()` — 3 call sites:
   - `generate_draft(...)` (E2 draft, `invoke_claude(model="sonnet")`)
   - `adapt_channels(...)` (E3 adapt, up to 2 `invoke_claude` calls — facebook/tiktok)
   - `apply_faq(...)` (E4 FAQ, `invoke_claude(model="sonnet")`)
   All 3 now `await asyncio.to_thread(...)`; existing `try/except DraftGenerationFailed`/
   `FAQAnswerFailed` blocks are unchanged and still work — exceptions raised inside a
   `to_thread`-run function propagate through the awaited call exactly as if it had been
   called directly.
3. `services/acp_produce/pipeline.py::run_piece_through_produce_gates()` — the big one:
   `run_gates(piece, [_f1, _f5, _f2, _f3, _f4, _f6, _f7, _f8, _f9], _repair, ...)` now
   `await asyncio.to_thread(run_gates, piece, [...], _repair, ...)`. This is the dominant
   real-world offender — `run_gates()`'s `while True` loop can call `invoke_judge()`
   (F8/F9) every round AND `repair_piece()` -> `invoke_claude()` (E5) up to
   `repair_budget` times (real measured single-call latency: 13.8s,
   `docs/claude_audit/AA-418-parallel-cost-investigation.md`; up to `REPAIR_BUDGET_CAP`
   rounds per piece) — before this fix, ALL of that ran bare, blocking the whole event
   loop for the full duration, every round.
4. New test file `tests/unit/test_aa416_event_loop_not_blocked.py` — 2 tests:
   - Positive: `await asyncio.to_thread(run_gates, ...)` (the fixed shape) running
     concurrently with a polling "health check" coroutine — asserts the health-check
     latency stays under 50ms throughout a simulated 0.5s blocking repair call.
   - Negative control: the bare (pre-fix) call shape — asserts the health-check
     coroutine gets literally zero chance to run until the blocking call finishes
     (proves the positive test is exercising a real difference, not a no-op).

## Tradeoffs

- **Thread-per-call, not connection pooling of threads** — `asyncio.to_thread()` uses
  the loop's default `ThreadPoolExecutor` (stdlib default sizing,
  `min(32, os.cpu_count() + 4)`), shared process-wide with anything else that calls
  `asyncio.to_thread`/`loop.run_in_executor(None, ...)`. Not tuned/sized specially for
  N7 — default sizing is more than sufficient given the piece loop stays sequential (see
  next point), so this wasn't worth the complexity of a dedicated executor.
- **Deliberately did NOT add concurrency (no `asyncio.gather()`).** The piece loop in
  `slot_runner.py` (`for piece in [...]: result = await run_piece_through_produce_gates
  (...)`) stays exactly as sequential as before — one `await` per piece, each fully
  resolving before the next starts. `docs/claude_audit/AA-418-parallel-cost-
  investigation.md` (16/08/2026, same day) already investigated piece-level parallelism
  separately and found it unsafe today for unrelated reasons (shared `asyncpg.Connection`
  not thread-safe for concurrent use across pieces, acc3 Bedrock RPM quota unverified) —
  fixing those is explicitly out of scope for AA-416, which is a blocking-call fix, not a
  throughput fix. Runtime for one piece's full gate+repair loop is unchanged by this fix
  (still fully serial internally) — only the identity of the thread it runs on changed.
- **Thread-safety of the shared boto3 `Session` cache** (`shared/llm_client/
  bedrock_satellite.py`'s `_cached_sessions` dict, module-level): confirmed low risk, not
  zero. Each `invoke_claude()`/`invoke_judge()` call creates its own `boto3.client(...)`
  fresh (never a shared mutable client object across calls) — only the underlying
  `boto3.Session` object is cached/shared. Because the piece loop stays sequential (see
  above), this fix does NOT introduce any NEW concurrent access to that cache — at most
  one N7-originated thread is ever active in `invoke_claude`/`invoke_judge` at a time.
  Other concurrent admin traffic hitting the same satellite functions was already
  possible before this fix (FastAPI's own sync-route thread pool) and is unchanged by
  it. If piece-level concurrency is added later (AA-418's separate, deferred
  investigation), this assumption needs re-checking — flagging here rather than
  re-deriving it then.

## Should know

- **`/health` (`api/main.py:297`) is `async def health()`, zero I/O** — confirmed by
  reading the route directly. It shares the exact same single-threaded event loop as
  `_produce_slots_background` (`api/routers/admin_produce.py`, added via FastAPI's
  `BackgroundTasks.add_task()`, which runs on the same loop, not a separate thread/
  process) on this ECS service's one running task (`desired=1`). This is the precise
  mechanism the task described: any synchronous blocking call anywhere in N7's call
  graph stalls `/health` for its full duration, which is what caused the real, repeated
  ALB health-check timeouts (`docs/claude_audit/AA-404-n7-run6-results.md`,
  `AA-418-parallel-cost-investigation.md`).
- **Cost is unchanged**, as the task predicted — Bedrock bills by token, not by which
  thread issued the HTTP call; nothing about the request/model/retry logic changed.
- **`kirocli/`** (untracked dir in the repo root, present before this session started,
  unrelated CLI tool) was left untouched — not created by this work, not part of this
  diff.
- **AA-351-02 (parallel session, GPT-5.6 judge trial) work found uncommitted on this
  session's PRIOR branch** at the start of this task — preserved separately (not part of
  this diff): `docs: AA-404 LLM cost investigation` pushed straight to `main` (docs-only,
  matches this repo's established pattern for such notes), and `feat: AA-351 add GPT-5.6
  Sol as feature-flagged judge backend` opened as PR #173 (not merged). No file overlap
  occurred between that work and this fix — AA-351-02 touched
  `services/acp_produce/judge_client.py` (adds `invoke_judge_gpt56()`, a new function);
  this fix touches the 3 files listed above and never modified `judge_client.py` — the
  git-pull-before-push collision the task warned about didn't materialize, confirmed by
  `git fetch origin` showing `origin/main` unchanged since this branch was created.

## Verify — status

1. **Unit tests: DONE, clean.** `pytest tests/unit/ -q` → **1333 passed** (was 1331
   before this change; +2 new AA-416 tests), 0 failures. Includes the full
   `services/acp_produce/*` suite (248 tests) unaffected by the call-site changes.
2. **Load test (simulated): DONE, in `tests/unit/test_aa416_event_loop_not_blocked.py`.**
   Real asyncio event loop, a synchronous mock repair function that blocks for 0.5s
   (standing in for the real 13.8s `invoke_claude()` latency, shortened for test speed),
   run through the EXACT fixed call shape (`await asyncio.to_thread(run_gates, ...)`)
   concurrently with a polling health-check coroutine on the same loop:
   - **Fixed shape: health-check latency stayed under 50ms throughout the 0.5s blocking
     call** (test asserts `max(health_latencies) < 0.05`, passes).
   - **Negative control (bare, pre-fix call shape): the health-check coroutine got zero
     chance to run until the full 0.5s had elapsed** (test asserts this, passes) —
     confirms the positive test is exercising a real difference in event-loop behavior,
     not a no-op.
3. **Real N7 week run against live ECS: PENDING — deploy is live, run not yet triggered.**
   PR #174 merged (squash, commit `50f40ff`) 16/08/2026 on Nghiep's explicit go-ahead
   ("ci green thì merge luôn") once all 5 required checks passed. `Deploy Dev` (a real
   dedicated pipeline does still exist for this repo, run
   [31957253331](https://github.com/AdventureAsia365-CIS/AA-CIS-App/actions/runs/31957253331))
   ran automatically on the push to `main` and completed clean: ECR build+push, ECS
   deploy (`Wait stable` + `Smoke test` both passed), Lambda deploy, Vercel deploy hook —
   all 4 jobs green. Confirmed live:
   - `aws ecs describe-services`: task def `aa-cis-dev-api:104`, rollout `COMPLETED`,
     desired=1/running=1.
   - Running task's container image digest (`aws ecs describe-tasks`) —
     `sha256:424d2fb...ea59bb6` — matches `aws ecr describe-images --image-ids
     imageTag=latest` EXACTLY, tagged `dev-50f40ff1f69c...` (the merge commit hash) —
     confirms the deployed build really is this fix, not a stale image.
   - `curl https://api-cis.lumiguides.it.com/health` → `200 {"status":"ok",...}` in
     0.76s, task `healthStatus=HEALTHY`.
   The fix is live in Dev. What's NOT yet done: actually triggering a real N7 week run
   against this build and watching ALB health-check/ECS task stability throughout (the
   task's original step 3) — that's a real, paid, ~30-40 min Bedrock run and wasn't part
   of what this session's merge-and-monitor instruction covered. Flagging as the next
   action rather than assuming it should run unprompted.
4. **CI / deploy digest check: DONE** — see the ECR/ECS digest match above.

## Next step for Nghiep

Fix is merged and deployed to Dev, verified live (digest match + healthy task + working
`/health`). The one remaining verify step from the original task is triggering a real,
not-yet-run N7 week (check Run History first) and watching for ALB timeouts throughout —
say the word and I'll run it, or you can trigger it yourself and I'll watch CloudWatch/
ECS alongside.
