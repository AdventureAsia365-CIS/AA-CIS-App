"""
tests/unit/test_aa351_judge_gpt56.py — AA-351 GPT-5.6 alternative judge backend
(services/acp_produce/judge_client.py::invoke_judge_gpt56()).

Covers: (1) invoke_judge()'s Nova Pro backend stays fully selectable via explicit
model="nova_pro" (AA-518, 02/09/2026, changed the DEFAULT to "gpt41" — see
test_aa351_judge_gpt41.py::test_invoke_judge_defaults_to_gpt41_when_env_unset --
Nova Pro itself is untouched, still selectable as a fallback); (2) explicit
model="gpt56" and the JUDGE_MODEL env var both
route to the new backend; (3) the GPT-5.6 path goes through the acc3 Bedrock
satellite session (get_satellite_client), NOT a fresh boto3 client, and uses
Converse (not invoke_model); (4) response parsing produces the same {text,
model_used, provider, input_tokens, output_tokens} shape the Nova Pro path
returns, so gates.py's parsing code needs no changes for either backend.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from services.acp_produce.judge_client import (
    GPT56_SOL_INFERENCE_PROFILE, NOVA_PRO_MODEL_ID, invoke_judge, invoke_judge_gpt56,
)


def _nova_response(text: str):
    payload = {
        "output": {"message": {"content": [{"text": text}], "role": "assistant"}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 20, "outputTokens": 10, "totalTokens": 30},
    }
    body = MagicMock()
    body.read.return_value = json.dumps(payload).encode()
    return {"body": body}


def _converse_response(text: str):
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 15, "outputTokens": 8, "totalTokens": 23},
    }


def test_invoke_judge_nova_pro_still_selectable_explicitly(monkeypatch):
    """AA-518 changed invoke_judge()'s DEFAULT away from Nova Pro (see
    test_aa351_judge_gpt41.py), but the backend itself is untouched --
    explicit model="nova_pro" must still route there."""
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _nova_response('{"ok": true}')
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client) as mock_boto:
        result = invoke_judge("system", "user", model="nova_pro")
    mock_boto.assert_called_once_with("bedrock-runtime", region_name="us-west-1")
    assert result["model_used"] == NOVA_PRO_MODEL_ID


def test_invoke_judge_explicit_model_param_routes_to_gpt56():
    fake_client = MagicMock()
    fake_client.converse.return_value = _converse_response('{"ok": true}')
    with patch("shared.llm_client.bedrock_satellite.get_satellite_client", return_value=fake_client) as mock_get:
        result = invoke_judge("system", "user", model="gpt56")
    mock_get.assert_called_once_with("bedrock-runtime", account="acc3")
    assert result["model_used"] == GPT56_SOL_INFERENCE_PROFILE
    assert result["provider"] == "bedrock-satellite-acc3"


def test_invoke_judge_env_var_routes_to_gpt56(monkeypatch):
    monkeypatch.setenv("JUDGE_MODEL", "gpt56")
    fake_client = MagicMock()
    fake_client.converse.return_value = _converse_response('{"ok": true}')
    with patch("shared.llm_client.bedrock_satellite.get_satellite_client", return_value=fake_client):
        result = invoke_judge("system", "user")
    assert result["model_used"] == GPT56_SOL_INFERENCE_PROFILE


def test_invoke_judge_explicit_model_param_overrides_env_var(monkeypatch):
    """model= kwarg (used by the AA-351 comparison script) must win over
    JUDGE_MODEL so a single process can call both backends in the same run
    without mutating env state between calls."""
    monkeypatch.setenv("JUDGE_MODEL", "gpt56")
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _nova_response('{"ok": true}')
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result = invoke_judge("system", "user", model="nova_pro")
    assert result["model_used"] == NOVA_PRO_MODEL_ID


def test_invoke_judge_gpt56_uses_converse_not_invoke_model():
    """GPT models on Bedrock only support Converse (AA-351 survey finding) --
    the satellite client's invoke_model must never be called for this path."""
    fake_client = MagicMock()
    fake_client.converse.return_value = _converse_response('{"status": "pass"}')
    with patch("shared.llm_client.bedrock_satellite.get_satellite_client", return_value=fake_client):
        invoke_judge_gpt56("system prompt", "user prompt")
    fake_client.converse.assert_called_once()
    fake_client.invoke_model.assert_not_called()
    call_kwargs = fake_client.converse.call_args.kwargs
    assert call_kwargs["modelId"] == GPT56_SOL_INFERENCE_PROFILE
    assert call_kwargs["system"] == [{"text": "system prompt"}]
    assert call_kwargs["messages"] == [{"role": "user", "content": [{"text": "user prompt"}]}]


def test_invoke_judge_gpt56_parses_usage_and_text():
    fake_client = MagicMock()
    fake_client.converse.return_value = _converse_response('{"status": "flagged"}')
    with patch("shared.llm_client.bedrock_satellite.get_satellite_client", return_value=fake_client):
        result = invoke_judge_gpt56("system", "user")
    assert result["text"] == '{"status": "flagged"}'
    assert result["input_tokens"] == 15
    assert result["output_tokens"] == 8


def test_judge_client_still_never_imports_generation_or_writer_modules():
    """AA-351's addition must not weaken the existing isolation guarantee
    (ADR-2026-014/027 L3) -- re-run the same structural check with the new
    functions present."""
    import ast
    import inspect

    from services.acp_produce import judge_client
    tree = ast.parse(inspect.getsource(judge_client))
    imported_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)
    assert not any("content_generation" in name for name in imported_names)
    assert not any("acp_produce.generation" in name for name in imported_names)
