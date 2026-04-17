"""
Prompt Caching Layer — 2 levels:
L1: System prompt cache (static, reused across all tours)
L2: Few-shot examples cache (semi-static, reused per batch)
Anthropic cache_control: ephemeral (5 min TTL on their side)
"""
from typing import Any

def build_cached_system_prompt(system_text: str) -> list[dict]:
    """L1 cache — system prompt marked for Anthropic prompt caching."""
    return [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]

def build_cached_messages(
    few_shots: list[dict],
    user_prompt: str,
) -> list[dict]:
    """
    L2 cache — few-shot examples cached, user prompt NOT cached.
    Structure:
      [cached few-shots block] + [non-cached user prompt]
    """
    messages = []

    if few_shots:
        few_shot_text = "\n\n".join([
            f"EXAMPLE {i+1}:\nINPUT: {f['input']}\nOUTPUT: {f['output']}"
            for i, f in enumerate(few_shots[:3])
        ])
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"REFERENCE EXAMPLES:\n{few_shot_text}",
                    "cache_control": {"type": "ephemeral"},  # L2 cache
                },
                {
                    "type": "text",
                    "text": user_prompt,  # NOT cached — changes per tour
                },
            ]
        })
    else:
        messages.append({
            "role": "user",
            "content": user_prompt,
        })

    return messages
