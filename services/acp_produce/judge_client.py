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

AA-351 (16/08/2026) — added invoke_judge_gpt56() as a SECOND, feature-flagged judge
backend (GPT-5.6 Sol, via the acc3 Bedrock satellite) alongside Nova Pro, to test
whether a judge from a third vendor family (neither Claude/writer nor Nova) reduces
the "moving target" flagging AA-382 confirmed with real data (docs/implementation-
notes/AA-382-repair-rubric-context.md — same phrase re-flagged as violating across
repair rounds after being fixed, one case re-reading as compliant with the judge's
own GOOD anchor). Selection is env var JUDGE_MODEL ("nova_pro" default | "gpt56"),
read per-call (not at import) so it can be overridden per-invocation for a side-by-
side comparison script without mutating process-wide state. Nova Pro's code path is
UNCHANGED — this is additive, not a replacement; every existing caller (gates.py's 3
call sites) is untouched and still defaults to Nova Pro in production.
"""
from __future__ import annotations

import json
import os

import boto3
import structlog
from json_repair import repair_json

logger = structlog.get_logger()

AWS_REGION = "us-west-1"
NOVA_PRO_MODEL_ID = "us.amazon.nova-pro-v1:0"

# AA-351 — GPT-5.6 Sol, accepted (create-foundation-model-agreement) on acc3 ONLY
# (786888028788, profile nghiep_aa365) 16/08/2026 — NOT accepted on acc1/acc2, verified
# via list-foundation-model-agreement-offers before/after on all 3. Only Sol was
# accepted (Terra/Luna are separate agreements/rate cards, NOT the same offer as
# survey AA-351-gpt-bedrock-3accounts.md originally assumed — confirmed distinct
# offerIds/pricing during this session) — Nghiep's explicit choice, trial scope only.
# "global." prefix (not "us.") matches the existing Claude satellite convention
# (bedrock_satellite.py's INFERENCE_PROFILE_SONNET/HAIKU — AA-397) and is ~10%
# cheaper per the survey's rate card. GPT models on Bedrock only support Converse,
# never invoke_model with a raw JSON body (confirmed by the AA-351 survey's real
# invoke tests) — invoke_judge_gpt56() below uses client.converse(), not
# invoke_model(), unlike the Nova Pro path in invoke_judge() proper.
GPT56_SOL_INFERENCE_PROFILE = (
    "arn:aws:bedrock:us-west-1:786888028788:inference-profile/global.openai.gpt-5.6-sol"
)


def invoke_judge(
    system_prompt: str, user_prompt: str, max_tokens: int = 2048, model: str | None = None,
) -> dict:
    """One seam, mirrors the writer's generate_draft() seam
    (services/content_generation/s1_from_atom.py) — deliberately duplicated
    rather than shared, so no future refactor can accidentally merge the
    writer and judge call paths into one function that some caller then
    reuses for both roles. Returns {text, model_used, provider, input_tokens,
    output_tokens}.

    `model`: explicit override for AA-351's comparison script ("nova_pro" |
    "gpt56"). None (the default — every gates.py call site) falls back to the
    JUDGE_MODEL env var, itself defaulting to "nova_pro" — production
    behavior is unchanged unless JUDGE_MODEL is set."""
    model = model or os.environ.get("JUDGE_MODEL", "nova_pro")
    if model == "gpt56":
        return invoke_judge_gpt56(system_prompt, user_prompt, max_tokens)

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


def invoke_judge_gpt56(system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> dict:
    """AA-351 trial judge backend — GPT-5.6 Sol via the acc3 Bedrock satellite.
    Reuses shared/llm_client/bedrock_satellite.py's AssumeRole session cache
    (get_satellite_client, account="acc3") — the SAME session mechanism the
    Claude satellite writer already uses, not a new AssumeRole path (one
    fewer thing to get wrong/duplicate). Deliberately NOT imported by
    anything in generation.py/content_generation — this module's own
    isolation guarantee (see module docstring, ADR-2026-014/027 L3) applies
    equally to this second judge backend."""
    from shared.llm_client.bedrock_satellite import get_satellite_client

    client = get_satellite_client("bedrock-runtime", account="acc3")
    resp = client.converse(
        modelId=GPT56_SOL_INFERENCE_PROFILE,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    usage = resp.get("usage", {})
    logger.info("judge_llm_success", model=GPT56_SOL_INFERENCE_PROFILE,
                provider="bedrock-satellite-acc3",
                in_tokens=usage.get("inputTokens", 0), out_tokens=usage.get("outputTokens", 0))
    return {
        "text": text,
        "model_used": GPT56_SOL_INFERENCE_PROFILE,
        "provider": "bedrock-satellite-acc3",
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
