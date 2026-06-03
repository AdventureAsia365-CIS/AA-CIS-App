"""
AcpTracer — Langfuse trace instrumentation for ACP pipeline stages.

One AcpTracer per LLM call site (all share the same trace_id = acp_runs.run_id,
so Langfuse groups spans under one trace automatically).

Credentials from env vars (injected by ECS Secrets Manager):
  LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

Graceful degradation: Langfuse unavailable → _enabled=False, no exception raised.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Pricing per 1M tokens, USD (Langfuse internal tracking)
_PRICING = {
    "T1": {"input": 0.80,  "output": 4.00},   # Haiku 4.5
    "T2": {"input": 3.00,  "output": 15.00},  # Sonnet 4.5
    "T3": {"input": 2.00,  "output": 8.00},   # GPT-4.1
}


def _model_tier(model_id: str) -> str:
    """Map model_id string → T1 (Haiku) / T2 (Sonnet) / T3 (GPT-4.1)."""
    m = model_id.lower()
    if "gpt-4" in m or "gpt4" in m:
        return "T3"
    if "sonnet" in m:
        return "T2"
    return "T1"


def _calc_cost(input_tokens: int, output_tokens: int, tier: str) -> float:
    p = _PRICING.get(tier, _PRICING["T1"])
    return round(
        (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000, 6
    )


class _NoOpSpan:
    """Returned when Langfuse is disabled — all methods silently no-op."""

    def update(self, **kwargs):
        pass

    def end(self, **kwargs):
        pass


class _SpanCtx:
    """Context manager that opens/closes a real Langfuse span."""

    def __init__(self, trace, name: str, metadata: dict):
        self._trace = trace
        self._name = name
        self._metadata = metadata
        self._span = None

    def __enter__(self):
        try:
            self._span = self._trace.span(name=self._name, metadata=self._metadata)
        except Exception as exc:
            logger.debug("langfuse span create error: %s", exc)
            self._span = _NoOpSpan()
        return self._span

    def __exit__(self, *args):
        try:
            self._span.end()
        except Exception:
            pass


class _NoOpCtx:
    """Context manager returned when Langfuse is disabled."""

    def __enter__(self):
        return _NoOpSpan()

    def __exit__(self, *args):
        pass


class AcpTracer:
    """
    Langfuse tracer for one ACP pipeline stage invocation.

    All tracers with the same run_id write to the same Langfuse trace — safe
    to instantiate per LLM call site without creating duplicate traces.

    Usage::

        import time
        tracer = AcpTracer(run_id=run_id, tenant_id=tenant_id)
        t = time.time()
        with tracer.span("s2", "synthesize") as span:
            result = bedrock.invoke_model(...)
            inp, out = extract_tokens(result)
            tracer.record_llm_call(span, model_id, inp, out, (time.time() - t) * 1000)
        tracer.flush()
    """

    def __init__(self, run_id: str, tenant_id: str):
        self.run_id = run_id
        self.tenant_id = tenant_id
        self._enabled = False
        self._lf = None
        self._trace = None

        try:
            from langfuse import Langfuse  # noqa: PLC0415

            pk = os.environ["LANGFUSE_PUBLIC_KEY"]
            sk = os.environ["LANGFUSE_SECRET_KEY"]
            host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

            self._lf = Langfuse(public_key=pk, secret_key=sk, host=host)
            self._trace = self._lf.trace(
                id=run_id,
                name=f"acp_run_{run_id}",
                user_id=tenant_id,
                metadata={"tenant_id": tenant_id},
            )
            self._enabled = True
            logger.debug("AcpTracer ready trace_id=%s", run_id)
        except Exception as exc:
            logger.warning(
                "AcpTracer init failed (Langfuse disabled) run_id=%s: %s", run_id, exc
            )

    def span(self, stage: str, agent: Optional[str] = None):
        """Return context manager that creates a Langfuse span for this stage."""
        name = f"{stage}.{agent}" if agent else stage
        if not self._enabled:
            return _NoOpCtx()
        return _SpanCtx(
            trace=self._trace,
            name=name,
            metadata={"stage": stage, "tenant_id": self.tenant_id},
        )

    def record_llm_call(
        self,
        span,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> None:
        """Attach LLM call metadata to a span (call inside the span context)."""
        tier = _model_tier(model_id)
        cost = _calc_cost(input_tokens, output_tokens, tier)
        try:
            span.update(
                metadata={
                    "model_id": model_id,
                    "model_tier": tier,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost,
                    "latency_ms": round(latency_ms, 1),
                }
            )
        except Exception as exc:
            logger.debug("record_llm_call span update failed: %s", exc)

    def flush(self) -> None:
        """Flush pending Langfuse events. Call once at the end of a stage."""
        if not self._enabled:
            return
        try:
            self._lf.flush()
        except Exception as exc:
            logger.warning("langfuse flush failed run_id=%s: %s", self.run_id, exc)
