import os
import anthropic
import openai
import structlog
from .models import LLMRequest, LLMResponse

logger = structlog.get_logger()

# Cost per 1K tokens (USD)
COST_TABLE = {
    "claude-sonnet-4-6":  {"in": 0.003,  "out": 0.015},
    "claude-haiku-4-5":   {"in": 0.00025,"out": 0.00125},
    "gpt-4.1":            {"in": 0.002,  "out": 0.008},
}

class LLMClient:
    """
    Fallback chain:
    T1: Claude Sonnet (Anthropic API)
    T2: Claude Haiku  (Anthropic API)
    T3: GPT-4.1       (OpenAI)
    """

    def __init__(self):
        self._anthropic = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        self._openai = openai.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY")
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Try T1 → T2 → T3, return first success."""

        # T1: Claude Sonnet
        try:
            return self._call_anthropic(request, model="claude-sonnet-4-6")
        except Exception as e:
            logger.warning("t1_failed", error=str(e))

        # T2: Claude Haiku
        try:
            resp = self._call_anthropic(request, model="claude-haiku-4-5-20251001")
            resp.fallback_used = True
            return resp
        except Exception as e:
            logger.warning("t2_failed", error=str(e))

        # T3: GPT-4.1
        try:
            resp = self._call_openai(request, model="gpt-4.1")
            resp.fallback_used = True
            return resp
        except Exception as e:
            logger.error("t3_failed_all_providers_down", error=str(e))
            raise RuntimeError("All LLM providers failed") from e

    def _call_anthropic(self, request: LLMRequest, model: str) -> LLMResponse:
        msg = self._anthropic.messages.create(
            model=model,
            max_tokens=request.max_tokens,
            system=request.system_prompt,
            messages=[{"role": "user", "content": request.user_prompt}],
        )
        content = msg.content[0].text
        in_tok  = msg.usage.input_tokens
        out_tok = msg.usage.output_tokens
        cost    = self._calc_cost(model, in_tok, out_tok)

        logger.info("llm_success", provider="anthropic", model=model,
                    in_tokens=in_tok, out_tokens=out_tok, cost_usd=cost)

        return LLMResponse(
            content=content, model_used=model,
            provider="anthropic", input_tokens=in_tok,
            output_tokens=out_tok, cost_usd=cost,
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
            content=content, model_used=model,
            provider="openai", input_tokens=in_tok,
            output_tokens=out_tok, cost_usd=cost,
        )

    def _calc_cost(self, model: str, in_tok: int, out_tok: int) -> float:
        rates = COST_TABLE.get(model, {"in": 0.003, "out": 0.015})
        return round((in_tok * rates["in"] + out_tok * rates["out"]) / 1000, 6)
