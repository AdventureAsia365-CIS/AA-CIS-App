"""Multi-provider LLM client for S4.2 Social Media Content Engine (AA-93).

Supports: bedrock (default), anthropic, openai.
Returns a callable: (system_prompt: str, user_prompt: str) → str
"""
from __future__ import annotations

import json
import os
from typing import Callable

SOCIAL_MODEL_BEDROCK = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
SOCIAL_MODEL_ANTHROPIC = "claude-sonnet-4-5-20251001"
SOCIAL_MODEL_OPENAI = "gpt-4o"


def make_llm_client(
    provider: str = "bedrock",
    model_id: str | None = None,
    token_log: list | None = None,
) -> Callable:
    """
    Factory: returns a callable (system, user) → str for the given provider.

    Args:
        provider:   'bedrock' | 'anthropic' | 'openai'
        model_id:   Override model ID (optional)
        token_log:  Optional list — bedrock client appends (input_tokens, output_tokens)
                    tuples so callers can sum cost after the run.
    """
    if provider == "bedrock":
        return _make_bedrock_client(model_id or SOCIAL_MODEL_BEDROCK, token_log=token_log)
    elif provider == "anthropic":
        return _make_anthropic_client(model_id or SOCIAL_MODEL_ANTHROPIC)
    elif provider == "openai":
        return _make_openai_client(model_id or SOCIAL_MODEL_OPENAI)
    else:
        return _make_bedrock_client(model_id or SOCIAL_MODEL_BEDROCK, token_log=token_log)


def _make_bedrock_client(model_id: str, token_log: list | None = None) -> Callable:
    import boto3
    bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-west-1"))

    def call(system: str, user: str) -> str:
        resp = bedrock.invoke_model(
            modelId=model_id,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2048,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(resp["body"].read())
        if token_log is not None:
            usage = raw.get("usage", {})
            token_log.append((
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
            ))
        return raw["content"][0]["text"].strip()

    return call


def _make_anthropic_client(model_id: str) -> Callable:
    def call(system: str, user: str) -> str:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model_id, max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text.strip()

    return call


def _make_openai_client(model_id: str) -> Callable:
    def call(system: str, user: str) -> str:
        import openai
        api_key = os.environ.get("OPENAI_API_KEY", "")
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model_id, max_tokens=2048, temperature=0.7,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content.strip()

    return call
