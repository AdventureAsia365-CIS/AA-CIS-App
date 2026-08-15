"""
tests/unit/test_aa371_adapt_faq.py — services/acp_produce/adapt.py (AA-371
E3 Adapt channel) + services/acp_produce/faq.py (AA-371 E4 FAQ answer +
JSON-LD) + a direct F1 grounding check on both modules' output shapes
(gates.py::gate_grounding(), unchanged from AA-298/AA-370 — confirms E3/E4
output is compatible, not that F1 itself needed any change).

No live Bedrock calls — shared.llm_client.bedrock_satellite.invoke_claude is
mocked throughout, same convention as test_aa369_research.py /
test_aa370_generation.py.
"""
from unittest.mock import patch

import pytest

from services.acp_produce.adapt import AdaptChannelFailed, _select_atoms_for_channel, adapt_channels
from services.acp_produce.faq import (FAQAnswerFailed, answer_faq, apply_faq,
                                       build_faq_jsonld, render_faq_section)
from services.acp_produce.gates import gate_grounding
from services.acp_produce.models import Brief, FAQCandidate, FAQItem, KeywordRecord, Piece
from services.content_generation.brand_standards import AA_BRAND_IDENTITY_PROMPT
from shared.llm_client.bedrock_satellite import BedrockInvokeResult, BedrockUnavailable


def _sonnet_result(text: str) -> BedrockInvokeResult:
    return BedrockInvokeResult(text=text, model_used="sonnet-4-6", latency_ms=500.0,
                                usage={"input_tokens": 400, "output_tokens": 200})


def _blog_piece(body_tagged: str) -> Piece:
    return Piece(piece_id="piece-1", body_tagged=body_tagged, channel="blog")


def _brief(**overrides) -> Brief:
    defaults = dict(
        brief_id="brief-1", slot_id="slot-1", keyword="sapa trekking tours",
        demand=KeywordRecord(keyword="sapa trekking tours", location="US", volume=500, confidence="dfs"),
        required_h2s=["Sapa Trekking Tours: what it's actually like"],
        atoms_by_section={}, faq_candidates=[],
        framework="hub", cta_target="https://aa.example.com/tours/sapa",
    )
    defaults.update(overrides)
    return Brief(**defaults)


# =================================================================== AA-404 Part 2: _select_atoms_for_channel

def test_select_atoms_for_channel_facebook_keeps_only_first_cited_atom():
    cited = {"atom_a": "text a", "atom_b": "text b", "atom_c": "text c"}
    result = _select_atoms_for_channel(cited, "facebook")
    assert result == {"atom_a": "text a"}


def test_select_atoms_for_channel_tiktok_keeps_every_cited_atom():
    cited = {"atom_a": "text a", "atom_b": "text b", "atom_c": "text c"}
    result = _select_atoms_for_channel(cited, "tiktok")
    assert result == cited


def test_select_atoms_for_channel_facebook_empty_when_nothing_cited():
    assert _select_atoms_for_channel({}, "facebook") == {}


# =================================================================== E3 adapt_channels

_BLOG_BODY = (
    "## Sapa Trekking Tours: what it's actually like\n\n"
    "The trek passes 3 ethnic minority villages over 2 days [R:atom_a]. "
    "Homestay dinner is cooked by the host family, not a restaurant [R:atom_b].\n"
)
_ATOM_TEXT = {
    "atom_a": "The trek passes 3 ethnic minority villages over 2 days.",
    "atom_b": "Homestay dinner is cooked by the host family, not a restaurant.",
    "atom_unused": "This atom is never cited in the blog body.",
}


def _fb_response(text_body="Great villages and home-cooked dinners [R:atom_a]."):
    return _sonnet_result(f"{text_body}\nHASHTAGS: #sapa #trekking #vietnam")


def _tiktok_response():
    return _sonnet_result(
        "HOOK: You won't believe this Sapa homestay dinner.\n"
        "SCRIPT: The trek passes 3 ethnic minority villages over 2 days [R:atom_a], and dinner is "
        "cooked by the host family, not a restaurant [R:atom_b].\n"
        "VISUAL: Wide shot of terraced hills, then close-up of home-cooked dinner table."
    )


def test_adapt_channels_both_succeed():
    blog = _blog_piece(_BLOG_BODY)
    with patch("services.acp_produce.adapt.invoke_claude",
               side_effect=[_fb_response(), _tiktok_response()]) as mock_invoke:
        pieces = adapt_channels(blog, _ATOM_TEXT)

    assert mock_invoke.call_count == 2
    by_channel = {p.channel: p for p in pieces}
    assert set(by_channel) == {"facebook", "tiktok"}
    assert by_channel["facebook"].piece_id == "piece-1#facebook"
    assert by_channel["tiktok"].piece_id == "piece-1#tiktok"
    assert "HASHTAGS:" in by_channel["facebook"].body_tagged
    assert "HOOK:" in by_channel["tiktok"].body_tagged


def test_adapt_channels_only_passes_cited_atoms_in_prompt():
    """AA-404 Part 2 note: facebook's call is checked separately below
    (test_adapt_channels_facebook_prompt_has_only_one_atom) now that facebook
    gets a single-atom ceiling — this test covers tiktok, which still gets
    every cited atom, plus confirms neither call ever leaks an uncited atom."""
    blog = _blog_piece(_BLOG_BODY)
    with patch("services.acp_produce.adapt.invoke_claude",
               side_effect=[_fb_response(), _tiktok_response()]) as mock_invoke:
        adapt_channels(blog, _ATOM_TEXT)

    fb_call, tiktok_call = mock_invoke.call_args_list
    fb_prompt = fb_call.args[0] if fb_call.args else fb_call.kwargs["prompt"]
    tiktok_prompt = tiktok_call.args[0] if tiktok_call.args else tiktok_call.kwargs["prompt"]

    assert "atom_unused" not in fb_prompt and "atom_unused" not in tiktok_prompt
    assert "atom_a" in tiktok_prompt and "atom_b" in tiktok_prompt


def test_adapt_channels_facebook_prompt_has_only_one_atom():
    """AA-404 Part 2: hook_story_cta's "one atom, one emotion" F8 criterion
    fails in real production data because facebook was handed every atom the
    blog cited. Fixed at the data layer — the "ATOMS YOU MAY CITE" listing in
    the facebook prompt must only ever contain the FIRST cited atom (atom_a,
    per _BLOG_BODY's citation order), never a listing line for atom_b — even
    though the raw BLOG TEXT block (given for context, unchanged) still shows
    the original [R:atom_b] tag as part of the source article being adapted."""
    blog = _blog_piece(_BLOG_BODY)
    with patch("services.acp_produce.adapt.invoke_claude",
               side_effect=[_fb_response(), _tiktok_response()]) as mock_invoke:
        adapt_channels(blog, _ATOM_TEXT)

    fb_call = mock_invoke.call_args_list[0]
    fb_prompt = fb_call.args[0] if fb_call.args else fb_call.kwargs["prompt"]
    atoms_section = fb_prompt.split("ATOMS YOU MAY CITE")[1]
    assert "- atom_a:" in atoms_section
    assert "- atom_b:" not in atoms_section


def test_adapt_channels_model_is_sonnet_never_palmyra():
    blog = _blog_piece(_BLOG_BODY)
    with patch("services.acp_produce.adapt.invoke_claude",
               side_effect=[_fb_response(), _tiktok_response()]) as mock_invoke:
        adapt_channels(blog, _ATOM_TEXT)

    for call in mock_invoke.call_args_list:
        assert call.kwargs["model"] == "sonnet"


def test_adapt_channels_one_channel_fails_other_still_returned():
    blog = _blog_piece(_BLOG_BODY)
    with patch("services.acp_produce.adapt.invoke_claude",
               side_effect=[BedrockUnavailable("throttled")] * 3 + [_tiktok_response()]), \
         patch("services.acp_produce.adapt.time.sleep"):
        pieces = adapt_channels(blog, _ATOM_TEXT)

    assert len(pieces) == 1
    assert pieces[0].channel == "tiktok"


def test_adapt_channels_never_raises_when_both_fail():
    blog = _blog_piece(_BLOG_BODY)
    with patch("services.acp_produce.adapt.invoke_claude", side_effect=BedrockUnavailable("down")), \
         patch("services.acp_produce.adapt.time.sleep"):
        pieces = adapt_channels(blog, _ATOM_TEXT)
    assert pieces == []


def test_adapt_channels_unparseable_response_treated_as_failure_then_retried():
    blog = _blog_piece(_BLOG_BODY)
    with patch("services.acp_produce.adapt.invoke_claude",
               side_effect=[_sonnet_result("no hashtags line here"), _fb_response(), _tiktok_response()]), \
         patch("services.acp_produce.adapt.time.sleep"):
        pieces = adapt_channels(blog, _ATOM_TEXT)

    by_channel = {p.channel: p for p in pieces}
    assert "facebook" in by_channel  # retry succeeded on 2nd attempt
    assert "tiktok" in by_channel


def test_facebook_adapt_output_passes_f1_grounding_when_grounded():
    blog = _blog_piece(_BLOG_BODY)
    with patch("services.acp_produce.adapt.invoke_claude",
               side_effect=[_fb_response(), _tiktok_response()]):
        pieces = adapt_channels(blog, _ATOM_TEXT)

    fb = next(p for p in pieces if p.channel == "facebook")
    result = gate_grounding(fb.body_tagged, set(_ATOM_TEXT), _ATOM_TEXT)
    assert result.passed is True


def test_facebook_adapt_output_fails_f1_grounding_on_fabricated_number():
    blog = _blog_piece(_BLOG_BODY)
    fabricated = _fb_response("This trek has 47 secret waterfalls [R:atom_a].")
    with patch("services.acp_produce.adapt.invoke_claude", side_effect=[fabricated, _tiktok_response()]):
        pieces = adapt_channels(blog, _ATOM_TEXT)

    fb = next(p for p in pieces if p.channel == "facebook")
    result = gate_grounding(fb.body_tagged, set(_ATOM_TEXT), _ATOM_TEXT)
    assert result.passed is False


# =================================================================== E4 answer_faq / apply_faq

def _faq_marker_block(n: int, answer: str) -> str:
    return f"===FAQ:{n}===\n{answer}\n"


def test_answer_faq_empty_candidates_no_llm_call():
    with patch("services.acp_produce.faq.invoke_claude", side_effect=AssertionError("must not be called")):
        items = answer_faq([], _ATOM_TEXT)
    assert items == []


def test_answer_faq_single_batch_happy_path():
    candidates = [
        FAQCandidate(question="Is it safe for beginners?", source_id="atom_a"),
        FAQCandidate(question="What's dinner like?", source_id="atom_b"),
    ]
    response_text = (
        _faq_marker_block(0, "Yes — the trek passes 3 ethnic minority villages over 2 days [R:atom_a].")
        + _faq_marker_block(1, "Dinner is cooked by the host family, not a restaurant [R:atom_b].")
    )
    with patch("services.acp_produce.faq.invoke_claude", return_value=_sonnet_result(response_text)) as mock_invoke:
        items = answer_faq(candidates, _ATOM_TEXT)

    mock_invoke.assert_called_once()
    assert mock_invoke.call_args.kwargs["model"] == "sonnet"
    assert len(items) == 2
    assert items[0].question == "Is it safe for beginners?"
    assert items[0].source_id == "atom_a"
    assert "[R:atom_a]" in items[0].answer
    assert items[1].source_id == "atom_b"


def test_answer_faq_raises_on_unparseable_response():
    candidates = [FAQCandidate(question="Is it safe?", source_id="atom_a")]
    with patch("services.acp_produce.faq.invoke_claude", return_value=_sonnet_result("no markers here")):
        with pytest.raises(FAQAnswerFailed):
            answer_faq(candidates, _ATOM_TEXT)


def test_answer_faq_raises_after_max_retries():
    candidates = [FAQCandidate(question="Is it safe?", source_id="atom_a")]
    with patch("services.acp_produce.faq.invoke_claude", side_effect=BedrockUnavailable("throttled")) as mock_invoke, \
         patch("services.acp_produce.faq.time.sleep"):
        with pytest.raises(FAQAnswerFailed):
            answer_faq(candidates, _ATOM_TEXT)
    assert mock_invoke.call_count == 3


def test_render_faq_section_keeps_citation_tags():
    items = [FAQItem(question="Is it safe?", answer="Yes, very [R:atom_a].", source_id="atom_a")]
    section = render_faq_section(items)
    assert section.startswith("## FAQ")
    assert "**Q: Is it safe?**" in section
    assert "[R:atom_a]" in section


def test_render_faq_section_empty_list_returns_empty_string():
    assert render_faq_section([]) == ""


def test_build_faq_jsonld_strips_citation_tags():
    items = [FAQItem(question="Is it safe?", answer="Yes, very [R:atom_a].", source_id="atom_a")]
    jsonld = build_faq_jsonld(items)
    assert jsonld["@type"] == "FAQPage"
    entity = jsonld["mainEntity"][0]
    assert entity["@type"] == "Question"
    assert entity["name"] == "Is it safe?"
    assert entity["acceptedAnswer"]["text"] == "Yes, very ."
    assert "[R:" not in entity["acceptedAnswer"]["text"]


def test_build_faq_jsonld_empty_list_returns_none():
    assert build_faq_jsonld([]) is None


def test_apply_faq_no_candidates_is_noop_no_llm_call():
    blog = _blog_piece(_BLOG_BODY)
    brief = _brief(faq_candidates=[])
    with patch("services.acp_produce.faq.invoke_claude", side_effect=AssertionError("must not be called")):
        result = apply_faq(blog, brief, _ATOM_TEXT)
    assert result.body_tagged == _BLOG_BODY
    assert result.faq_items == []
    assert result.faq_jsonld is None


def test_apply_faq_appends_section_and_sets_fields():
    blog = _blog_piece(_BLOG_BODY)
    brief = _brief(faq_candidates=[FAQCandidate(question="Is it safe?", source_id="atom_a")])
    response_text = _faq_marker_block(0, "Yes, the trail is well-guided [R:atom_a].")
    with patch("services.acp_produce.faq.invoke_claude", return_value=_sonnet_result(response_text)):
        result = apply_faq(blog, brief, _ATOM_TEXT)

    assert result is blog  # mutates + returns the same object
    assert result.body_tagged.startswith(_BLOG_BODY.rstrip())
    assert "## FAQ" in result.body_tagged
    assert "[R:atom_a]" in result.body_tagged
    assert len(result.faq_items) == 1
    assert result.faq_jsonld["mainEntity"][0]["name"] == "Is it safe?"


def test_apply_faq_output_passes_f1_grounding_when_grounded():
    blog = _blog_piece(_BLOG_BODY)
    brief = _brief(faq_candidates=[FAQCandidate(question="Is it safe?", source_id="atom_a")])
    response_text = _faq_marker_block(0, "Yes, it passes 3 ethnic minority villages [R:atom_a].")
    with patch("services.acp_produce.faq.invoke_claude", return_value=_sonnet_result(response_text)):
        result = apply_faq(blog, brief, _ATOM_TEXT)

    gate_result = gate_grounding(result.body_tagged, set(_ATOM_TEXT), _ATOM_TEXT)
    assert gate_result.passed is True


def test_apply_faq_output_fails_f1_grounding_on_fabricated_number():
    blog = _blog_piece(_BLOG_BODY)
    brief = _brief(faq_candidates=[FAQCandidate(question="Is it safe?", source_id="atom_a")])
    response_text = _faq_marker_block(0, "Yes, over 500 travelers do it safely each month [R:atom_a].")
    with patch("services.acp_produce.faq.invoke_claude", return_value=_sonnet_result(response_text)):
        result = apply_faq(blog, brief, _ATOM_TEXT)

    gate_result = gate_grounding(result.body_tagged, set(_ATOM_TEXT), _ATOM_TEXT)
    assert gate_result.passed is False


# =================================================================== AA-404 writer-side wire: brand_rubric_text

_REAL_RUBRIC = "REAL AA_INTERNAL BRAND RUBRIC — calm, assured, curated."


def test_adapt_channels_defaults_to_generic_brand_prompt_when_not_passed():
    """No `brand_rubric_text` argument (every pre-AA-404 caller/test) must
    reproduce the exact pre-AA-404 system prompt for both channels."""
    blog = _blog_piece(_BLOG_BODY)
    with patch("services.acp_produce.adapt.invoke_claude",
               side_effect=[_fb_response(), _tiktok_response()]) as mock_invoke:
        adapt_channels(blog, _ATOM_TEXT)

    for call in mock_invoke.call_args_list:
        assert AA_BRAND_IDENTITY_PROMPT.strip() in call.kwargs["system"]


def test_adapt_channels_uses_real_tenant_brand_rubric_when_passed():
    """AA-404 F9 deep-dive TL;DR #1: E3 must adapt against the SAME real
    per-tenant rubric F9's judge scores it against, for BOTH channels, once
    the caller (slot_runner.py) has one to pass."""
    blog = _blog_piece(_BLOG_BODY)
    with patch("services.acp_produce.adapt.invoke_claude",
               side_effect=[_fb_response(), _tiktok_response()]) as mock_invoke:
        adapt_channels(blog, _ATOM_TEXT, _REAL_RUBRIC)

    for call in mock_invoke.call_args_list:
        assert _REAL_RUBRIC in call.kwargs["system"]
        assert AA_BRAND_IDENTITY_PROMPT.strip() not in call.kwargs["system"]


def test_answer_faq_defaults_to_generic_brand_prompt_when_not_passed():
    candidates = [FAQCandidate(question="Is it safe for beginners?", source_id="atom_a")]
    response_text = _faq_marker_block(0, "Yes [R:atom_a].")
    with patch("services.acp_produce.faq.invoke_claude", return_value=_sonnet_result(response_text)) as mock_invoke:
        answer_faq(candidates, _ATOM_TEXT)

    assert AA_BRAND_IDENTITY_PROMPT.strip() in mock_invoke.call_args.kwargs["system"]


def test_answer_faq_uses_real_tenant_brand_rubric_when_passed():
    """AA-404 F9 deep-dive TL;DR #1: E4 must answer against the SAME real
    per-tenant rubric F9's judge scores it against."""
    candidates = [FAQCandidate(question="Is it safe for beginners?", source_id="atom_a")]
    response_text = _faq_marker_block(0, "Yes [R:atom_a].")
    with patch("services.acp_produce.faq.invoke_claude", return_value=_sonnet_result(response_text)) as mock_invoke:
        answer_faq(candidates, _ATOM_TEXT, _REAL_RUBRIC)

    system = mock_invoke.call_args.kwargs["system"]
    assert _REAL_RUBRIC in system
    assert AA_BRAND_IDENTITY_PROMPT.strip() not in system


def test_apply_faq_threads_real_rubric_through_to_answer_faq():
    blog = _blog_piece(_BLOG_BODY)
    brief = _brief(faq_candidates=[FAQCandidate(question="Is it safe?", source_id="atom_a")])
    response_text = _faq_marker_block(0, "Yes, the trail is well-guided [R:atom_a].")
    with patch("services.acp_produce.faq.invoke_claude", return_value=_sonnet_result(response_text)) as mock_invoke:
        apply_faq(blog, brief, _ATOM_TEXT, _REAL_RUBRIC)

    assert _REAL_RUBRIC in mock_invoke.call_args.kwargs["system"]
