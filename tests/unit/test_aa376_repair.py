"""
tests/unit/test_aa376_repair.py — services/acp_produce/repair.py
(AA-376: E5 repair_piece(), the LLM rewrite call wired into run_gates()'s
repair_fn slot).

No live Bedrock calls — shared.llm_client.bedrock_satellite.invoke_claude is
mocked throughout, same convention as test_aa370_generation.py.
"""
from unittest.mock import patch

import pytest

from services.acp_produce.repair import PieceInvariants, RepairFailed, repair_piece
from services.content_generation.brand_standards import AA_BRAND_IDENTITY_PROMPT
from shared.llm_client.bedrock_satellite import BedrockInvokeResult, BedrockUnavailable


def _sonnet_result(text: str) -> BedrockInvokeResult:
    return BedrockInvokeResult(text=text, model_used="sonnet-4-6", latency_ms=500.0,
                                usage={"input_tokens": 400, "output_tokens": 380})


def test_repair_piece_happy_path_returns_full_rewritten_body():
    body = "The trek passes 22 hidden waterfalls [R:atom_a]."
    violations = ["sentence states '22' not present in its cited id(s)"]
    fixed = "The trek passes several hidden waterfalls [R:atom_a]."

    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result(fixed)) as mock_invoke:
        result = repair_piece(body, violations)

    assert result == fixed
    assert mock_invoke.call_args.kwargs["model"] == "sonnet"
    prompt = mock_invoke.call_args.args[0]
    assert body in prompt
    assert violations[0] in prompt


def test_repair_piece_prompt_carries_every_violation():
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result("fixed body")) as mock_invoke:
        repair_piece("some body", ["violation one", "violation two"])

    prompt = mock_invoke.call_args.args[0]
    assert "violation one" in prompt
    assert "violation two" in prompt


def test_repair_piece_retries_then_succeeds():
    with patch("services.acp_produce.repair.invoke_claude",
               side_effect=[BedrockUnavailable("throttled"), _sonnet_result("fixed body")]) as mock_invoke, \
         patch("services.acp_produce.repair.time.sleep"):
        result = repair_piece("broken body", ["v1"])

    assert result == "fixed body"
    assert mock_invoke.call_count == 2


def test_repair_piece_raises_repair_failed_after_max_retries():
    with patch("services.acp_produce.repair.invoke_claude",
               side_effect=BedrockUnavailable("throttled")) as mock_invoke, \
         patch("services.acp_produce.repair.time.sleep"):
        with pytest.raises(RepairFailed):
            repair_piece("broken body", ["v1"])

    assert mock_invoke.call_count == 3


def test_repair_piece_strips_whitespace_from_response():
    with patch("services.acp_produce.repair.invoke_claude",
               return_value=_sonnet_result("  \n  fixed body with padding  \n  ")):
        result = repair_piece("body", ["v1"])
    assert result == "fixed body with padding"


def test_repair_piece_prompt_includes_full_reason_string_with_notes():
    """AA-396 fix 1: gates.py now folds the judge's `notes` into the
    violation string it hands to repair_fn, not just the terse failure
    codes (see gates.py::_format_audit_reason). Confirm repair's prompt
    actually carries that fuller string through -- gates.py building it is
    only half the fix, this is the "does repair actually read it" half."""
    violation_with_notes = (
        "audit flagged: SUMMARY_OFF_BRAND -- opens with a generic AI-sounding "
        "preamble before the first real fact"
    )
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result("fixed body")) as mock_invoke:
        repair_piece("some body", [violation_with_notes])

    prompt = mock_invoke.call_args.args[0]
    assert "opens with a generic AI-sounding preamble" in prompt


# ── AA-396: leaked-reasoning sanity guard (piece-7 class) ─────────────────

# Reconstructed verbatim from the real held piece
# 737b28f9-...:slot_4139d8506f2e56427a49:blog (docs/implementation-notes/
# AA-391-report-data.json) -- a real Sonnet repair call returned its own
# chain-of-thought about why it couldn't act instead of a repaired body, and
# that text got persisted as the piece's actual content.
_PIECE7_LEAKED_PREFIX = (
    "Looking at the violations, I need to identify where these fields appear in the text. "
    "The current text is a summary/editorial piece — it does not contain discrete "
    "AA_HIGHLIGHTS, AA_ITINERARIES, SEO_TITLE, or SEO_META fields as separate labeled "
    "sections. The violations reference fields that are absent from this text entirely, "
    "which means they cannot be repaired within this document as written."
)


def test_repair_piece_rejects_leaked_reasoning_real_aa396_fixture():
    """The guard must catch the exact corruption shape seen in real
    production data and raise RepairFailed rather than let it through as a
    successful repair."""
    leaked = (
        _PIECE7_LEAKED_PREFIX
        + "\n\nHowever, re-reading carefully:\n\n## Some Heading\n\nReal content would follow here."
    )
    with patch("services.acp_produce.repair.invoke_claude",
               return_value=_sonnet_result(leaked)) as mock_invoke:
        with pytest.raises(RepairFailed):
            repair_piece("original body", ["v1"])
    assert mock_invoke.call_count == 1  # no wasted retries once a leak is detected


def test_repair_piece_does_not_false_flag_legitimate_travel_content():
    """A real repaired blog piece that happens to discuss itinerary
    structure as actual travel content -- not as meta-commentary about the
    repair task -- must not trip the guard. Only the specific
    self-referential "I couldn't do this" phrasing from the real leak
    should ever match."""
    legit = (
        "South Korea's temple architecture follows a deliberate structure, one that "
        "rewards close attention to the itinerary of a single day rather than a rushed "
        "circuit. [R:atom_a]\n\n"
        "## Day 3 -- Temple Stay\n\nGuests spend the morning in guided meditation before "
        "a quiet walk through the temple grounds."
    )
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result(legit)):
        result = repair_piece("original body", ["v1"])
    assert result == legit


# ── AA-404: PieceInvariants — general fix for the repair.py blind spot ────
#
# STEP 0 (docs/implementation-notes/AA-404.md's "mở rộng" section, 45 real
# pieces across 4 N7 runs) found repair_piece() previously received only
# (body_tagged, violations) -- the first failing gate's own narrow view --
# so a repair round fixing one gate had zero visibility into ANOTHER gate's
# piece-wide requirements and could silently regress it. Confirmed real: 14
# events / 13 pieces, 4 causal pairs (F9-social->F8 6x, F4->F3 3x,
# F9-blog->F4 3x, F4->F2 2x). These tests cover the two real shapes named in
# the AA-404 task text, plus the other invariant fields for completeness.

def test_repair_piece_with_no_invariants_matches_pre_aa404_prompt_shape():
    """`invariants` defaults to None -- every caller/test that predates
    AA-404 (including every test above this section) must see the exact
    same prompt shape as before: no STRUCTURAL CONTEXT block at all."""
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result("fixed")) as mock_invoke:
        repair_piece("some body", ["some violation"])
    prompt = mock_invoke.call_args.args[0]
    assert "STRUCTURAL CONTEXT" not in prompt


def test_repair_prompt_preserves_cta_when_f9_social_repair_triggers():
    """Real case (a): a facebook piece held on F9_brand_seo_audit_social
    (GENERIC_AI_WORDING) -- a violation that has NOTHING to do with the CTA
    -- must still see the CTA preservation instruction in its repair prompt,
    because `invariants.cta_required=True` for a hook_story_cta piece
    regardless of which gate actually triggered this round. This is the
    real F9-social -> F8 pattern (6x, the single dominant regression in the
    45-piece corpus)."""
    body = "Sunrise over the old quarter [R:atom_1]. Design This Journey.\nHASHTAGS: #travel"
    invariants = PieceInvariants(channel="facebook", single_atom_required=True, cta_required=True)
    f9_violation = "audit flagged: GENERIC_AI_WORDING -- opens with a generic AI-sounding phrase"

    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result(body)) as mock_invoke:
        repair_piece(body, [f9_violation], invariants=invariants)

    prompt = mock_invoke.call_args.args[0]
    assert "STRUCTURAL CONTEXT" in prompt
    assert "Design This Journey" in prompt
    assert "REQUIRES ending on the exact brand CTA phrase" in prompt
    # the violation itself is unrelated to the CTA -- confirms the CTA note
    # is present BECAUSE of the invariant, not because of the violation text
    assert "cta" not in f9_violation.lower()


def test_repair_prompt_preserves_single_atom_when_f9_social_repair_triggers():
    """Same real F9-social -> F8 pattern, the "one atom, one emotion"
    sub-criterion: the prompt must tell repair to keep citing only the
    atom(s) already present, re-derived from the CURRENT body (not a stale
    stored id)."""
    body = "Sunrise over the old quarter [R:atom_1]. Design This Journey.\nHASHTAGS: #travel"
    invariants = PieceInvariants(channel="facebook", single_atom_required=True, cta_required=True)

    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result(body)) as mock_invoke:
        repair_piece(body, ["audit flagged: GENERIC_AI_WORDING"], invariants=invariants)

    prompt = mock_invoke.call_args.args[0]
    assert "single-atom piece" in prompt
    assert "[R:atom_1]" in prompt.split("STRUCTURAL CONTEXT")[1]  # cited in the invariant note itself


def test_repair_prompt_preserves_section_balance_when_f4_repair_triggers():
    """Real case (b): a blog piece held on F4_brief_compliance (a missing
    required H2) -- a violation about a MISSING section, not length balance
    -- must still see the section-ownership note in its repair prompt, so a
    repair that adds/restructures a section doesn't blindly grow it into a
    second "longest" section and break F3's >=1.4x ratio. This is the real
    F4 -> F3 pattern (3x)."""
    body = "## Intro\n\nShort intro.\n\n## Details\n\nMore detail here."
    invariants = PieceInvariants(
        channel="blog",
        long_section_title="Details",
        short_para_section_title="Intro",
        required_h2s=["Intro", "Details", "Wrap-up"],
    )
    f4_violation = 'required H2 "Wrap-up" not found in body'

    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result(body)) as mock_invoke:
        repair_piece(body, [f4_violation], invariants=invariants)

    prompt = mock_invoke.call_args.args[0]
    assert "STRUCTURAL CONTEXT" in prompt
    assert '"## Details" section was deliberately written to run' in prompt
    assert '"## Intro" section carries the piece\'s one required short' in prompt
    assert 'required section headings are: "Intro", "Details", "Wrap-up"' in prompt
    # the violation itself is about a missing heading, not length balance --
    # confirms the balance note is present because of the invariant
    assert "notably longer" not in f4_violation.lower()


def test_repair_prompt_carries_aida_opening_closing_notes():
    """F8 AIDA (blog): same class of gap as F3's -- structurally identical
    exposure, no real regression yet (STEP 0), included so it doesn't need
    a follow-up patch once real data catches it."""
    body = "## Hook\n\nOpening.\n\n## Middle\n\nMore.\n\n## Close\n\nEnd."
    invariants = PieceInvariants(
        channel="blog", aida_opening_section_title="Hook", aida_closing_section_title="Close",
    )
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result(body)) as mock_invoke:
        repair_piece(body, ["some unrelated violation"], invariants=invariants)

    prompt = mock_invoke.call_args.args[0]
    assert '"## Hook" section is this piece\'s OPENING' in prompt
    assert '"## Close" section is this piece\'s CLOSING' in prompt


def test_repair_prompt_ends_with_cta_violation_gets_explicit_hint_even_without_invariants():
    """AA-404 STEP 0's own finding: the terse 'ends with CTA' violation
    string never connected to the brand block's one-line CTA mention
    elsewhere in context. This hint fires off the violation TEXT itself
    (gates.py::_ends_with_cta() is the only check that emits this string),
    so it's defense-in-depth even when `invariants` is None."""
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result("fixed")) as mock_invoke:
        repair_piece("some body", ["framework criterion failed: ends with CTA"])

    prompt = mock_invoke.call_args.args[0]
    assert 'HINT for the "ends with CTA" violation' in prompt
    assert "Design This Journey" in prompt


def test_repair_prompt_no_fabricated_context_when_invariants_mostly_empty():
    """A `PieceInvariants` with only `channel` set (no applicable
    constraint for this piece, e.g. a tiktok piece) must produce NO
    STRUCTURAL CONTEXT block -- never invent guidance generation didn't
    actually set."""
    invariants = PieceInvariants(channel="tiktok")
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result("fixed")) as mock_invoke:
        repair_piece("some body", ["some violation"], invariants=invariants)

    prompt = mock_invoke.call_args.args[0]
    assert "STRUCTURAL CONTEXT" not in prompt


def test_repair_piece_backward_compatible_positional_call_still_works():
    """Confirms `invariants` is truly keyword-only and optional -- every
    existing caller (including pipeline.py pre-AA-404 callers/tests) that
    calls `repair_piece(body, violations)` positionally keeps working
    unchanged."""
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result("fixed body")):
        result = repair_piece("body", ["v1"])
    assert result == "fixed body"


# =================================================================== AA-404 writer-side wire: brand_rubric_text

def test_repair_piece_defaults_to_generic_brand_prompt_when_no_invariants():
    """No `invariants` (every pre-AA-404 caller/test) must reproduce the
    exact pre-AA-404 system prompt -- the generic `AA_BRAND_IDENTITY_PROMPT`
    constant."""
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result("fixed body")) as mock_invoke:
        repair_piece("some body", ["v1"])

    assert AA_BRAND_IDENTITY_PROMPT.strip() in mock_invoke.call_args.kwargs["system"]


def test_repair_piece_defaults_to_generic_brand_prompt_when_invariants_has_no_rubric():
    """`PieceInvariants()` with no `brand_rubric_text` override must also
    fall back to the generic constant (the field's own default)."""
    invariants = PieceInvariants(channel="tiktok")
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result("fixed body")) as mock_invoke:
        repair_piece("some body", ["v1"], invariants=invariants)

    assert AA_BRAND_IDENTITY_PROMPT.strip() in mock_invoke.call_args.kwargs["system"]


def test_repair_piece_uses_real_tenant_brand_rubric_from_invariants():
    """AA-404 F9 deep-dive TL;DR #1: E5 repair must rewrite against the SAME
    real per-tenant rubric F9's judge scores the repaired piece against —
    reuses the existing `PieceInvariants` mechanism (PR #154), not a new
    disconnected parameter."""
    real_rubric = "REAL AA_INTERNAL BRAND RUBRIC — calm, assured, curated."
    invariants = PieceInvariants(channel="blog", brand_rubric_text=real_rubric)
    with patch("services.acp_produce.repair.invoke_claude", return_value=_sonnet_result("fixed body")) as mock_invoke:
        repair_piece("some body", ["v1"], invariants=invariants)

    system = mock_invoke.call_args.kwargs["system"]
    assert real_rubric in system
    assert AA_BRAND_IDENTITY_PROMPT.strip() not in system
