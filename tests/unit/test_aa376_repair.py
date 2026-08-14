"""
tests/unit/test_aa376_repair.py — services/acp_produce/repair.py
(AA-376: E5 repair_piece(), the LLM rewrite call wired into run_gates()'s
repair_fn slot).

No live Bedrock calls — shared.llm_client.bedrock_satellite.invoke_claude is
mocked throughout, same convention as test_aa370_generation.py.
"""
from unittest.mock import patch

import pytest

from services.acp_produce.repair import RepairFailed, repair_piece
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
