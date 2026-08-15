"""
tests/unit/test_aa404_atom_density.py — services/acp_produce/gates.py::gate_atom_density()
(F5, AA-404 — N0-N8 defense-layer audit's #1 finding, aa-marketing-v2/CONTEXT.md §1.6.1's
highest-leverage anti-AI-voice layer, never built until now).

Same convention as test_aa372_gates.py — calls the gate function directly with hand-built
`body_tagged` strings, no pipeline/DB involved.
"""
from services.acp_produce.gates import ATOM_DENSITY_WORDS, gate_atom_density

assert ATOM_DENSITY_WORDS == 300, "test constants below assume the real 300-word window"


def _words(n: int, start: int = 0) -> str:
    """`n` distinct plain words, no citation tags."""
    return " ".join(f"word{i}" for i in range(start, start + n))


def test_passes_when_the_only_window_has_a_citation():
    body = _words(299) + " [R:atom_1]"
    result = gate_atom_density(body)
    assert result.gate == "F5_atom_density"
    assert result.passed is True
    assert result.violations == []


def test_fails_a_300_word_window_with_zero_citations():
    body = _words(300)
    result = gate_atom_density(body)
    assert result.passed is False
    assert len(result.violations) == 1
    assert "words 0-300" in result.violations[0]
    assert "zero atom/fact citations" in result.violations[0]


def test_multi_window_flags_only_the_zero_atom_window():
    body = (_words(299) + " [R:atom_1] " + _words(300, start=300))
    result = gate_atom_density(body)
    assert result.passed is False
    assert len(result.violations) == 1
    assert "words 300-600" in result.violations[0]


def test_two_zero_atom_windows_both_flagged():
    body = _words(300) + " " + _words(300, start=300)
    result = gate_atom_density(body)
    assert result.passed is False
    assert len(result.violations) == 2
    assert any("words 0-300" in v for v in result.violations)
    assert any("words 300-600" in v for v in result.violations)


def test_trailing_chunk_shorter_than_half_window_is_skipped():
    """149 words < ATOM_DENSITY_WORDS // 2 (150) -- too short to reasonably fit a citation,
    same guard the aamc original used."""
    body = _words(299) + " [R:atom_1] " + _words(149, start=300)
    result = gate_atom_density(body)
    assert result.passed is True
    assert result.violations == []


def test_trailing_chunk_at_exactly_half_window_is_evaluated():
    """150 words == ATOM_DENSITY_WORDS // 2 -- NOT skipped (the guard is strictly '<')."""
    body = _words(299) + " [R:atom_1] " + _words(150, start=300)
    result = gate_atom_density(body)
    assert result.passed is False
    assert len(result.violations) == 1
    assert "words 300-450" in result.violations[0]


def test_empty_body_passes_trivially():
    result = gate_atom_density("")
    assert result.passed is True
    assert result.violations == []


def test_reuses_shared_tag_re_facts_tag_also_satisfies_density():
    """[F:fact_id] (facts-pack domain) counts the same as [R:atom_id] -- gate_atom_density()
    reuses this module's own TAG_RE, doesn't invent a narrower atom-only pattern."""
    body = _words(299) + " [F:fact_1]"
    result = gate_atom_density(body)
    assert result.passed is True


def test_facebook_length_body_is_exempted_by_window_floor():
    """Real facebook piece bodies run 80-150 words (adapt.py) -- entirely under the 150-word
    floor, so the single implicit chunk is skipped before the tag check ever runs. No
    explicit `channel` branch in gate_atom_density() -- this is the window-size guard doing
    the exemption naturally, same as the aamc original (which never took a channel either)."""
    body = _words(120)  # no citation tags at all
    result = gate_atom_density(body)
    assert result.passed is True
    assert result.violations == []


def test_tiktok_length_body_is_exempted_by_window_floor():
    """Real tiktok script bodies run ~100-150 words (adapt.py) -- same natural exemption."""
    body = _words(140)  # no citation tags at all
    result = gate_atom_density(body)
    assert result.passed is True
    assert result.violations == []


def test_violation_includes_a_text_sample_for_repair_context():
    body = _words(300)
    result = gate_atom_density(body)
    assert "First 80 chars:" in result.violations[0]
    assert "word0 word1 word2" in result.violations[0]
