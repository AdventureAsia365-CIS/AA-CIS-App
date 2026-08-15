"""
tests/unit/test_aa370_generation.py — services/acp_produce/generation.py
(AA-370: E1 build_outline() deterministic outline, E2 generate_draft()
Sonnet-batched draft) + a direct F1 grounding check on E2-shaped output
(gates.py::gate_grounding(), already built in AA-298 — AA-370 only needs to
confirm the [R:atom_id] tag format E2 produces is compatible, not change F1).

No live Bedrock calls — shared.llm_client.bedrock_satellite.invoke_claude is
mocked throughout, same convention as test_aa369_research.py.
"""
from unittest.mock import patch

import pytest

from services.acp_produce.gates import gate_grounding, gate_structural_variance
from services.acp_produce.generation import (DraftGenerationFailed, _build_extra_section_directives,
                                              _compute_words_per_section, _select_variance_owners,
                                              build_outline, generate_draft)
from services.acp_produce.models import Brief, KeywordRecord, OutlineSection
from shared.llm_client.bedrock_satellite import BedrockInvokeResult, BedrockUnavailable


def _brief(**overrides) -> Brief:
    defaults = dict(
        brief_id="brief-1", slot_id="slot-1", keyword="sapa trekking tours",
        demand=KeywordRecord(keyword="sapa trekking tours", location="US", volume=500, confidence="dfs"),
        required_h2s=[
            "Sapa Trekking Tours: what it's actually like",
            "Sapa trek passes 3 ethnic minority villages over 2 days",
            "Homestay dinner is cooked by the host family, not a res",
            "FAQ",
        ],
        atoms_by_section={
            "Sapa Trekking Tours: what it's actually like": [],
            "Sapa trek passes 3 ethnic minority villages over 2 days": ["atom_a"],
            "Homestay dinner is cooked by the host family, not a res": ["atom_b"],
            "FAQ": ["atom_c"],
        },
        faq_candidates=[],
        framework="hub", cta_target="https://aa.example.com/tours/sapa",
    )
    defaults.update(overrides)
    return Brief(**defaults)


def _atom_text():
    return {
        "atom_a": "Sapa trek passes 3 ethnic minority villages over 2 days.",
        "atom_b": "Homestay dinner is cooked by the host family, not a restaurant.",
        "atom_c": "Best season is Sep-Nov and Mar-May, per local guides.",
    }


def _sonnet_result(text: str) -> BedrockInvokeResult:
    return BedrockInvokeResult(text=text, model_used="sonnet-4-6", latency_ms=500.0,
                                usage={"input_tokens": 800, "output_tokens": 900})


def _marker_block(title: str, body: str) -> str:
    return f"===SECTION:{title}===\n{body}\n"


# ---------------------------------------------------------------- E1 build_outline (no LLM)

def test_build_outline_never_calls_bedrock():
    brief = _brief()
    with patch("services.acp_produce.generation.invoke_claude", side_effect=AssertionError("must not be called")):
        outline = build_outline(brief)
    assert len(outline) == 3  # "FAQ" excluded (AA-371: E4/faq.py owns it entirely)
    assert all(isinstance(s, OutlineSection) for s in outline)


def test_build_outline_atom_ids_from_atoms_by_section():
    outline = build_outline(_brief())
    by_title = {s.title: s for s in outline}
    assert by_title["Sapa trek passes 3 ethnic minority villages over 2 days"].atom_ids == ["atom_a"]


def test_build_outline_empty_atom_section_goal_says_so():
    outline = build_outline(_brief())
    title_section = next(s for s in outline if s.title == "Sapa Trekking Tours: what it's actually like")
    assert title_section.atom_ids == []
    assert "no atoms" in title_section.goal.lower() or "No atoms" in title_section.goal


def test_build_outline_excludes_faq_section_entirely():
    """AA-371: E2/E1 no longer drafts a generic FAQ section at all — E4
    (faq.py) owns Brief.faq_candidates answers exclusively, appended to
    body_tagged separately. atoms_by_section["FAQ"] entries (if any) are
    simply not surfaced as an OutlineSection — regardless of faq_candidates
    count, "FAQ" never appears in build_outline()'s output."""
    from services.acp_produce.models import FAQCandidate
    brief = _brief(faq_candidates=[
        FAQCandidate(question="Is it safe?", source_id="atom_a"),
        FAQCandidate(question="What to pack?", source_id="atom_b"),
    ])
    outline = build_outline(brief)
    assert all(s.title != "FAQ" for s in outline)


# ---------------------------------------------------------------- E2 generate_draft

def test_generate_draft_single_batch_happy_path():
    outline = build_outline(_brief())[1:3]  # 2 sections -> 1 batch
    response_text = (
        _marker_block(outline[0].title, "Villages here feel lived-in [R:atom_a].")
        + _marker_block(outline[1].title, "Dinner is home-cooked, not a restaurant plate [R:atom_b].")
    )
    with patch("services.acp_produce.generation.invoke_claude",
               return_value=_sonnet_result(response_text)) as mock_invoke:
        body = generate_draft(_brief(), outline, _atom_text())

    mock_invoke.assert_called_once()
    assert mock_invoke.call_args.kwargs["model"] == "sonnet"
    assert f"## {outline[0].title}" in body
    assert "[R:atom_a]" in body
    assert "[R:atom_b]" in body


def test_generate_draft_batches_5_sections_as_3_then_2():
    outline = [OutlineSection(title=f"Section {i}", atom_ids=[], goal="g") for i in range(5)]
    calls = []

    def _fake_invoke(prompt, model, max_tokens, system, account=None):
        calls.append(prompt)
        batch_titles = [ln.split("SECTION: ")[1] for ln in prompt.splitlines() if ln.startswith("SECTION: ")]
        text = "".join(_marker_block(t, f"body for {t} [R:atom_a]") for t in batch_titles)
        return _sonnet_result(text)

    with patch("services.acp_produce.generation.invoke_claude", side_effect=_fake_invoke) as mock_invoke:
        body = generate_draft(_brief(), outline, {"atom_a": "x"})

    assert mock_invoke.call_count == 2
    assert "Section 0" in calls[0] and "Section 1" in calls[0] and "Section 2" in calls[0]
    assert "Section 3" in calls[1] and "Section 4" in calls[1]
    for s in outline:
        assert f"## {s.title}" in body


def test_generate_draft_retries_then_succeeds():
    outline = build_outline(_brief())[1:2]
    response_text = _marker_block(outline[0].title, "Grounded body [R:atom_a].")
    with patch("services.acp_produce.generation.invoke_claude",
               side_effect=[BedrockUnavailable("throttled"), _sonnet_result(response_text)]) as mock_invoke, \
         patch("services.acp_produce.generation.time.sleep"):
        body = generate_draft(_brief(), outline, _atom_text())

    assert mock_invoke.call_count == 2
    assert "[R:atom_a]" in body


def test_generate_draft_raises_after_max_retries():
    outline = build_outline(_brief())[1:2]
    with patch("services.acp_produce.generation.invoke_claude",
               side_effect=BedrockUnavailable("throttled")) as mock_invoke, \
         patch("services.acp_produce.generation.time.sleep"):
        with pytest.raises(DraftGenerationFailed):
            generate_draft(_brief(), outline, _atom_text())
    assert mock_invoke.call_count == 3


def test_generate_draft_raises_on_unparseable_response():
    outline = build_outline(_brief())[1:2]
    with patch("services.acp_produce.generation.invoke_claude",
               return_value=_sonnet_result("no markers here, just prose.")):
        with pytest.raises(DraftGenerationFailed):
            generate_draft(_brief(), outline, _atom_text())


def test_generate_draft_empty_outline_raises_value_error():
    with pytest.raises(ValueError):
        generate_draft(_brief(), [], {})


# ---------------------------------------------------------------- F1 grounding compatibility (AA-298 gate, unchanged)

def test_e2_shaped_output_passes_f1_grounding_when_grounded():
    outline = build_outline(_brief())[1:3]
    response_text = (
        _marker_block(outline[0].title, "Villages here feel lived-in [R:atom_a].")
        + _marker_block(outline[1].title, "Dinner is home-cooked, not a restaurant plate [R:atom_b].")
    )
    with patch("services.acp_produce.generation.invoke_claude", return_value=_sonnet_result(response_text)):
        body = generate_draft(_brief(), outline, _atom_text())

    result = gate_grounding(body, set(_atom_text()), _atom_text())
    assert result.passed is True


def test_e2_shaped_output_fails_f1_grounding_on_fabricated_number():
    outline = build_outline(_brief())[1:2]
    fabricated = _marker_block(outline[0].title, "The trek passes 22 hidden waterfalls [R:atom_a].")
    with patch("services.acp_produce.generation.invoke_claude", return_value=_sonnet_result(fabricated)):
        body = generate_draft(_brief(), outline, _atom_text())

    result = gate_grounding(body, set(_atom_text()), _atom_text())
    assert result.passed is False
    assert any("22" in v for v in result.violations)


# ---------------------------------------------------------------- AA-404 Part 1: F3 variance ownership

def test_select_variance_owners_picks_most_atoms_as_long_fewest_as_short():
    outline = [
        OutlineSection(title="A", atom_ids=["a1"], goal="g"),
        OutlineSection(title="B", atom_ids=["b1", "b2", "b3"], goal="g"),
        OutlineSection(title="C", atom_ids=[], goal="g"),
    ]
    long_title, short_title = _select_variance_owners(outline)
    assert long_title == "B"
    assert short_title == "C"


def test_select_variance_owners_ties_break_by_first_occurrence():
    outline = [
        OutlineSection(title="A", atom_ids=["a1"], goal="g"),
        OutlineSection(title="B", atom_ids=["b1"], goal="g"),
    ]
    long_title, short_title = _select_variance_owners(outline)
    assert long_title == "A"
    assert short_title == "B"  # excluded from being the same as "long" since len(outline) > 1


def test_select_variance_owners_single_section_owns_both_directives():
    outline = [OutlineSection(title="Solo", atom_ids=[], goal="g")]
    long_title, short_title = _select_variance_owners(outline)
    assert long_title == short_title == "Solo"


def test_select_variance_owners_empty_outline_raises():
    with pytest.raises(ValueError):
        _select_variance_owners([])


def test_compute_words_per_section_uniform_when_fewer_than_3_sections():
    outline = [OutlineSection(title="A", atom_ids=[], goal="g"),
               OutlineSection(title="B", atom_ids=[], goal="g")]
    result = _compute_words_per_section(_brief(), outline, "A")
    assert result["A"] == result["B"]


def test_compute_words_per_section_inflates_long_by_at_least_the_gate_threshold():
    """gates.py::gate_structural_variance() requires the longest section to
    be >=1.4x the second-longest whenever there are >=3 H2 sections."""
    outline = [OutlineSection(title=t, atom_ids=[], goal="g") for t in ("A", "B", "C")]
    result = _compute_words_per_section(_brief(), outline, "B")
    assert result["B"] >= result["A"] * 1.4
    assert result["B"] >= result["C"] * 1.4


def test_compute_words_per_section_total_stays_within_f4_word_range():
    """The redistribution must not blow past F4_brief_compliance's ±30%
    word-count tolerance (gates.py::gate_brief_compliance()) — only the
    DISTRIBUTION across sections should change, not the total."""
    outline = [OutlineSection(title=t, atom_ids=[], goal="g") for t in ("A", "B", "C", "D")]
    brief = _brief(word_range=(900, 1400))
    result = _compute_words_per_section(brief, outline, "B")
    words_mid = sum(brief.word_range) // 2
    assert sum(result.values()) <= words_mid * 1.3


def test_build_extra_section_directives_long_and_short_get_the_right_notes():
    outline = [OutlineSection(title="A", atom_ids=["a1", "a2"], goal="g"),
               OutlineSection(title="B", atom_ids=[], goal="g"),
               OutlineSection(title="C", atom_ids=["c1"], goal="g")]
    directives = _build_extra_section_directives(_brief(framework="hub"), outline, "A", "B")
    assert any("LENGTH DIRECTIVE" in d for d in directives["A"])
    assert any("RHYTHM DIRECTIVE" in d for d in directives["B"])
    assert directives["C"] == []


def test_build_extra_section_directives_no_length_note_below_3_sections():
    outline = [OutlineSection(title="A", atom_ids=["a1"], goal="g"),
               OutlineSection(title="B", atom_ids=[], goal="g")]
    directives = _build_extra_section_directives(_brief(framework="hub"), outline, "A", "B")
    assert not any("LENGTH DIRECTIVE" in d for d in directives["A"])
    assert any("RHYTHM DIRECTIVE" in d for d in directives["B"])


def test_build_extra_section_directives_aida_adds_hook_and_cta_notes_to_first_and_last():
    outline = [OutlineSection(title=t, atom_ids=[], goal="g") for t in ("Open", "Mid", "Close")]
    directives = _build_extra_section_directives(_brief(framework="AIDA"), outline, "Mid", "Open")
    assert any("ATTENTION-HOOK REQUIREMENT" in d for d in directives["Open"])
    assert any("SINGLE-CTA REQUIREMENT" in d for d in directives["Close"])
    assert not any("ATTENTION-HOOK" in d or "SINGLE-CTA" in d for d in directives["Mid"])


def test_build_extra_section_directives_non_aida_gets_no_hook_cta_notes():
    outline = [OutlineSection(title=t, atom_ids=[], goal="g") for t in ("Open", "Mid", "Close")]
    directives = _build_extra_section_directives(_brief(framework="hub"), outline, "Mid", "Open")
    assert not any("ATTENTION-HOOK" in d for d in directives["Open"])
    assert not any("SINGLE-CTA" in d for d in directives["Close"])


def test_generate_draft_prompt_carries_targeted_directives_and_aida_guidance():
    brief = _brief(framework="AIDA", required_h2s=[
        "Opening hook section", "Middle detail section", "Closing CTA section", "FAQ",
    ], atoms_by_section={
        "Opening hook section": ["atom_a"],
        "Middle detail section": ["atom_a", "atom_b", "atom_c"],
        "Closing CTA section": [],
        "FAQ": [],
    })
    outline = build_outline(brief)
    calls = []

    def _fake_invoke(prompt, model, max_tokens, system, account=None):
        calls.append(prompt)
        titles = [ln.split("SECTION: ")[1] for ln in prompt.splitlines() if ln.startswith("SECTION: ")]
        text = "".join(_marker_block(t, f"body for {t} [R:atom_a]") for t in titles)
        return _sonnet_result(text)

    with patch("services.acp_produce.generation.invoke_claude", side_effect=_fake_invoke):
        generate_draft(brief, outline, {"atom_a": "x", "atom_b": "y", "atom_c": "z"})

    full_prompt = "\n".join(calls)
    assert "AIDA FRAMEWORK (Attention-Interest-Desire-Action)" in full_prompt
    assert "ATTENTION-HOOK REQUIREMENT" in full_prompt
    assert "SINGLE-CTA REQUIREMENT" in full_prompt
    assert "LENGTH DIRECTIVE" in full_prompt
    assert "RHYTHM DIRECTIVE" in full_prompt


def test_generate_draft_non_aida_prompt_has_no_aida_guidance():
    outline = build_outline(_brief(framework="hub"))
    calls = []

    def _fake_invoke(prompt, model, max_tokens, system, account=None):
        calls.append(prompt)
        titles = [ln.split("SECTION: ")[1] for ln in prompt.splitlines() if ln.startswith("SECTION: ")]
        text = "".join(_marker_block(t, f"body for {t} [R:atom_a]") for t in titles)
        return _sonnet_result(text)

    with patch("services.acp_produce.generation.invoke_claude", side_effect=_fake_invoke):
        generate_draft(_brief(framework="hub"), outline, _atom_text())

    full_prompt = "\n".join(calls)
    assert "AIDA FRAMEWORK" not in full_prompt
    assert "ATTENTION-HOOK REQUIREMENT" not in full_prompt


def test_generate_draft_output_can_pass_f3_when_writer_follows_targeted_directives():
    """AA-404 Part 1 mechanism check: when the model follows the per-section
    directives it's given, the resulting body passes F3 — this is not a
    claim that a real LLM WILL follow them, only that doing so is sufficient
    to satisfy the gate (docs/implementation-notes/AA-404.md §2's root-cause
    finding was that the OLD blanket directive gave the model no reliable
    way to know whether it had already been satisfied by another batch)."""
    brief = _brief(framework="hub", required_h2s=[
        "Section One", "Section Two", "Section Three", "FAQ",
    ], atoms_by_section={
        "Section One": [], "Section Two": ["atom_a", "atom_b", "atom_c"],
        "Section Three": [], "FAQ": [],
    })
    outline = build_outline(brief)
    long_title, short_title = _select_variance_owners(outline)
    assert long_title == "Section Two"
    assert short_title == "Section One"

    def _fake_invoke(prompt, model, max_tokens, system, account=None):
        titles = [ln.split("SECTION: ")[1] for ln in prompt.splitlines() if ln.startswith("SECTION: ")]
        parts = []
        for t in titles:
            if t == short_title:
                body = ("Short and true.\n\n"
                         "A longer paragraph with several full sentences follows here. "
                         "It continues for a bit longer to add more context. "
                         "This is a third sentence for good measure.")
            elif t == long_title:
                body = "This longer section develops the topic in real depth. " * 12
            else:
                body = "A normal paragraph with two full sentences. Here is the second one."
            parts.append(_marker_block(t, body))
        return _sonnet_result("".join(parts))

    with patch("services.acp_produce.generation.invoke_claude", side_effect=_fake_invoke):
        body = generate_draft(brief, outline, {"atom_a": "x", "atom_b": "y", "atom_c": "z"})

    result = gate_structural_variance(body, "blog")
    assert result.passed is True, result.violations
