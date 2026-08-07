"""
tests/unit/test_aa298_gates.py — services/acp_produce/gates.py::gate_grounding()
(N7 F1, AA-298 P0-1).

fixtures/aa298_gates_grounding_bodies.json is not synthetic: for each of the
4 real production tours used to verify AA-306/audit AA-325 (23/07/2026), it
is the real generate_s1_from_atom() output body (aa_subtitle + aa_summary +
aa_highlights + aa_itineraries concatenated, exactly how gate_grounding()
receives a tagged body) plus the real curated atom set. One of the 4
(Classic Exploration, tour c410a272) contains the confirmed production
fabrication — "22-meter-long reclining Buddha", a measurement no cited atom
states. The other 3 must not be flagged.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

from services.acp_produce.gates import gate_grounding, run_gates
from services.acp_produce.models import GateResult, Piece

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "aa298_gates_grounding_bodies.json"
TOURS = json.loads(FIXTURE_PATH.read_text())

FABRICATION_TOUR_ID = "c410a272-cac2-486d-9911-a5a73f5365d2"


def test_fixture_has_4_real_tours():
    assert len(TOURS) == 4


def test_gate_grounding_rejects_the_tour_with_the_real_fabrication():
    t = TOURS[FABRICATION_TOUR_ID]
    result = gate_grounding(t["body_tagged"], set(t["valid_ids"]), t["text_by_id"])
    assert result.gate == "F1_grounding"
    assert result.passed is False
    assert any("22" in v for v in result.violations)
    assert len(result.violations) == 1  # exactly the one confirmed fabrication, no other noise


def test_gate_grounding_passes_the_other_3_real_tours_clean():
    false_positives = {}
    for tid, t in TOURS.items():
        if tid == FABRICATION_TOUR_ID:
            continue
        result = gate_grounding(t["body_tagged"], set(t["valid_ids"]), t["text_by_id"])
        if not result.passed:
            false_positives[t["name"]] = result.violations
    assert false_positives == {}


def test_gate_grounding_flags_unknown_provenance_id():
    result = gate_grounding(
        "A rickshaw ride through Chandni Chowk [R:atom_real123]. A made-up elephant trek [R:atom_fake999].",
        {"atom_real123"},
        {"atom_real123": "Ride a rickshaw through Chandni Chowk."},
    )
    assert result.passed is False
    assert any("atom_fake999" in v for v in result.violations)


def test_gate_grounding_passes_faithful_grounded_body():
    result = gate_grounding(
        "The rickshaw ride opens the trip [R:atom_real123]. Sunrise comes next at the fort [R:atom_real456].",
        {"atom_real123", "atom_real456"},
        {"atom_real123": "Ride a rickshaw through Chandni Chowk.",
         "atom_real456": "Watch sunrise at the fort."},
    )
    assert result.passed is True
    assert result.violations == []


# ── run_gates: P0-3 repair loop re-runs the WHOLE stack, not just the failed gate ──

def _fake_gate_f1_grounded_marker(body: str) -> GateResult:
    return GateResult(gate="F1_grounding", passed="GROUNDED" in body,
                       violations=[] if "GROUNDED" in body else ["missing GROUNDED marker"])


def _fake_gate_f3_no_banned_word(body: str) -> GateResult:
    return GateResult(gate="F3_banned_patterns", passed="BANNED_WORD" not in body,
                       violations=[] if "BANNED_WORD" not in body else ["contains BANNED_WORD"])


def test_run_gates_repair_regression_on_f1_is_caught_by_full_restack():
    """The exact AA-298 verify checklist scenario: 'Repair fix F3 cố tình làm hỏng
    F1 -> phải bị bắt lại.' Old aamc/gates.py bug: after repairing F3, it only
    re-checked F3 -- a repair that fixed F3 but broke F1 would ship. This must
    re-run F1 too and catch the regression."""
    piece = Piece(piece_id="p1", body_tagged="GROUNDED some content with BANNED_WORD")
    repair_fn = MagicMock(side_effect=[
        "some content",  # "fixes" F3 (banned word gone) but regresses F1 (marker gone)
        "GROUNDED some content",  # second repair round: restores F1, still no banned word
    ])

    result = run_gates(
        piece, [_fake_gate_f1_grounded_marker, _fake_gate_f3_no_banned_word], repair_fn,
    )

    assert result.status == "passed"
    assert result.repair_count == 2
    assert repair_fn.call_count == 2
    # second repair call must have been given F1's violation (the regression), not F3's --
    # proof the full re-run, not a stale check of only the originally-failed gate, drove it
    second_call_violations = repair_fn.call_args_list[1].args[1]
    assert "missing GROUNDED marker" in second_call_violations


def test_run_gates_holds_after_exhausting_repair_budget():
    piece = Piece(piece_id="p2", body_tagged="no markers at all")
    repair_fn = MagicMock(return_value="still no markers at all")  # never fixes anything

    result = run_gates(
        piece, [_fake_gate_f1_grounded_marker], repair_fn, max_repairs=3,
    )

    assert result.status == "held"
    assert result.repair_count == 3
    assert "F1_grounding" in result.held_reason
    assert repair_fn.call_count == 3


def test_run_gates_passes_clean_body_without_ever_calling_repair():
    piece = Piece(piece_id="p3", body_tagged="GROUNDED, no banned content")
    repair_fn = MagicMock()

    result = run_gates(
        piece, [_fake_gate_f1_grounded_marker, _fake_gate_f3_no_banned_word], repair_fn,
    )

    assert result.status == "passed"
    assert result.repair_count == 0
    repair_fn.assert_not_called()


def test_run_gates_on_real_fabrication_tour_then_repairs_it():
    """End-to-end with the real gate_grounding() (not a stub) against the real
    AA-325 fabrication tour: repair_fn simulates removing the fabricated number,
    run_gates must reach passed status."""
    t = TOURS[FABRICATION_TOUR_ID]
    piece = Piece(piece_id=FABRICATION_TOUR_ID, body_tagged=t["body_tagged"])

    def real_gate(body: str) -> GateResult:
        return gate_grounding(body, set(t["valid_ids"]), t["text_by_id"])

    def strip_22(body: str, violations: list[str]) -> str:
        return body.replace("22-meter-long ", "")

    result = run_gates(piece, [real_gate], strip_22, max_repairs=3)

    assert result.status == "passed"
    assert result.repair_count == 1


# ── run_gates: AA-376 is_repairable filter + repair_fn failure safety net ──

def _fake_gate_always_fails(gate_name: str):
    def _gate(body: str) -> GateResult:
        return GateResult(gate=gate_name, passed=False, violations=[f"{gate_name} always fails"])
    return _gate


def test_run_gates_is_repairable_false_holds_immediately_without_calling_repair_fn():
    """AA-376: a caller-supplied `is_repairable` predicate can veto repair
    entirely for a given failure (e.g. pipeline.py's F6 external-state
    filter) — must hold on round 1, repair_fn never called, repair_count
    stays 0."""
    piece = Piece(piece_id="p4", body_tagged="anything")
    repair_fn = MagicMock()

    result = run_gates(
        piece, [_fake_gate_always_fails("F6_route_to_sellable")], repair_fn,
        max_repairs=3, is_repairable=lambda r: False,
    )

    assert result.status == "held"
    assert result.repair_count == 0
    repair_fn.assert_not_called()


def test_run_gates_is_repairable_only_vetoes_the_matched_gate():
    """A predicate that only vetoes one specific gate must still allow normal
    repair for every other gate."""
    piece = Piece(piece_id="p5", body_tagged="no markers at all")
    repair_fn = MagicMock(return_value="GROUNDED now")

    result = run_gates(
        piece, [_fake_gate_f1_grounded_marker], repair_fn, max_repairs=3,
        is_repairable=lambda r: r.gate != "F6_route_to_sellable",
    )

    assert result.status == "passed"
    repair_fn.assert_called_once()


def test_run_gates_repair_fn_exception_holds_without_incrementing_repair_count():
    """AA-376: if repair_fn itself raises (e.g. RepairFailed after exhausted
    Sonnet retries), run_gates() must hold VISIBLY with the ORIGINAL
    failure's reason rather than propagate the exception and crash the
    whole slot-production run over one piece."""
    piece = Piece(piece_id="p6", body_tagged="no markers at all")
    repair_fn = MagicMock(side_effect=RuntimeError("Sonnet invoke failed after 3 attempts"))

    result = run_gates(
        piece, [_fake_gate_f1_grounded_marker], repair_fn, max_repairs=3,
    )

    assert result.status == "held"
    assert result.repair_count == 0
    assert "F1_grounding" in result.held_reason
    repair_fn.assert_called_once()
