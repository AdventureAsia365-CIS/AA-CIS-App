"""
services.acp_produce.judge_client — F8/F9 cross-weight judge (Nova Pro, acc2).

ADR-2026-014/ADR-2026-027 (L3): the judge must run on a different model/vendor
than the writer AND must never see the writer's generation prompt — only
(piece text + rubric + corpus). This is a separate file from
services/acp_produce/generation.py on purpose: this module never imports
from generation.py (or from services/content_generation/s1_from_atom.py, the
writer used elsewhere in this repo), and nothing here accepts a
system_prompt/user_prompt built for a writer call. A reviewer — or a future
CI import-graph check — can verify context isolation by reading imports, not
just by trusting a docstring.

Model verified live (24/07/2026, real Bedrock invoke_model call, acc2
005097885195, confirmed via `aws bedrock list-inference-profiles`):
us.amazon.nova-pro-v1:0. Request/response shape is Bedrock's Converse-style
body — a THIRD distinct shape in this repo, neither Anthropic's
content[0].text (Claude satellite, shared/llm_client/bedrock_satellite.py)
nor the OpenAI-compatible choices[0].message.content shape (Palmyra,
services/content_generation/s1_from_atom.py::_call_palmyra):
  request:  {"system": [{"text": ...}], "messages": [{"role": "user",
             "content": [{"text": ...}]}], "inferenceConfig": {...}}
  response: {"output": {"message": {"content": [{"text": ...}]}}, "usage": {...}}
"""
from __future__ import annotations

import json

import boto3
import structlog
from json_repair import repair_json

logger = structlog.get_logger()

AWS_REGION = "us-west-1"
NOVA_PRO_MODEL_ID = "us.amazon.nova-pro-v1:0"


def invoke_judge(system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> dict:
    """One seam, mirrors the writer's generate_draft() seam
    (services/content_generation/s1_from_atom.py) — deliberately duplicated
    rather than shared, so no future refactor can accidentally merge the
    writer and judge call paths into one function that some caller then
    reuses for both roles. Returns {text, model_used, provider, input_tokens,
    output_tokens}."""
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    body = {
        "system": [{"text": system_prompt}],
        "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
    }
    resp = client.invoke_model(
        modelId=NOVA_PRO_MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(resp["body"].read())
    text = payload["output"]["message"]["content"][0]["text"]
    usage = payload.get("usage", {})
    logger.info("judge_llm_success", model=NOVA_PRO_MODEL_ID, provider="bedrock-acc2",
                in_tokens=usage.get("inputTokens", 0), out_tokens=usage.get("outputTokens", 0))
    return {
        "text": text,
        "model_used": NOVA_PRO_MODEL_ID,
        "provider": "bedrock-acc2",
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
    }


def parse_judge_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        salvaged = repair_json(raw, return_objects=True)
        if isinstance(salvaged, dict):
            return salvaged
        raise
