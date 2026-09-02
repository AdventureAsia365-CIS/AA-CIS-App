"""AA-512 — services/acp_angle_gate/ranking.py. Pure functions, no mocking needed. Port of
src/aa_social/angles.py::rank() (Ms. Thư repo) — see docs/claude_audit/AA-512-step0-investigation
.md §2 for the read-verbatim ADR 0004 formula and the 2 disclosed scope adaptations."""
from services.acp_angle_gate.ranking import _plain, rank_angles, split_avoid_phrases


class TestPlain:
    def test_normalizes_case_punctuation_whitespace(self):
        assert _plain("Is Sapa  safe... to trek?!") == "is sapa safe to trek"

    def test_different_punctuation_same_plain(self):
        assert _plain("Is Sapa safe to trek?") == _plain("is sapa safe to trek")


class TestSplitAvoidPhrases:
    def test_splits_and_strips_comma_joined_string(self):
        assert split_avoid_phrases("hard sell,  cliché , generic travel copy") == (
            "hard sell", "cliché", "generic travel copy",
        )

    def test_empty_segments_dropped(self):
        assert split_avoid_phrases("a,,  ,b") == ("a", "b")

    def test_empty_string_gives_empty_tuple(self):
        assert split_avoid_phrases("") == ()


class TestRankAngles:
    def test_fewest_violations_wins_regardless_of_answers(self):
        angles = [
            {"name": "A", "why_it_works": "a hard sell pitch"},
            {"name": "B", "why_it_works": "clean copy"},
        ]
        evidence, best = rank_angles(
            angles, claimed_answers=[["q1"], []],
            asked_questions=["q1"], avoid_text="hard sell",
        )
        assert best == 1
        assert evidence[0].violations and not evidence[1].violations

    def test_most_real_answers_wins_when_violations_tied(self):
        angles = [
            {"name": "A", "why_it_works": "clean"},
            {"name": "B", "why_it_works": "clean"},
        ]
        evidence, best = rank_angles(
            angles, claimed_answers=[["Is Sapa safe to trek?"], []],
            asked_questions=["Is Sapa safe to trek?"], avoid_text="",
        )
        assert best == 0
        assert evidence[0].answers == ["Is Sapa safe to trek?"]
        assert evidence[1].answers == []

    def test_claimed_answer_not_in_real_pool_scores_nothing(self):
        """ADR 0004's whole point — an angle claiming a question nobody asked must not be
        credited for it, never trusted on the model's word alone."""
        angles = [{"name": "A", "why_it_works": "x"}]
        evidence, best = rank_angles(
            angles, claimed_answers=[["a question nobody asked"]],
            asked_questions=["a real question"], avoid_text="",
        )
        assert evidence[0].answers == []

    def test_claim_matches_despite_different_punctuation(self):
        angles = [{"name": "A", "why_it_works": "x"}]
        evidence, _best = rank_angles(
            angles, claimed_answers=[["is sapa safe to trek"]],
            asked_questions=["Is Sapa safe to trek?!"], avoid_text="",
        )
        assert evidence[0].answers == ["Is Sapa safe to trek?!"]  # real text, not the claim

    def test_tie_breaks_to_earliest_idx(self):
        angles = [{"name": "A", "why_it_works": "x"}, {"name": "B", "why_it_works": "y"}]
        _evidence, best = rank_angles(
            angles, claimed_answers=[[], []], asked_questions=[], avoid_text="",
        )
        assert best == 0

    def test_missing_claim_defaults_to_empty(self):
        """claimed_answers shorter than angles (or a missing entry) must not crash — treated as
        no claim, matching generate.py's own defensive coercion."""
        angles = [{"name": "A", "why_it_works": "x"}, {"name": "B", "why_it_works": "y"}]
        evidence, best = rank_angles(
            angles, claimed_answers=[["q"]], asked_questions=["q"], avoid_text="",
        )
        assert evidence[1].answers == []
        assert best == 0

    def test_violation_word_boundary_not_substring(self):
        """"epic" as an avoid phrase must not match "epicenter" — word-boundary regex, not a bare
        substring check."""
        angles = [{"name": "A", "why_it_works": "near the epicenter of the region"}]
        evidence, _best = rank_angles(
            angles, claimed_answers=[[]], asked_questions=[], avoid_text="epic",
        )
        assert evidence[0].violations == []

    def test_violation_case_insensitive(self):
        angles = [{"name": "A", "why_it_works": "a HARD SELL pitch"}]
        evidence, _best = rank_angles(
            angles, claimed_answers=[[]], asked_questions=[], avoid_text="hard sell",
        )
        assert len(evidence[0].violations) == 1
