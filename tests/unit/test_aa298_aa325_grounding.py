"""
tests/unit/test_aa298_aa325_grounding.py — shared entailment check
(services/acp_shared/grounding.py), used by both N7 Produce gate_grounding
(AA-298 P0-1) and S1-from-atom check_grounding (AA-325).

fixtures/aa325_grounding_units.json is not synthetic: it is the real output of
generate_s1_from_atom(model_tier="palmyra") against the 4 production tours
used to verify AA-306 (Classic Exploration x2, A sea of coral/Prayers of
Uminchu fishermen, Yaksa Trek BEST DEAL), captured during the AA-325 live
audit (23/07/2026) via ECS exec against real curated atoms. 79 sentence-units,
each with the union of the atom texts it cites. Exactly one is a confirmed
production fabrication (a fabricated "22-meter-long" measurement with no
support in the cited atom) — everything else is faithful paraphrase/synthesis
a working check must NOT flag (this dataset is exactly what falsified the
ADR-2026-029 token-overlap-ratio approach — see ADR-2026-033).
"""
import json
from pathlib import Path

from services.acp_shared.grounding import check_entailment, find_novel_numeric_claims

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "aa325_grounding_units.json"
UNITS = json.loads(FIXTURE_PATH.read_text())

KNOWN_FABRICATION_INDEX = 26  # "Walk among the 22-meter-long reclining Buddha..."


def test_fixture_has_79_real_units():
    assert len(UNITS) == 79


def test_known_fabrication_is_flagged():
    unit = UNITS[KNOWN_FABRICATION_INDEX]
    assert "22-meter-long" in unit["sentence"]
    assert check_entailment(unit["sentence"], unit["cited_atom_texts"]) is False
    assert find_novel_numeric_claims(unit["sentence"], unit["cited_atom_texts"]) == ["22"]


def test_zero_false_positives_on_real_good_content():
    false_positives = []
    for i, unit in enumerate(UNITS):
        if i == KNOWN_FABRICATION_INDEX:
            continue
        if not check_entailment(unit["sentence"], unit["cited_atom_texts"]):
            false_positives.append((i, unit["sentence"]))
    assert false_positives == []


def test_day_label_not_treated_as_claim():
    assert check_entailment(
        "Day 7: Visit Pinnawela Elephant Orphanage.",
        ["Visit Pinnawela Elephant Orphanage."],
    ) is True


def test_multi_citation_sentence_checks_against_union_not_single_atom():
    # A synthesis sentence citing 2 atoms should be checked against BOTH atoms'
    # text combined -- a number legitimately sourced from the second atom must
    # not be flagged just because it is absent from the first.
    sentence = "Visit the temple built in 1592 and the adjoining 3-hectare garden [R:a][R:b]"
    cited = ["The temple was built in 1592.", "The garden covers 3 hectares."]
    assert check_entailment(sentence, cited) is True


def test_fabricated_number_with_no_atom_support_is_flagged():
    sentence = "The waterfall drops 45 meters into a turquoise pool [R:a]"
    cited = ["A scenic waterfall feeds a turquoise pool popular with photographers."]
    assert check_entailment(sentence, cited) is False
    assert find_novel_numeric_claims(sentence, cited) == ["45"]
