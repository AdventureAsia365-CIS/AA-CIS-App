"""AA-224: Bedrock streaming invoke + usage accumulation."""
import json
from unittest.mock import patch, MagicMock
import pytest
from shared.llm_client.client import LLMClient
from shared.llm_client.models import LLMRequest


def _event(d):
    return {"chunk": {"bytes": json.dumps(d).encode()}}


def _fake_stream(text="Hello world.", in_tok=1200, out_tok=342, cache_read=800, cache_write=0):
    return [
        _event({"type": "message_start", "message": {"usage": {
            "input_tokens": in_tok,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
        }}}),
        _event({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        _event({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[:5]}}),
        _event({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[5:]}}),
        _event({"type": "content_block_stop", "index": 0}),
        _event({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": out_tok}}),
        _event({"type": "message_stop"}),
    ]


def _client_with_stream(events):
    with patch("shared.llm_client.client.boto3.client"), \
         patch("shared.llm_client.client.openai.OpenAI"):
        client = LLMClient()
    mock_bedrock = MagicMock()
    mock_bedrock.invoke_model_with_response_stream.return_value = {"body": iter(events)}
    client._bedrock = mock_bedrock
    return client


def _req():
    return LLMRequest(system_prompt="sys", user_prompt="write a tour", model_tier="sonnet")


def test_streaming_accumulates_content_and_usage():
    client = _client_with_stream(_fake_stream(text="Hello world.", in_tok=1200, out_tok=342))
    resp = client._call_bedrock(_req(), model="us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert resp.content == "Hello world."
    assert resp.input_tokens == 1200
    assert resp.output_tokens == 342
    assert resp.model_used == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert resp.provider == "bedrock"


def test_streaming_uses_response_stream_not_blocking_invoke():
    client = _client_with_stream(_fake_stream())
    client._call_bedrock(_req(), model="m")
    client._bedrock.invoke_model_with_response_stream.assert_called_once()
    assert not client._bedrock.invoke_model.called


def test_streaming_empty_delta_yields_empty_content_not_crash():
    events = [
        _event({"type": "message_start", "message": {"usage": {"input_tokens": 10}}}),
        _event({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {}}),
        _event({"type": "message_stop"}),
    ]
    client = _client_with_stream(events)
    resp = client._call_bedrock(_req(), model="m")
    assert resp.content == ""
    assert resp.input_tokens == 10
    assert resp.output_tokens == 0
