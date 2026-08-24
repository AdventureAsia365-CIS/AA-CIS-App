"""AA-450 — services/acp_content_writing/quality_gates.py. F1/F2/F4-adjusted are pure functions
(no mocking needed); F8/F9-adjusted patch invoke_judge, same convention gates.py's own test
suite and test_aa449_angle_gate_generate.py both already use."""
import json
from unittest.mock import patch

from services.acp_content_writing import quality_gates as qg
from services.acp_content_writing.framework_rubrics import DEFAULT_RUBRIC


class TestGateCtaPresent:
    def test_missing_cta_fails_non_repairable(self):
        result = qg.gate_cta_present(None)
        assert result["passed"] is False
        assert result["repairable"] is False

    def test_empty_string_cta_fails_non_repairable(self):
        result = qg.gate_cta_present("   ")
        assert result["passed"] is False
        assert result["repairable"] is False

    def test_real_cta_passes(self):
        result = qg.gate_cta_present("Book a consultation")
        assert result["passed"] is True


class TestGateGrounding:
    def test_no_fabricated_number_passes(self):
        atom = "The bridge is 22 meters long."
        content = "Cross the 22 meter bridge at dawn for a quiet start to the day."
        result = qg.gate_grounding(content, atom)
        assert result["passed"] is True

    def test_fabricated_number_fails(self):
        atom = "A quiet mountain trail near the village."
        content = "The trail stretches 45 kilometers through dense forest."
        result = qg.gate_grounding(content, atom)
        assert result["passed"] is False
        assert result["repairable"] is True


class TestGateBannedPatterns:
    def test_clean_text_passes(self):
        result = qg.gate_banned_patterns("A quiet morning by the river.", "")
        assert result["passed"] is True

    def test_banned_phrase_fails(self):
        result = qg.gate_banned_patterns("This breathtaking view awaits you.", "")
        assert result["passed"] is False

    def test_skill_v2_only_phrase_also_caught(self):
        # "game-changing" is in SKILL_v2.md's Avoid list but NOT in N7's own BANNED_PATTERNS_SEED
        # — confirms the union, not just a copy of N7's list (AA-450-02 gate map, F2 row).
        result = qg.gate_banned_patterns("This is a truly game-changing itinerary.", "")
        assert result["passed"] is False

    def test_verbatim_atom_text_exempt(self):
        atom = "Locals call it a hidden gem among the northern provinces."
        result = qg.gate_banned_patterns("Locals call it a hidden gem among the provinces.", atom)
        assert result["passed"] is True


class TestGateExtremeLength:
    def test_normal_length_passes(self):
        assert qg.gate_extreme_length("A" * 200)["passed"] is True

    def test_empty_fails(self):
        assert qg.gate_extreme_length("")["passed"] is False

    def test_runaway_length_fails(self):
        assert qg.gate_extreme_length("A" * 7000)["passed"] is False


def _judge_raw(**fields) -> dict:
    return {"text": json.dumps(fields)}


class TestGateFramework:
    def test_all_criteria_met_passes(self):
        rubric = qg.get_framework_rubric("promotion")
        data = {"items": [{"criterion": c, "score": "1", "evidence": "quote"} for c in rubric]}
        with patch.object(qg, "invoke_judge", return_value=_judge_raw(**data)):
            result = qg.gate_framework("some piece", "promotion")
        assert result["passed"] is True

    def test_unmet_criterion_fails(self):
        rubric = qg.get_framework_rubric("promotion")
        items = [{"criterion": c, "score": "1", "evidence": "quote"} for c in rubric]
        items[0]["score"] = "0"
        with patch.object(qg, "invoke_judge", return_value=_judge_raw(items=items)):
            result = qg.gate_framework("some piece", "promotion")
        assert result["passed"] is False

    def test_score_1_without_evidence_treated_as_fail(self):
        rubric = qg.get_framework_rubric("promotion")
        items = [{"criterion": c, "score": "1", "evidence": ""} for c in rubric]
        with patch.object(qg, "invoke_judge", return_value=_judge_raw(items=items)):
            result = qg.gate_framework("some piece", "promotion")
        assert result["passed"] is False

    def test_judge_exception_treated_as_fail_not_crash(self):
        with patch.object(qg, "invoke_judge", side_effect=RuntimeError("bedrock down")):
            result = qg.gate_framework("some piece", "promotion")
        assert result["passed"] is False

    def test_covers_goal_with_no_n7_equivalent_framework(self):
        # product_service_explanation -> FAB, which does NOT exist in N7's own FRAMEWORK_RUBRICS
        # (AA-450-02 gate map, F8 row) — confirms the derived rubric, not a silent DEFAULT_RUBRIC.
        rubric = qg.get_framework_rubric("product_service_explanation")
        assert rubric != DEFAULT_RUBRIC
        assert any("Feature" in c for c in rubric)


class TestGateBrandVoice:
    def test_pass_status(self):
        data = {"status": "pass", "brand_fit": "1", "cta_clear": "1", "human_read": "1",
                 "failure_codes": [], "flagged_phrases": [], "notes": ""}
        with patch.object(qg, "invoke_judge", return_value=_judge_raw(**data)):
            result = qg.gate_brand_voice("piece", "Book now", "brand rubric text")
        assert result["passed"] is True

    def test_flagged_status_fails_with_reason(self):
        data = {"status": "flagged", "brand_fit": "0", "cta_clear": "1", "human_read": "1",
                 "failure_codes": ["SUMMARY_OFF_BRAND"], "flagged_phrases": ["generic phrase"],
                 "notes": "reads generic"}
        with patch.object(qg, "invoke_judge", return_value=_judge_raw(**data)):
            result = qg.gate_brand_voice("piece", "Book now", "brand rubric text")
        assert result["passed"] is False
        assert "generic phrase" in result["violations"][0]

    def test_required_cta_reaches_the_prompt(self):
        data = {"status": "pass", "brand_fit": "1", "cta_clear": "1", "human_read": "1",
                 "failure_codes": [], "flagged_phrases": [], "notes": ""}
        with patch.object(qg, "invoke_judge", return_value=_judge_raw(**data)) as mock_judge:
            qg.gate_brand_voice("piece", "Book a consultation today", "brand rubric text")
        user_prompt = mock_judge.call_args[0][1]
        assert "Book a consultation today" in user_prompt


class TestRunQualityGates:
    def _passing_data(self, fields):
        return _judge_raw(**fields)

    def test_missing_cta_short_circuits_before_any_judge_call(self):
        with patch.object(qg, "invoke_judge") as mock_judge:
            outcome = qg.run_quality_gates(
                content_text="piece", atom_text="atom", cta=None, goal_key="promotion",
                brand_rubric_text="rubric",
            )
        assert outcome["passed"] is False
        assert outcome["first_failure"]["gate"] == "F6_cta_present"
        assert outcome["first_failure"]["repairable"] is False
        mock_judge.assert_not_called()

    def test_all_gates_pass(self):
        rubric = qg.get_framework_rubric("promotion")
        f8_data = {"items": [{"criterion": c, "score": "1", "evidence": "q"} for c in rubric]}
        f9_data = {"status": "pass", "brand_fit": "1", "cta_clear": "1", "human_read": "1",
                    "failure_codes": [], "flagged_phrases": [], "notes": ""}
        with patch.object(qg, "invoke_judge", side_effect=[_judge_raw(**f8_data), _judge_raw(**f9_data)]):
            outcome = qg.run_quality_gates(
                content_text="A clean, specific piece about the trail.", atom_text="the trail",
                cta="Book now", goal_key="promotion", brand_rubric_text="rubric",
            )
        assert outcome["passed"] is True
        assert len(outcome["gate_ledger"]) == 6  # cta + grounding + banned + length + f8 + f9

    def test_first_det_failure_used_for_repair_targeting(self):
        rubric = qg.get_framework_rubric("promotion")
        f8_data = {"items": [{"criterion": c, "score": "1", "evidence": "q"} for c in rubric]}
        f9_data = {"status": "pass", "brand_fit": "1", "cta_clear": "1", "human_read": "1",
                    "failure_codes": [], "flagged_phrases": [], "notes": ""}
        with patch.object(qg, "invoke_judge", side_effect=[_judge_raw(**f8_data), _judge_raw(**f9_data)]):
            outcome = qg.run_quality_gates(
                content_text="This breathtaking view awaits you.", atom_text="a view",
                cta="Book now", goal_key="promotion", brand_rubric_text="rubric",
            )
        assert outcome["passed"] is False
        assert outcome["first_failure"]["gate"] == "F2_banned_patterns"
        assert outcome["first_failure"]["repairable"] is True
