"""
tests/unit/test_aa396_repair_budget.py — services/acp_produce/gates.py::
compute_repair_budget() + run_gates() (AA-396 follow-up, option C: dynamic
repair budget scaled to how many gates are failing when a piece's repair
loop starts).

Piece-1-shaped fixture below reconstructs the real failing-gate SET (not the
body text) of slot_b09166b7f2fdc28c87fd:blog from docs/implementation-notes/
AA-391-report-data.json (aa394_followup_test) — F3+F4+F8+F9 all failing at
once, the real case that motivated this fix (3 rounds could fix at most 3 of
4 simultaneous failures under the old flat REPAIR_TOTAL_MAX=3 budget).
"""
from unittest.mock import MagicMock

from services.acp_produce.gates import REPAIR_BUDGET_CAP, REPAIR_TOTAL_MAX, compute_repair_budget, run_gates
from services.acp_produce.models import GateResult, Piece


# ── compute_repair_budget(): pure function ──

def test_compute_repair_budget_single_failure_is_unchanged_base():
    assert compute_repair_budget(1) == REPAIR_TOTAL_MAX == 3


def test_compute_repair_budget_zero_failures_is_base():
    """A piece that never fails a gate never repairs, but the formula must
    not go negative/below base for a 0 count."""
    assert compute_repair_budget(0) == REPAIR_TOTAL_MAX == 3


def test_compute_repair_budget_piece1_shaped_four_simultaneous_failures():
    """Real piece-1 shape: F3+F4+F8+F9 = 4 simultaneous failures ->
    base(3) + (4-1) = 6."""
    assert compute_repair_budget(4) == 6


def test_compute_repair_budget_cap_enforced_for_pathological_case():
    """8 simultaneous failures would be base(3) + 7 = 10 under the raw
    formula -- REPAIR_BUDGET_CAP (8) must clip it, not let it grow
    unbounded."""
    assert compute_repair_budget(8) == REPAIR_BUDGET_CAP == 8
    assert compute_repair_budget(100) == REPAIR_BUDGET_CAP == 8


# ── run_gates(): 1 failing gate -> budget unchanged from today ──

def _fake_gate(name: str, marker: str):
    def _gate(body: str) -> GateResult:
        passed = marker not in body
        return GateResult(gate=name, passed=passed, violations=[] if passed else [f"{name} failed"])
    return _gate


def test_run_gates_single_failing_gate_gets_base_budget_unchanged():
    piece = Piece(piece_id="single", body_tagged="BAD_F1")
    repair_fn = MagicMock(return_value="BAD_F1")  # never fixes -- exhaust budget

    result = run_gates(piece, [_fake_gate("F1_grounding", "BAD_F1")], repair_fn)

    assert result.status == "held"
    assert result.initial_failing_gate_count == 1
    assert result.repair_budget == REPAIR_TOTAL_MAX == 3
    assert result.repair_count == 3
    assert repair_fn.call_count == 3


# ── run_gates(): piece-1-shaped 4 simultaneous failures -> scaled budget + convergence ──

def test_run_gates_four_simultaneous_failures_gets_scaled_budget_and_converges():
    """Piece-1-shaped: starts with F3+F4+F8+F9 all failing (4 simultaneous).
    Mocked repair_fn fixes exactly one marker per call, in the order
    run_gates() targets gates (gate_fns declaration order) -- proves the
    computed budget (6) is both correct AND sufficient for the piece to
    actually reach 'passed' within it, one gate fixed per round."""
    body0 = "BAD_F3 BAD_F4 BAD_F8 BAD_F9"
    gate_fns = [
        _fake_gate("F3_structural_variance", "BAD_F3"),
        _fake_gate("F4_brief_compliance", "BAD_F4"),
        _fake_gate("F8_framework", "BAD_F8"),
        _fake_gate("F9_brand_seo_audit", "BAD_F9"),
    ]
    piece = Piece(piece_id="piece1shaped", body_tagged=body0)
    repair_fn = MagicMock(side_effect=[
        "BAD_F4 BAD_F8 BAD_F9",       # round 1: fixes F3 (first-failing, gate_fns order)
        "BAD_F8 BAD_F9",              # round 2: fixes F4
        "BAD_F9",                     # round 3: fixes F8
        "",                           # round 4: fixes F9 -- all clean
    ])

    result = run_gates(piece, gate_fns, repair_fn)

    assert result.initial_failing_gate_count == 4
    assert result.repair_budget == 6  # base(3) + (4 - 1)
    assert result.status == "passed"
    assert result.repair_count == 4  # converged within the scaled budget (6), not the old flat 3
    assert repair_fn.call_count == 4

    # per-round repair_log matches the real gate order the fix targeted
    targeted_order = [r.gate_targeted for r in result.repair_log]
    assert targeted_order == [
        "F3_structural_variance", "F4_brief_compliance", "F8_framework", "F9_brand_seo_audit",
    ]
    assert all(r.outcome == "passed" for r in result.repair_log)


def test_run_gates_four_simultaneous_failures_would_have_starved_old_flat_budget():
    """Sanity check the premise itself: under the OLD flat max_repairs=3,
    the piece-1-shaped scenario above could not have converged (needs 4
    rounds, one gate fixed per round) -- confirms the fix is load-bearing,
    not just a formula that happens to agree with the old behavior."""
    assert REPAIR_TOTAL_MAX < 4


# ── run_gates(): cap enforced for a pathological 6+ simultaneous-failure case ──

def test_run_gates_cap_enforced_when_repairs_never_succeed():
    """8 simultaneous failing gates, repair_fn never fixes anything -- the
    computed budget must be clipped to REPAIR_BUDGET_CAP (8), not
    base(3) + 7 = 10, so a pathological piece can't spend unbounded Sonnet
    calls."""
    names = [f"F{i}_fake" for i in range(8)]
    markers = [f"BAD_{i}" for i in range(8)]
    body0 = " ".join(markers)
    gate_fns = [_fake_gate(n, m) for n, m in zip(names, markers)]
    piece = Piece(piece_id="pathological", body_tagged=body0)
    repair_fn = MagicMock(return_value=body0)  # never fixes anything

    result = run_gates(piece, gate_fns, repair_fn)

    assert result.initial_failing_gate_count == 8
    assert result.repair_budget == REPAIR_BUDGET_CAP == 8
    assert result.status == "held"
    assert result.repair_count == REPAIR_BUDGET_CAP == 8
    assert repair_fn.call_count == REPAIR_BUDGET_CAP == 8


# ── repair_log / summary bookkeeping ──

def test_run_gates_repair_log_records_exception_outcome():
    piece = Piece(piece_id="exc", body_tagged="BAD_F1")
    repair_fn = MagicMock(side_effect=RuntimeError("Sonnet exhausted"))

    result = run_gates(piece, [_fake_gate("F1_grounding", "BAD_F1")], repair_fn)

    assert result.status == "held"
    assert len(result.repair_log) == 1
    assert result.repair_log[0].outcome == "exception"
    assert result.repair_log[0].gate_targeted == "F1_grounding"


def test_run_gates_clean_body_never_calls_repair_and_still_sets_budget_fields():
    piece = Piece(piece_id="clean", body_tagged="all good")
    repair_fn = MagicMock()

    result = run_gates(piece, [_fake_gate("F1_grounding", "BAD_F1")], repair_fn)

    assert result.status == "passed"
    assert result.initial_failing_gate_count == 0
    assert result.repair_budget == REPAIR_TOTAL_MAX
    assert result.repair_log == []
    repair_fn.assert_not_called()


# ── run_gates(): AA-415 — late-discovered gate gets +1 budget headroom ──
#
# Real shape (docs/implementation-notes/AA-415-verify-real-run.md, run
# `363f22c9:slot_efb6c6d175e23bad4767:blog#tiktok`): initial_failing_gate_count=1
# (only F9_brand_seo_audit_social) -> repair_budget=3. Rounds 1-2 target F9.
# F1_grounding -- passing on the FIRST gate-stack run -- starts failing for
# the first time only after those F9 rounds (a real side effect of the F9
# repair rewrite), leaving exactly 1 round of the ORIGINAL budget for it,
# which failed. gate_fns order below matches the real stack (F1 checked
# before F9), so F1 becomes `first_failure` the moment it starts failing,
# regardless of F9's own state.

def test_run_gates_late_discovered_gate_extends_budget_and_can_converge():
    """F9 repair's 2nd attempt (mocked) fixes F9 but introduces F1 as a real
    side effect -- proves the +1 extension is what lets the piece actually
    reach 'passed' within budget, not just avoid a crash."""
    gate_fns = [
        _fake_gate("F1_grounding", "BAD_F1"),
        _fake_gate("F9_brand_seo_audit", "BAD_F9"),
    ]
    piece = Piece(piece_id="late-gate-converges", body_tagged="BAD_F9")
    repair_fn = MagicMock(side_effect=[
        "BAD_F9",   # round 1 (targets F9): no change, F9 still failing
        "BAD_F1",   # round 2 (targets F9): fixes F9, introduces F1 (side effect)
        "",         # round 3 (targets the newly-discovered F1): fixes it
    ])

    result = run_gates(piece, gate_fns, repair_fn)

    assert result.status == "passed"
    assert result.initial_failing_gate_count == 1
    assert result.repair_budget == 4  # base(3) extended by +1 for the late F1 discovery
    assert result.repair_count == 3
    assert repair_fn.call_count == 3

    targeted_order = [r.gate_targeted for r in result.repair_log]
    assert targeted_order == ["F9_brand_seo_audit", "F9_brand_seo_audit", "F1_grounding"]
    outcomes = [r.outcome for r in result.repair_log]
    assert outcomes == ["failed", "passed", "passed"]


def test_run_gates_late_discovered_gate_extension_happens_once_not_per_round():
    """A late gate that keeps failing across several rounds must extend the
    budget by +1 ONCE (on first discovery), never once per round it's
    re-targeted -- otherwise a stuck late gate could grow the budget
    unbounded the same way REPAIR_BUDGET_CAP already prevents for the
    initial-simultaneous-failure formula."""
    gate_fns = [
        _fake_gate("F1_grounding", "BAD_F1"),
        _fake_gate("F9_brand_seo_audit", "BAD_F9"),
    ]
    piece = Piece(piece_id="late-gate-stuck", body_tagged="BAD_F9")
    repair_fn = MagicMock(side_effect=[
        "BAD_F1",   # round 1 (targets F9): fixes F9, introduces F1 immediately
        "BAD_F1",   # round 2 (targets late-discovered F1): no change
        "BAD_F1",   # round 3 (targets F1 again): no change
        "BAD_F1",   # round 4 (targets F1 again): no change -- budget (4) now exhausted
    ])

    result = run_gates(piece, gate_fns, repair_fn)

    assert result.status == "held"
    assert result.initial_failing_gate_count == 1
    assert result.repair_budget == 4  # extended exactly once (3 -> 4), not once per round
    assert result.repair_count == 4
    assert repair_fn.call_count == 4
    targeted_order = [r.gate_targeted for r in result.repair_log]
    assert targeted_order == ["F9_brand_seo_audit", "F1_grounding", "F1_grounding", "F1_grounding"]


def test_run_gates_late_gate_extension_still_bounded_by_cap():
    """A piece already AT REPAIR_BUDGET_CAP via the existing simultaneous-
    failure formula must not be pushed past the cap by a late-discovered
    gate on top -- the cap is still the one hard ceiling. F1_grounding is
    placed FIRST in gate_fns (matching the real stack order) and passes on
    the initial body, so it isn't part of `initial_failing_gate_count` --
    once the (unfixed) repair round introduces it too, it becomes
    `first_failure` every subsequent round (checked first), giving the
    late-gate-extension check a real chance to fire against an
    already-capped budget."""
    names = [f"F{i}_fake" for i in range(8)]
    markers = [f"BAD_{i}" for i in range(8)]
    gate_fns = [_fake_gate("F1_grounding", "BAD_F1")] + [
        _fake_gate(n, m) for n, m in zip(names, markers)
    ]
    body0 = " ".join(markers)  # 8 simultaneous failures (F1 not among them) -> budget capped at 8
    piece = Piece(piece_id="late-gate-at-cap", body_tagged=body0)
    # Never fixes any of the original 8, and introduces F1_grounding starting with the
    # very first repair call -- from round 2 onward F1 is the first-failing gate every time.
    repair_fn = MagicMock(return_value=body0 + " BAD_F1")

    result = run_gates(piece, gate_fns, repair_fn)

    assert result.initial_failing_gate_count == 8
    assert result.repair_budget == REPAIR_BUDGET_CAP == 8  # not extended past the cap
    assert result.status == "held"
    assert result.repair_count == REPAIR_BUDGET_CAP == 8
    # confirms F1 (the late gate) really did become the target after round 1, proving the
    # cap-guard was actually exercised, not just vacuously true because F1 never got targeted
    assert result.repair_log[-1].gate_targeted == "F1_grounding"
