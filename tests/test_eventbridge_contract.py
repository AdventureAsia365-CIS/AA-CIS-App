"""
Contract tests: EventBridge source strings + consumer idempotency.
AA-106 — EventBridge Source Fix + Consumer Idempotency
"""
import importlib
import sys
import unittest
from unittest.mock import MagicMock, patch


# ── 1. Source / detail-type string contract ──────────────────────────────────

class TestACPEventSourceStrings(unittest.TestCase):
    def setUp(self):
        from services.acp_shared.event_constants import ACPEventSource, ACPEventDetailType
        self.S = ACPEventSource
        self.D = ACPEventDetailType

    def test_source_values(self):
        assert self.S.S0 == "acp.s0"
        assert self.S.S1 == "acp.s1"
        assert self.S.S2 == "acp.s2"
        assert self.S.S3 == "acp.s3"
        assert self.S.S4_BLOG == "acp.s4_blog"
        assert self.S.S4_SOCIAL == "acp.s4_social"
        assert self.S.HITL == "acp.hitl"

    def test_detail_type_values(self):
        assert self.D.S1_COMPLETED == "acp.s1.completed"
        assert self.D.S3_COMPLETED == "acp.s3.completed"
        assert self.D.HITL_APPROVED == "acp.hitl.approved"
        assert self.D.HITL_REJECTED == "acp.hitl.rejected"
        assert self.D.RUN_FAILED == "acp.run.failed"

    def test_no_legacy_pipeline_source(self):
        """Ensure the old broken source string does not appear in any constant."""
        all_values = [v for k, v in vars(self.S).items() if not k.startswith("_")]
        assert "aa-cis.pipeline" not in all_values, \
            "Legacy source 'aa-cis.pipeline' must not exist in ACPEventSource"

    def test_s1_handler_uses_constant_source(self):
        """S1 handler must not hardcode 'aa-cis.pipeline'."""
        import inspect
        import services.acp.handler as h
        src = inspect.getsource(h)
        assert "aa-cis.pipeline" not in src, \
            "services/acp/handler.py still contains hardcoded 'aa-cis.pipeline'"
        assert "ACPEventSource.S1" in src or "acp.s1" in src

    def test_gate2_approval_uses_hitl_source(self):
        """Gate 2 HITL approval event must use ACPEventSource.HITL, not 'acp.s3'."""
        import inspect
        import api.routers.v1_s3 as v1
        src = inspect.getsource(v1)
        # The HITL approval block must reference the HITL source constant
        assert "ACPEventSource.HITL" in src, \
            "v1_s3.py Gate 2 approval must emit ACPEventSource.HITL, not 'acp.s3'"


# ── 2. Idempotency helpers unit tests ────────────────────────────────────────

class TestIdempotencyHelpers(unittest.TestCase):
    """Tests for services.acp_shared.idempotency — uses an in-memory mock DB."""

    def _make_mock_conn(self, fetchone_result=None):
        """Return a context-manager-compatible mock psycopg2 connection."""
        cur = MagicMock()
        cur.fetchone.return_value = fetchone_result
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)

        conn = MagicMock()
        conn.cursor.return_value = cur
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        return conn, cur

    @patch("services.acp_shared.idempotency._connect")
    def test_is_already_processed_returns_false_when_not_found(self, mock_connect):
        conn, _ = self._make_mock_conn(fetchone_result=None)
        mock_connect.return_value = conn

        from services.acp_shared.idempotency import is_event_already_processed
        result = is_event_already_processed("evt-123", "run-abc", "s4_trigger",
                                            db_url="postgresql://x:y@host/db")
        assert result is False

    @patch("services.acp_shared.idempotency._connect")
    def test_is_already_processed_returns_true_when_found(self, mock_connect):
        conn, _ = self._make_mock_conn(fetchone_result=(1,))
        mock_connect.return_value = conn

        from services.acp_shared.idempotency import is_event_already_processed
        result = is_event_already_processed("evt-456", "run-abc", "s4_trigger",
                                            db_url="postgresql://x:y@host/db")
        assert result is True

    def test_returns_false_when_no_db_url(self):
        from services.acp_shared.idempotency import is_event_already_processed
        result = is_event_already_processed("evt-789", "run-abc", "s4_trigger",
                                            db_url=None)
        assert result is False

    def test_returns_false_when_no_event_id(self):
        from services.acp_shared.idempotency import is_event_already_processed
        result = is_event_already_processed(None, "run-abc", "s4_trigger",
                                            db_url="postgresql://x:y@host/db")
        assert result is False

    @patch("services.acp_shared.idempotency._connect")
    def test_returns_false_on_db_error(self, mock_connect):
        mock_connect.side_effect = Exception("DB connection refused")

        from services.acp_shared.idempotency import is_event_already_processed
        result = is_event_already_processed("evt-err", "run-abc", "s4_trigger",
                                            db_url="postgresql://x:y@host/db")
        assert result is False


# ── 3. S4 trigger handler idempotency integration ────────────────────────────

class TestS4TriggerHandlerIdempotency(unittest.TestCase):
    """Verify duplicate EventBridge delivery returns duplicate_skipped."""

    def _make_event(self, event_id="eb-test-001", run_id="run-uuid-001",
                    tenant_id="tenant-001"):
        return {
            "id": event_id,
            "detail": {"run_id": run_id, "tenant_id": tenant_id},
        }

    def _load_s4_handler(self):
        """Import api.lambda.s4_trigger.handler via importlib ('lambda' is a reserved word)."""
        return importlib.import_module("api.lambda.s4_trigger.handler")

    def test_duplicate_event_returns_skipped(self):
        mod = self._load_s4_handler()
        with patch.object(mod, "_is_already_processed", return_value=True):
            result = mod.handler(self._make_event(), context=None)
        assert result["statusCode"] == 200
        assert result["body"] == "duplicate_skipped"

    def test_first_delivery_proceeds(self):
        mod = self._load_s4_handler()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"status": "accepted"}'

        with patch.object(mod, "_ALB_URL", "http://internal-alb"), \
             patch.object(mod, "_is_already_processed", return_value=False), \
             patch.object(mod, "_mark_received") as mock_mark, \
             patch("urllib.request.urlopen", return_value=mock_resp):
            result = mod.handler(self._make_event(), context=None)

        assert result["statusCode"] == 200
        mock_mark.assert_called_once()

    def test_missing_run_id_returns_400(self):
        mod = self._load_s4_handler()
        result = mod.handler({"id": "evt-x", "detail": {"tenant_id": "t1"}}, context=None)
        assert result["statusCode"] == 400


if __name__ == "__main__":
    unittest.main()
