import os
import json
import boto3
import openai
import structlog
from .models import LLMRequest, LLMResponse
from .prompt_cache import build_cached_system_prompt, build_cached_messages

logger = structlog.get_logger()

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-1")

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

# Langfuse optional
try:
    from langfuse import Langfuse
    _langfuse = Langfuse(
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
        host=os.environ.get("LANGFUSE_HOST", "http://localhost:3000"),
    )
    LANGFUSE_ENABLED = True
except Exception:
    LANGFUSE_ENABLED = False
    logger.info("langfuse_disabled", reason="not configured or not reachable")


class LLMClient:
    """
    Fallback chain:
    T1: Claude Sonnet 4.5 (AWS Bedrock) + prompt caching
    T2: Claude Haiku 4.5  (AWS Bedrock) + prompt caching
    T3: GPT-4.1           (OpenAI)
    + Langfuse tracing (optional)
    """

    def __init__(self):
        self._bedrock = boto3.client(
            "bedrock-runtime",
            region_name=BEDROCK_REGION,
        )
        self._openai = openai.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY")
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        trace_id = self._start_trace(request)

        # T1: Claude Sonnet via Bedrock
        try:
            resp = self._call_bedrock(
                request, model=BEDROCK_SONNET, use_cache=True
            )
            self._end_trace(trace_id, resp, "t1_success")
            return resp
        except Exception as e:
            logger.warning("t1_failed", error=str(e))

        # T2: Claude Haiku via Bedrock
        try:
            resp = self._call_bedrock(
                request, model=BEDROCK_HAIKU, use_cache=True
            )
            resp.fallback_used = True
            self._end_trace(trace_id, resp, "t2_fallback")
            return resp
        except Exception as e:
            logger.warning("t2_failed", error=str(e))

        # T3: GPT-4.1 (unchanged)
        try:
            resp = self._call_openai(request, model="gpt-4.1")
            resp.fallback_used = True
            self._end_trace(trace_id, resp, "t3_fallback")
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

        response = self._bedrock.invoke_model(
            modelId=model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )

        result  = json.loads(response["body"].read())
        content = result["content"][0]["text"]
        usage   = result.get("usage", {})
        in_tok  = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
        cache_read  = usage.get("cache_read_input_tokens", 0) or 0
        cache_write = usage.get("cache_creation_input_tokens", 0) or 0
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
        resp = self._openai.chat.completions.create(
            model=model,
            max_tokens=request.max_tokens,
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user",   "content": request.user_prompt},
            ],
        )
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

    def _start_trace(self, request: LLMRequest) -> str | None:
        if not LANGFUSE_ENABLED:
            return None
        try:
            trace = _langfuse.trace(name="llm_generate",
                                    input={"prompt": request.user_prompt[:200]})
            return trace.id
        except Exception:
            return None

    def _end_trace(self, trace_id: str | None, resp: LLMResponse, status: str):
        if not LANGFUSE_ENABLED or not trace_id:
            return
        try:
            _langfuse.generation(
                trace_id=trace_id,
                name=status,
                model=resp.model_used,
                usage={"input": resp.input_tokens, "output": resp.output_tokens},
                output=resp.content[:200],
            )
        except Exception:
            pass
