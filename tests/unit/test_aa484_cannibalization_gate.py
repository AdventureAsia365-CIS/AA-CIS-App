"""AA-484 — services/acp_content_writing/quality_gates.py::gate_cannibalization() (the pure
gate function) and services/acp_content_writing/service.py::_tenant_missing_brand_rules()
(the diagnostic-hint helper). The full end-to-end wiring (embedding -> find_similar_pieces ->
cannibalization_match reaching run_quality_gates()) is covered by
test_aa499_content_writing_wiring.py::TestCannibalizationMatchReachesGates — this file is
gate-logic-level, mirroring test_aa452_t10_nine_gates.py's own per-gate test shape."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.acp_content_writing import quality_gates as qg
from services.acp_content_writing import service


class TestGateCannibalization:
    def test_no_match_passes_with_zero_violations(self):
        result = qg.gate_cannibalization(None)
        assert result["gate"] == "F10_cannibalization_cross_tenant"
        assert result["passed"] is True
        assert result["violations"] == []
        assert result["blocking"] is True  # default — a real match DOES block

    def test_match_above_threshold_fails_blocking_and_repairable(self):
        match = {"piece_id": "piece-123", "tenant_id": "tenant-abc", "similarity": 0.95,
                 "writer_missing_brand_rules": False}
        result = qg.gate_cannibalization(match)
        assert result["passed"] is False
        assert result["blocking"] is True
        assert result["repairable"] is True
        assert "0.95" in result["violations"][0]
        assert "piece-123" in result["violations"][0]

    def test_missing_brand_rules_adds_diagnostic_hint(self):
        match = {"piece_id": "piece-123", "tenant_id": "tenant-abc", "similarity": 0.95,
                 "writer_missing_brand_rules": True}
        result = qg.gate_cannibalization(match)
        assert "no active brand rules" in result["violations"][0]

    def test_brand_rules_present_no_hint_text(self):
        match = {"piece_id": "piece-123", "tenant_id": "tenant-abc", "similarity": 0.95,
                 "writer_missing_brand_rules": False}
        result = qg.gate_cannibalization(match)
        assert "brand rules" not in result["violations"][0]

    def test_missing_key_defaults_to_no_hint_not_a_crash(self):
        """Real callers always set writer_missing_brand_rules (service.py) — this only guards a
        hand-built test/caller dict that omits it, same defensive .get() pattern used elsewhere."""
        match = {"piece_id": "piece-123", "tenant_id": "tenant-abc", "similarity": 0.95}
        result = qg.gate_cannibalization(match)
        assert "no active brand rules" not in result["violations"][0]


@pytest.mark.asyncio
class TestTenantMissingBrandRules:
    def _pool(self, conn):
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)
        return pool

    async def test_active_row_found_returns_false(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"?column?": 1}
        pool = self._pool(conn)
        result = await service._tenant_missing_brand_rules(str(uuid.uuid4()), pool)
        assert result is False

    async def test_no_row_returns_true(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = self._pool(conn)
        result = await service._tenant_missing_brand_rules(str(uuid.uuid4()), pool)
        assert result is True

    async def test_query_scopes_by_tenant_and_active(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = self._pool(conn)
        tenant_id = str(uuid.uuid4())
        await service._tenant_missing_brand_rules(tenant_id, pool)
        query, *params = conn.fetchrow.call_args[0]
        assert "tenant_brand_rules" in query
        assert "is_active = true" in query
        assert params[0] == tenant_id
