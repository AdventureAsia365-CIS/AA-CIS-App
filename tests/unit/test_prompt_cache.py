import pytest
from shared.llm_client.prompt_cache import build_cached_system_prompt, build_cached_messages

def test_system_prompt_has_cache_control():
    result = build_cached_system_prompt("You are a travel writer.")
    assert len(result) == 1
    assert result[0]["cache_control"] == {"type": "ephemeral"}
    assert result[0]["text"] == "You are a travel writer."

def test_system_prompt_type_is_text():
    result = build_cached_system_prompt("System prompt here.")
    assert result[0]["type"] == "text"

def test_messages_with_few_shots_cached():
    few_shots = [{"input": "old name", "output": "refined name"}]
    messages  = build_cached_messages(few_shots, "Rewrite this tour.")
    assert len(messages) == 1
    content = messages[0]["content"]
    # L2 cache block
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert "REFERENCE EXAMPLES" in content[0]["text"]
    # User prompt NOT cached
    assert "cache_control" not in content[1]
    assert "Rewrite this tour." in content[1]["text"]

def test_messages_no_few_shots():
    messages = build_cached_messages([], "Rewrite this tour.")
    assert len(messages) == 1
    assert messages[0]["content"] == "Rewrite this tour."

def test_few_shots_max_3():
    few_shots = [{"input": f"in{i}", "output": f"out{i}"} for i in range(10)]
    messages  = build_cached_messages(few_shots, "prompt")
    content   = messages[0]["content"][0]["text"]
    assert "EXAMPLE 3" in content
    assert "EXAMPLE 4" not in content
