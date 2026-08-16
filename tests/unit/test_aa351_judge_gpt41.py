"""
tests/unit/test_aa351_judge_gpt41.py — AA-351-03 GPT-4.1 alternative judge backend
(services/acp_produce/judge_client.py::invoke_judge_gpt41()).

Covers: (1) invoke_judge() still defaults to Nova Pro when JUDGE_MODEL is unset and no
explicit model= is passed — production behavior (every gates.py call site) is unchanged
by this addition, same as AA-351-02's gpt56 backend before it; (2) explicit model="gpt41"
and the JUDGE_MODEL env var both route to the new backend; (3) the GPT-4.1 path uses a
direct openai.OpenAI client (same construction judge_node.py already runs in production),
NOT Bedrock/boto3, and NOT the full LLMClient.generate() fallback chain; (4) response
parsing produces the same {text, model_used, provider, input_tokens, output_tokens} shape
the Nova Pro/GPT-5.6 paths return, so gates.py's parsing code needs no changes for any of
the three backends; (5) gpt56 selection still works unchanged (no regression from adding
the gpt41 branch alongside it).
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from services.acp_produce.judge_client import (
    GPT41_MODEL, GPT56_SOL_INFERENCE_PROFILE, NOVA_PRO_MODEL_ID, invoke_judge,
    invoke_judge_gpt41,
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


def _openai_response(text: str, in_tok: int = 18, out_tok: int = 9):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    resp.usage = MagicMock(prompt_tokens=in_tok, completion_tokens=out_tok)
    return resp


def test_invoke_judge_defaults_to_nova_pro_when_env_unset(monkeypatch):
    """No JUDGE_MODEL env var, no explicit model= -- must still be Nova Pro
    (the production path every gates.py call site relies on), unaffected by
    the gpt41 branch existing alongside gpt56."""
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _nova_response('{"ok": true}')
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result = invoke_judge("system", "user")
    assert result["model_used"] == NOVA_PRO_MODEL_ID


def test_invoke_judge_explicit_model_param_routes_to_gpt41():
    fake_openai_client = MagicMock()
    fake_openai_client.chat.completions.create.return_value = _openai_response('{"ok": true}')
    with patch("openai.OpenAI", return_value=fake_openai_client) as mock_openai:
        result = invoke_judge("system", "user", model="gpt41")
    mock_openai.assert_called_once()
    assert result["model_used"] == GPT41_MODEL
    assert result["provider"] == "openai"


def test_invoke_judge_env_var_routes_to_gpt41(monkeypatch):
    monkeypatch.setenv("JUDGE_MODEL", "gpt41")
    fake_openai_client = MagicMock()
    fake_openai_client.chat.completions.create.return_value = _openai_response('{"ok": true}')
    with patch("openai.OpenAI", return_value=fake_openai_client):
        result = invoke_judge("system", "user")
    assert result["model_used"] == GPT41_MODEL


def test_invoke_judge_gpt56_still_works_unaffected_by_gpt41_addition():
    """Regression guard: adding the gpt41 branch must not disturb gpt56 routing
    (AA-351-02, still blocked on AWS access but the code path itself must stay intact)."""
    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {"message": {"role": "assistant", "content": [{"text": '{"ok": true}'}]}},
        "usage": {"inputTokens": 15, "outputTokens": 8},
    }
    with patch("shared.llm_client.bedrock_satellite.get_satellite_client", return_value=fake_client):
        result = invoke_judge("system", "user", model="gpt56")
    assert result["model_used"] == GPT56_SOL_INFERENCE_PROFILE


def test_invoke_judge_gpt41_uses_direct_openai_client_not_bedrock():
    """GPT-4.1 here is a direct OpenAI call -- boto3/Bedrock must never be touched
    for this backend."""
    fake_openai_client = MagicMock()
    fake_openai_client.chat.completions.create.return_value = _openai_response('{"status": "pass"}')
    with patch("openai.OpenAI", return_value=fake_openai_client) as mock_openai, \
            patch("services.acp_produce.judge_client.boto3.client") as mock_boto:
        invoke_judge_gpt41("system prompt", "user prompt")
    mock_openai.assert_called_once()
    mock_boto.assert_not_called()
    call_kwargs = fake_openai_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == GPT41_MODEL
    assert call_kwargs["temperature"] == 0
    assert call_kwargs["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]


def test_invoke_judge_gpt41_parses_usage_and_text():
    fake_openai_client = MagicMock()
    fake_openai_client.chat.completions.create.return_value = _openai_response(
        '{"status": "flagged"}', in_tok=42, out_tok=17,
    )
    with patch("openai.OpenAI", return_value=fake_openai_client):
        result = invoke_judge_gpt41("system", "user")
    assert result["text"] == '{"status": "flagged"}'
    assert result["input_tokens"] == 42
    assert result["output_tokens"] == 17


def test_judge_client_still_never_imports_generation_or_writer_modules():
    """AA-351-03's addition must not weaken the existing isolation guarantee
    (ADR-2026-014/027 L3) -- re-run the same structural check with the new
    gpt41 function present, same as AA-351-02's own re-run of this check."""
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
