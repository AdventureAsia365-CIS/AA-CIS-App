"""
tests/unit/test_aa416_event_loop_not_blocked.py — AA-416 regression: the N7
gate+repair loop must not block the shared ECS-task event loop.

Root cause (docs/claude_audit/AA-418-parallel-cost-investigation.md, confirmed
real: one E5 repair call measured latency_ms=13790.6): `run_gates()`
(services/acp_produce/gates.py) is a synchronous function whose repair path
calls `repair_piece()` -> `invoke_claude()` (sync boto3, blocking) and whose
F8/F9 gates call `invoke_judge()` (same). Before AA-416, `pipeline.py::
run_piece_through_produce_gates()` called `run_gates()` bare, with no
`await`/`to_thread` -- so that whole blocking call ran directly on the
asyncio event loop this ECS task shares with `/health` (api/main.py) and all
other API-serving traffic, causing the real, repeated ALB health-check
timeouts this issue fixes.

This test does NOT re-verify `run_gates()`'s own repair-loop logic (that's
gates.py's own test suite, e.g. test_aa376_repair_loop.py) -- it verifies the
EXECUTION MECHANISM: that a slow, synchronous repair_fn (standing in for a
real invoke_claude() call) does not stall a concurrently-running "health
check" coroutine on the same event loop, exactly reproducing the shape of
`pipeline.py`'s real call site (`await asyncio.to_thread(run_gates, ...)`).
"""
import asyncio
import time

import pytest

from services.acp_produce.gates import run_gates
from services.acp_produce.models import GateResult, Piece

# Stands in for one real invoke_claude()/invoke_judge() call's measured
# latency order of magnitude (13.8s real, docs/claude_audit/AA-418-...md) --
# shortened for test speed, still long enough that a blocked event loop would
# make a concurrent health-check coroutine's response time balloon by
# roughly this amount if the fix were absent.
_SIMULATED_BEDROCK_LATENCY_SECONDS = 0.5
_HEALTH_CHECK_MAX_LATENCY_SECONDS = 0.05  # generous margin over normal asyncio scheduling jitter


def _one_failure_then_pass_gate():
    """Fails the FIRST time it's called (triggering exactly one repair
    round), passes every call after -- mirrors a real gate whose one
    violation `repair_piece()` successfully fixes on round 1."""
    calls = {"n": 0}

    def _gate(body: str) -> GateResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return GateResult(gate="F1_grounding", passed=False, violations=["needs repair"])
        return GateResult(gate="F1_grounding", passed=True)

    return _gate


def _slow_sync_repair_fn(body: str, violations: list[str]) -> str:
    """Synchronous, blocking -- exactly the shape of the real
    `repair.py::repair_piece()` (which calls the synchronous
    `bedrock_satellite.invoke_claude()`, boto3, blocking HTTP call)."""
    time.sleep(_SIMULATED_BEDROCK_LATENCY_SECONDS)
    return "repaired body"


async def _fake_health_check() -> dict:
    """Exactly as cheap as the real api/main.py::health() -- no I/O, just
    returns a dict. On an event loop that is NOT blocked, this resolves in
    microseconds regardless of what else is running concurrently."""
    return {"status": "ok"}


@pytest.mark.asyncio
async def test_run_gates_via_to_thread_does_not_block_concurrent_health_check():
    """Reproduces pipeline.py's real AA-416 call site: `await asyncio.to_thread
    (run_gates, ...)` running concurrently with a health-check coroutine on
    the same event loop. The health check's response latency must stay near-
    instant throughout -- proving the fix (before AA-416, the equivalent bare
    call in the second test below stalls it by the full sleep duration)."""
    piece = Piece(piece_id="test:blog", body_tagged="original body", channel="blog")
    gate_fns = [_one_failure_then_pass_gate()]

    health_latencies: list[float] = []
    stop = asyncio.Event()

    async def _poll_health():
        while not stop.is_set():
            t0 = time.monotonic()
            await _fake_health_check()
            health_latencies.append(time.monotonic() - t0)
            await asyncio.sleep(0.01)

    poller = asyncio.create_task(_poll_health())

    t_start = time.monotonic()
    # This is the exact fixed call shape (pipeline.py::run_piece_through_produce_gates()).
    result = await asyncio.to_thread(run_gates, piece, gate_fns, _slow_sync_repair_fn, max_repairs=3)
    elapsed = time.monotonic() - t_start

    stop.set()
    await poller

    assert result.status == "passed"
    assert elapsed >= _SIMULATED_BEDROCK_LATENCY_SECONDS  # the repair really did take the slow path
    assert health_latencies, "health poller never got a chance to run concurrently"
    assert max(health_latencies) < _HEALTH_CHECK_MAX_LATENCY_SECONDS, (
        f"health check latency spiked to {max(health_latencies):.3f}s while run_gates() was "
        f"running in its worker thread -- the event loop was blocked, the AA-416 fix regressed"
    )


@pytest.mark.asyncio
async def test_bare_run_gates_call_WOULD_block_health_check_pre_aa416_shape():
    """Negative control: calling `run_gates()` bare (the pre-AA-416 shape,
    no `to_thread`) DOES starve a concurrently-scheduled health-check
    coroutine of any chance to run until the whole blocking call finishes --
    proving the test above is actually exercising the mechanism this issue
    fixes, not a no-op. Measures wall-clock time until the health-check
    coroutine gets to run at all (not its own execution time, which is
    microseconds either way) -- a blocked event loop can't even start it
    until the synchronous call yields control back."""
    piece = Piece(piece_id="test:blog", body_tagged="original body", channel="blog")
    gate_fns = [_one_failure_then_pass_gate()]

    t_test_start = time.monotonic()
    time_health_check_ran: list[float] = []

    async def _poll_health_once_after_yield():
        await asyncio.sleep(0)  # give the event loop one chance to schedule this
        await _fake_health_check()
        time_health_check_ran.append(time.monotonic() - t_test_start)

    poller = asyncio.ensure_future(_poll_health_once_after_yield())
    # Pre-AA-416 shape: bare synchronous call, no await/to_thread -- monopolizes the event
    # loop's single thread for the sleep duration, so `poller` above cannot run AT ALL
    # (not even its first `await asyncio.sleep(0)`) until this line returns.
    run_gates(piece, gate_fns, _slow_sync_repair_fn, max_repairs=3)
    await poller

    assert time_health_check_ran[0] >= _SIMULATED_BEDROCK_LATENCY_SECONDS * 0.9, (
        f"expected the bare (unfixed) call shape to starve the concurrent health-check "
        f"coroutine of any chance to run until ~{_SIMULATED_BEDROCK_LATENCY_SECONDS}s had "
        f"passed (it ran at t={time_health_check_ran[0]:.3f}s) -- if this assertion fails, the "
        f"negative control itself is broken and the positive test above proves nothing"
    )
