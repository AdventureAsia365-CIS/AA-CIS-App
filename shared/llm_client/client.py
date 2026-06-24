import os
import json
import boto3
from botocore.config import Config
import openai
import structlog
from .models import LLMRequest, LLMResponse
from .prompt_cache import build_cached_system_prompt, build_cached_messages

logger = structlog.get_logger()

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-1")

# Default model tier — override via ECS env var DEFAULT_MODEL_TIER
# Options: "haiku" (cheapest) | "sonnet" (premium) | "gpt-4.1" (OpenAI)
DEFAULT_MODEL_TIER = os.environ.get("DEFAULT_MODEL_TIER", "haiku")

# Bedrock model IDs
# T2 Haiku: cross-region inference profile — ACTIVE (verified working)
# T1 Sonnet: cross-region inference profile — needs AWS Marketplace subscription (AA-50)
BEDROCK_SONNET = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
BEDROCK_HAIKU  = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

COST_TABLE = {
    BEDROCK_SONNET: {"in": 0.003,   "out": 0.015},
    BEDROCK_HAIKU:  {"in": 0.00025, "out": 0.00125},
    "gpt-4.1":      {"in": 0.002,   "out": 0.008},
}

class LLMClient:
    """
    Fallback chain:
    T1: Claude Sonnet 4.5 (AWS Bedrock) + prompt caching
    T2: Claude Haiku 4.5  (AWS Bedrock) + prompt caching
    T3: GPT-4.1           (OpenAI)
    """

    def __init__(self):
        self._bedrock = boto3.client(
            "bedrock-runtime",
            region_name=BEDROCK_REGION,
            config=Config(
                read_timeout=300,
                connect_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
        self._openai = openai.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY")
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        tier = request.model_tier or DEFAULT_MODEL_TIER  # "haiku" | "sonnet" | "gpt-4.1"

        # Direct GPT-4.1 — no Bedrock fallback (explicit choice)
        if tier == "gpt-4.1":
            try:
                return self._call_openai(request, model="gpt-4.1")
            except Exception as e:
                logger.error("gpt41_direct_failed", error=str(e))
                raise RuntimeError(f"GPT-4.1 failed: {e}") from e

        if tier == "sonnet":
            # T1: Claude Sonnet — premium quality
            try:
                resp = self._call_bedrock(request, model=BEDROCK_SONNET, use_cache=True)
                return resp
            except Exception as e:
                if "AccessDeniedException" in str(e) or "not authorized" in str(e).lower():
                    logger.warning("t1_sonnet_not_subscribed", model=BEDROCK_SONNET,
                                   hint="Enable cross-region inference profile in AWS Marketplace (AA-50)")
                else:
                    logger.warning("t1_failed_trying_t2", model=BEDROCK_SONNET, error=str(e))

        # T2: Claude Haiku — fast / default tier, or Sonnet fallback
        try:
            resp = self._call_bedrock(request, model=BEDROCK_HAIKU, use_cache=True)
            resp.fallback_used = tier == "sonnet"  # only a fallback when Sonnet was intended
            return resp
        except Exception as e:
            logger.warning("t2_failed_trying_t3", model=BEDROCK_HAIKU, error=str(e))

        # T3: GPT-4.1 — last resort for all tiers
        try:
            resp = self._call_openai(request, model="gpt-4.1")
            resp.fallback_used = True
            logger.warning("t3_fallback_used", model="gpt-4.1",
                           reason=f"T2 failed (tier={tier})")
            return resp
        except Exception as e:
            logger.error("t3_failed_all_providers_down", error=str(e))
            raise RuntimeError("All LLM providers failed") from e

    def _call_bedrock(
        self, request: LLMRequest, model: str, use_cache: bool = False
    ) -> LLMResponse:
        system = (
            build_cached_system_prompt(request.system_prompt)
            if use_cache
            else [{"type": "text", "text": request.system_prompt}]
        )
        messages = (
            build_cached_messages(
                request.few_shots if hasattr(request, "few_shots") else [],
                request.user_prompt,
            )
            if use_cache
            else [{"role": "user", "content": request.user_prompt}]
        )

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": request.max_tokens,
            "system": system,
            "messages": messages,
        }

        response = self._bedrock.invoke_model_with_response_stream(
            modelId=model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )

        # AA-224: stream accumulation. Non-stream invoke_model held the HTTP connection open for
        # the full generation (default 60s read_timeout) -> Sonnet branded prompts timed out ->
        # silent fallback to Haiku. Streaming returns chunks incrementally so the socket never
        # idles past read_timeout. Usage now arrives across events: input_tokens in
        # message_start, output_tokens (cumulative) in message_delta.
        content_parts = []
        in_tok = out_tok = cache_read = cache_write = 0
        for event in response["body"]:
            chunk = json.loads(event["chunk"]["bytes"])
            ctype = chunk.get("type")
            if ctype == "message_start":
                u = chunk.get("message", {}).get("usage", {})
                in_tok      = u.get("input_tokens", 0)
                cache_read  = u.get("cache_read_input_tokens", 0) or 0
                cache_write = u.get("cache_creation_input_tokens", 0) or 0
            elif ctype == "content_block_delta":
                d = chunk.get("delta", {})
                if d.get("type") == "text_delta":
                    content_parts.append(d.get("text", ""))
            elif ctype == "message_delta":
                out_tok = chunk.get("usage", {}).get("output_tokens", out_tok)
        content = "".join(content_parts)
        cost    = self._calc_cost(model, in_tok, out_tok)

        logger.info("llm_success", provider="bedrock", model=model,
                    in_tokens=in_tok, out_tokens=out_tok,
                    cache_read=cache_read, cache_write=cache_write,
                    cost_usd=cost)

        return LLMResponse(
            content=content, model_used=model, provider="bedrock",
            input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost,
        )

    def _call_openai(self, request: LLMRequest, model: str) -> LLMResponse:
        # AA-209: forward sampling controls only when the caller explicitly set them. This makes the
        # GPT-4.1 judge reproducible (it passes temperature + seed) without changing behavior of
        # content/T3-fallback calls that rely on provider defaults (they never set these fields).
        kwargs = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user",   "content": request.user_prompt},
            ],
        }
        fields_set = request.model_fields_set
        if "temperature" in fields_set:
            kwargs["temperature"] = request.temperature
        if "seed" in fields_set and request.seed is not None:
            kwargs["seed"] = request.seed
        resp = self._openai.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content
        in_tok  = resp.usage.prompt_tokens
        out_tok = resp.usage.completion_tokens
        cost    = self._calc_cost(model, in_tok, out_tok)

        logger.info("llm_success", provider="openai", model=model,
                    in_tokens=in_tok, out_tokens=out_tok, cost_usd=cost)

        return LLMResponse(
            content=content, model_used=model, provider="openai",
            input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost,
        )

    def _calc_cost(self, model: str, in_tok: int, out_tok: int) -> float:
        rates = COST_TABLE.get(model, {"in": 0.003, "out": 0.015})
        return round((in_tok * rates["in"] + out_tok * rates["out"]) / 1000, 6)
