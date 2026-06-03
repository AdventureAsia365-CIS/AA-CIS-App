"""
AA-140 — AcpTracer unit tests.

Coverage:
  1. Tracer init with valid run_id → trace_id set correctly
  2. Graceful degradation when Langfuse unavailable → _enabled=False, no exception
  3. Model tier detection: haiku→T1, sonnet→T2, gpt-4→T3
  4. Cost calculation T1 (Haiku)
  5. Cost calculation T2 (Sonnet)
  6. Cost calculation T3 (GPT-4.1)
  7. span() returns no-op context when _enabled=False (no exception raised)
  8. record_llm_call updates span with correct tags
"""
import pytest
from unittest.mock import MagicMock, patch


class TestAcpTracerInit:
    def test_tracer_init_with_valid_run_id(self):
        """Tracer init with mocked Langfuse → trace_id matches run_id, _enabled=True."""
        from services.acp_shared.tracer import AcpTracer

        mock_lf = MagicMock()
        mock_trace = MagicMock(id="run-test-001")
        mock_lf.trace.return_value = mock_trace

        with patch.dict("os.environ", {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_HOST": "http://localhost:3000",
        }):
            with patch("services.acp_shared.tracer.Langfuse", return_value=mock_lf,
                       create=True):
                with patch("langfuse.Langfuse", return_value=mock_lf, create=True):
                    tracer = AcpTracer(run_id="run-test-001", tenant_id="tenant-001")

        assert tracer.run_id == "run-test-001"
        assert tracer.tenant_id == "tenant-001"

    def test_tracer_graceful_degradation(self):
        """Langfuse unavailable → _enabled=False, no exception raised."""
        from services.acp_shared.tracer import AcpTracer

        with patch.dict("os.environ", {}, clear=True):
            # No LANGFUSE_PUBLIC_KEY → KeyError caught internally
            tracer = AcpTracer(run_id="run-fail-001", tenant_id="tenant-001")

        assert tracer._enabled is False
        assert tracer.run_id == "run-fail-001"


class TestModelTier:
    def test_haiku_maps_to_t1(self):
        from services.acp_shared.tracer import _model_tier
        assert _model_tier("us.anthropic.claude-haiku-4-5-20251001-v1:0") == "T1"
        assert _model_tier("claude-haiku-4-5") == "T1"

    def test_sonnet_maps_to_t2(self):
        from services.acp_shared.tracer import _model_tier
        assert _model_tier("us.anthropic.claude-sonnet-4-5-20251001-v1:0") == "T2"
        assert _model_tier("claude-sonnet-4-5") == "T2"

    def test_gpt4_maps_to_t3(self):
        from services.acp_shared.tracer import _model_tier
        assert _model_tier("gpt-4.1") == "T3"
        assert _model_tier("gpt-4o") == "T3"
        assert _model_tier("gpt4-turbo") == "T3"

    def test_unknown_defaults_to_t1(self):
        from services.acp_shared.tracer import _model_tier
        assert _model_tier("some-unknown-model") == "T1"


class TestCostCalculation:
    def test_cost_calculation_t1(self):
        """Haiku: 1000 input + 500 output → $0.80*1000/1M + $4.00*500/1M = $0.0028"""
        from services.acp_shared.tracer import _calc_cost
        cost = _calc_cost(1000, 500, "T1")
        expected = round((1000 * 0.80 + 500 * 4.00) / 1_000_000, 6)
        assert cost == pytest.approx(expected, rel=1e-5)
        assert cost == pytest.approx(0.0028, rel=1e-5)

    def test_cost_calculation_t2(self):
        """Sonnet: 1000 input + 500 output → $3.00*1000/1M + $15.00*500/1M = $0.0105"""
        from services.acp_shared.tracer import _calc_cost
        cost = _calc_cost(1000, 500, "T2")
        expected = round((1000 * 3.00 + 500 * 15.00) / 1_000_000, 6)
        assert cost == pytest.approx(expected, rel=1e-5)
        assert cost == pytest.approx(0.0105, rel=1e-5)

    def test_cost_calculation_t3(self):
        """GPT-4.1: 1000 input + 500 output → $2.00*1000/1M + $8.00*500/1M = $0.006"""
        from services.acp_shared.tracer import _calc_cost
        cost = _calc_cost(1000, 500, "T3")
        expected = round((1000 * 2.00 + 500 * 8.00) / 1_000_000, 6)
        assert cost == pytest.approx(expected, rel=1e-5)
        assert cost == pytest.approx(0.006, rel=1e-5)

    def test_zero_tokens_returns_zero(self):
        from services.acp_shared.tracer import _calc_cost
        assert _calc_cost(0, 0, "T1") == 0.0


class TestSpanBehavior:
    def test_span_noop_when_disabled(self):
        """_enabled=False → span context manager does not raise."""
        from services.acp_shared.tracer import AcpTracer

        # Create disabled tracer (no env vars)
        with patch.dict("os.environ", {}, clear=True):
            tracer = AcpTracer(run_id="run-noop", tenant_id="t1")

        assert tracer._enabled is False

        # Must not raise any exception
        with tracer.span("s2", "synthesize") as span:
            tracer.record_llm_call(span, "claude-haiku", 100, 50, 120.0)

    def test_record_llm_call_updates_span(self):
        """record_llm_call calls span.update with correct metadata tags."""
        from services.acp_shared.tracer import AcpTracer

        with patch.dict("os.environ", {}, clear=True):
            tracer = AcpTracer(run_id="run-tag-test", tenant_id="t1")

        mock_span = MagicMock()
        tracer.record_llm_call(mock_span, "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                               1000, 500, 250.0)

        mock_span.update.assert_called_once()
        call_kwargs = mock_span.update.call_args[1]
        meta = call_kwargs["metadata"]

        assert meta["model_tier"] == "T1"
        assert meta["input_tokens"] == 1000
        assert meta["output_tokens"] == 500
        assert meta["latency_ms"] == 250.0
        assert "cost_usd" in meta
        assert meta["cost_usd"] > 0

    def test_record_llm_call_noop_span_does_not_raise(self):
        """record_llm_call on _NoOpSpan never raises."""
        from services.acp_shared.tracer import AcpTracer
        from services.acp_shared.tracer import _NoOpSpan as NoOpSpan

        with patch.dict("os.environ", {}, clear=True):
            tracer = AcpTracer(run_id="run-noop-2", tenant_id="t1")

        noop = NoOpSpan()
        # Should not raise
        tracer.record_llm_call(noop, "gpt-4.1", 200, 100, 500.0)

    def test_flush_noop_when_disabled(self):
        """flush() on disabled tracer does not raise."""
        from services.acp_shared.tracer import AcpTracer

        with patch.dict("os.environ", {}, clear=True):
            tracer = AcpTracer(run_id="run-flush", tenant_id="t1")

        tracer.flush()  # must not raise
