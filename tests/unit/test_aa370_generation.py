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

from services.acp_produce.gates import gate_grounding
from services.acp_produce.generation import (DraftGenerationFailed, build_outline,
                                              generate_draft)
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

    def _fake_invoke(prompt, model, max_tokens, system):
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
