"""
compact_packet build + Bedrock skeleton + expand calls.
"""
import json
import os
import time

import boto3

from models import CalendarSkeleton, CompactPacket

_SONNET = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_BEDROCK_REGION = "us-west-1"

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _read_prompt(filename: str) -> str:
    with open(os.path.join(_PROMPT_DIR, filename)) as f:
        return f.read()


def _bedrock_client():
    return boto3.client("bedrock-runtime", region_name=_BEDROCK_REGION)


def _invoke(client, model_id: str, prompt: str, max_tokens: int = 8192) -> tuple[str, int, int]:
    """Returns (text, input_tokens, output_tokens). Retries twice on ThrottlingException."""
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    for attempt in range(3):
        try:
            resp = client.invoke_model(modelId=model_id, body=body)
            parsed = json.loads(resp["body"].read())
            text = parsed["content"][0]["text"]
            usage = parsed.get("usage", {})
            return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        except client.exceptions.ThrottlingException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def build_compact_packet(
    run_context: dict,
    tenant_rules: dict,
    country: str,
    lesson_summary: str,
) -> CompactPacket:
    kw_research = run_context.get("s2_keyword_research", {})
    keywords = kw_research.get("keywords", {})

    # Top 18 by max(vol_market1, vol_market2)
    kw_list = []
    for kw, data in keywords.items():
        vol = max(
            data.get("vol_m1", 0) or 0,
            data.get("vol_m2", 0) or 0,
        )
        kw_list.append({
            "keyword": kw,
            "vol": vol,
            "competition": data.get("competition", ""),
            "cpc": data.get("cpc", 0),
            "intent": data.get("intent", ""),
        })
    kw_list.sort(key=lambda x: x["vol"], reverse=True)
    top_18 = kw_list[:18]

    brand_brief = run_context.get("brand_brief", {})
    funnel_mix = brand_brief.get("funnel_mix", {"tofu": 20, "mofu": 60, "bofu": 20})
    cadence_weeks = brand_brief.get("cadence_weeks", 12)
    posts_per_week = brand_brief.get("posts_per_week", 2)

    return CompactPacket(
        top_keywords=top_18,
        funnel_mix=funnel_mix,
        cadence_weeks=cadence_weeks,
        posts_per_week=posts_per_week,
        country=country,
        lesson_summary=lesson_summary,
    )


def skeleton_call(packet: CompactPacket) -> tuple[CalendarSkeleton, int, int]:
    """Step 3: Bedrock Sonnet skeleton. Returns (skeleton, in_tok, out_tok)."""
    rules = _read_prompt("planning_rules_compact.md")
    prompt = f"{rules}\n\n## Compact Packet\n```json\n{json.dumps(packet.model_dump(), indent=2)}\n```"

    client = _bedrock_client()
    text, in_tok, out_tok = _invoke(client, _SONNET, prompt, max_tokens=8192)

    # Strip accidental markdown fences
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    data = json.loads(text)
    return CalendarSkeleton(**data), in_tok, out_tok


def expand_call(
    skeleton: CalendarSkeleton,
    tenant_rules: dict,
    packet: CompactPacket,
) -> tuple[str, int, int]:
    """Step 4: Bedrock Sonnet expand. Returns (expanded_markdown, in_tok, out_tok)."""
    expand_prompt = _read_prompt("calendar_expand_prompt.md")

    system_prompt = tenant_rules.get("system_prompt", "")
    style_guide = tenant_rules.get("style_guide", "")
    rules_block = ""
    if system_prompt or style_guide:
        rules_block = f"\n\n## Tenant Brand Rules\n{system_prompt}\n{style_guide}"

    prompt = (
        f"{expand_prompt}{rules_block}\n\n"
        f"## Skeleton\n```json\n{json.dumps(skeleton.model_dump(), indent=2)}\n```\n\n"
        f"Country: {packet.country}\n"
        f"Cadence: {packet.cadence_weeks} weeks, {packet.posts_per_week} posts/week"
    )

    client = _bedrock_client()
    return _invoke(client, _SONNET, prompt, max_tokens=16384)
