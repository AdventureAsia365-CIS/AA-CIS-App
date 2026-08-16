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


# =================================== AA-404 N0-N8 audit follow-up: atoms_by_section (opt-in, off by default)

def test_gate_grounding_atoms_by_section_none_is_unchanged_behavior():
    """Backward compat: every pre-existing caller/test (no atoms_by_section arg) gets exactly
    the old whole-piece-only check — a section citing an atom assigned to a DIFFERENT section
    is NOT flagged when the new param is omitted."""
    body = (
        "## Intro\nThe rickshaw ride opens the trip [R:atom_a].\n\n"
        "## Detail\nMore about the fort [R:atom_b]."
    )
    result = gate_grounding(body, {"atom_a", "atom_b"}, {"atom_a": "x", "atom_b": "y"})
    assert result.passed is True


def test_gate_grounding_section_scoping_passes_when_each_section_cites_only_its_own_atoms():
    body = (
        "## Intro\nThe rickshaw ride opens the trip [R:atom_a].\n\n"
        "## Detail\nMore about the fort [R:atom_b]."
    )
    result = gate_grounding(
        body, {"atom_a", "atom_b"}, {"atom_a": "x", "atom_b": "y"},
        atoms_by_section={"Intro": ["atom_a"], "Detail": ["atom_b"]},
    )
    assert result.passed is True
    assert result.violations == []


def test_gate_grounding_section_scoping_flags_atom_cited_in_wrong_section():
    """atom_b is globally valid for the piece (in `valid_ids`) but the outline assigned it to
    'Detail', not 'Intro' — citing it in Intro must fail with atoms_by_section given."""
    body = (
        "## Intro\nThe rickshaw ride opens the trip [R:atom_a], with the fort ahead [R:atom_b].\n\n"
        "## Detail\nMore about the fort [R:atom_b]."
    )
    result = gate_grounding(
        body, {"atom_a", "atom_b"}, {"atom_a": "x", "atom_b": "y"},
        atoms_by_section={"Intro": ["atom_a"], "Detail": ["atom_b"]},
    )
    assert result.passed is False
    assert any("atom_b" in v and "Intro" in v for v in result.violations)


def test_gate_grounding_section_scoping_skips_faq_section():
    """'FAQ' is never a key in atoms_by_section (generation.py::build_outline() never assigns
    it one, E4/faq.py owns that section) — a FAQ section reusing an atom cited elsewhere in
    the piece must NOT be flagged, matching real 15/08 corpus data (every real cross-section
    reuse case that involved FAQ was FAQ legitimately re-citing a body atom to answer a
    question)."""
    body = (
        "## Intro\nThe rickshaw ride opens the trip [R:atom_a].\n\n"
        "## FAQ\n**Q: What's the highlight?**\n**A:** The rickshaw ride [R:atom_a]."
    )
    result = gate_grounding(
        body, {"atom_a"}, {"atom_a": "x"},
        atoms_by_section={"Intro": ["atom_a"]},  # no "FAQ" key at all
    )
    assert result.passed is True


def test_gate_grounding_section_scoping_real_corpus_case():
    """Real case from the 15/08 corpus (piece de8337ba...:slot_845eb6ec83cdf1f082ec:blog,
    used as the F9 fix #2 anchor sentence elsewhere) — atom_e79157604b (the Gyeongju bullet
    train fact) was cited in BOTH the intro overview section AND its own dedicated detail
    section. Demonstrates the mechanism actually catches the real-data pattern the impact
    analysis found (9/23 real pieces, 39%) — not just a synthetic example."""
    body = (
        "## Transit In South Korea: what it's actually like\n"
        "A bullet train reaches Gyeongju in under two hours [R:atom_e79157604b].\n\n"
        "## Travel by bullet train from Seoul to Gyeongju, the ancient c\n"
        "The Gyeonggi-Gyeongbu line reaches Gyeongju [R:atom_e79157604b]."
    )
    result = gate_grounding(
        body, {"atom_e79157604b"}, {"atom_e79157604b": "Bullet train to Gyeongju."},
        atoms_by_section={
            "Transit In South Korea: what it's actually like": [],
            "Travel by bullet train from Seoul to Gyeongju, the ancient c": ["atom_e79157604b"],
        },
    )
    assert result.passed is False
    assert any(
        "atom_e79157604b" in v and "Transit In South Korea" in v for v in result.violations
    )


def test_gate_grounding_does_not_merge_faq_markdown_bold_into_preceding_sentence():
    """AA-405: real week=2 CloudWatch fabrication alarm, shape reproduced from the
    actual held piece (slot_b30a9406...:blog) — citation sits on an earlier,
    plain-punctuation sentence boundary, exactly as in the real body ("...marks
    the border [R:atom_dmz]. It is the kind of place..."), not directly against
    the markdown-link/heading run that follows. Before the fix, `_SENT_SPLIT_RE`
    didn't split before `**Q:` (markdown bold doesn't match the old lookahead
    character class), so an itinerary sentence's citation several sentences
    earlier could get merged across the CTA-link/`## FAQ`/FAQ-question run and
    blamed for an unrelated FAQ answer's numbers. The DMZ atom has nothing to do
    with a "52 hour rule" labor-law question; a correctly-split gate must not
    reach across the FAQ boundary to blame it.

    NOTE (AA-405/AA-409): markdown *links* (`[text](url)`) and `##` headings
    still don't match the split lookahead either — same class of gap, not fixed
    by this change. It didn't fire in production because no real citation sits
    directly against a link/heading boundary in the corpus seen so far, but a
    body that put one there would still merge. Flagging for AA-409 or a
    follow-up, not fixed here (scope: the `**` FAQ-marker case that actually
    fired the alarm)."""
    body = (
        "The Freedom Bridge marks the border between North and South Korea "
        "[R:atom_dmz]. It is the kind of place that needs no embellishment. "
        "It allows each element to settle.\n\n"
        "[Design This Journey](https://aa-cis.lumiguides.it.com/)\n\n"
        "## FAQ\n\n"
        "**Q: Is South Korea bike friendly?**\n"
        "A: South Korea accommodates cycling, with routes through Seoul [R:atom_seoul].\n\n"
        "**Q: What is the 52 hour rule in South Korea?**\n"
        "A: The given fact does not address the 52-hour rule.\n\n"
        "**Q: Can someone live for $2000 a month in South Korea?**\n"
        "A: The given fact does not address living costs in South Korea."
    )
    result = gate_grounding(
        body,
        {"atom_dmz", "atom_seoul"},
        {
            "atom_dmz": "Day 2 is a car transfer to the Demilitarised Zone and the Freedom Bridge.",
            "atom_seoul": "The itinerary opens with cycling etiquette before heading into Seoul.",
        },
    )
    assert result.passed is True, result.violations
    assert result.violations == []


def test_gate_grounding_faq_merge_bug_is_real_under_the_old_split_regex():
    """Companion to the test above: proves the reproduction is real, not a
    tautology — the exact same body/ids/text WOULD have been flagged under the
    pre-fix `_SENT_SPLIT_RE` (module-patched here, not asserting on the real
    fix), because `?**\\nA:` and `.\\n\\n**Q` never split, chaining the whole
    FAQ block (including atom_seoul's legitimate citation) into one blob that
    also contains '52' and '2000' -- numbers atom_seoul's text never states."""
    import re
    import services.acp_produce.gates as gates_module

    old_split_re = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'‘’“”])")
    body = (
        "The Freedom Bridge marks the border between North and South Korea "
        "[R:atom_dmz]. It is the kind of place that needs no embellishment. "
        "It allows each element to settle.\n\n"
        "[Design This Journey](https://aa-cis.lumiguides.it.com/)\n\n"
        "## FAQ\n\n"
        "**Q: Is South Korea bike friendly?**\n"
        "A: South Korea accommodates cycling, with routes through Seoul [R:atom_seoul].\n\n"
        "**Q: What is the 52 hour rule in South Korea?**\n"
        "A: The given fact does not address the 52-hour rule.\n\n"
        "**Q: Can someone live for $2000 a month in South Korea?**\n"
        "A: The given fact does not address living costs in South Korea."
    )
    original = gates_module._SENT_SPLIT_RE
    gates_module._SENT_SPLIT_RE = old_split_re
    try:
        result = gate_grounding(
            body,
            {"atom_dmz", "atom_seoul"},
            {
                "atom_dmz": "Day 2 is a car transfer to the Demilitarised Zone and the Freedom Bridge.",
                "atom_seoul": "The itinerary opens with cycling etiquette before heading into Seoul.",
            },
        )
    finally:
        gates_module._SENT_SPLIT_RE = original
    assert result.passed is False
    assert any("52" in v and "2000" in v for v in result.violations)


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
