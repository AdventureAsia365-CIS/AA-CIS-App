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
