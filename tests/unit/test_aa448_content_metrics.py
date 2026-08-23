"""AA-448 round 6 — services/acp_shared/content_metrics.py (feedback loop: manual metric entry
+ confidence-gated atom.weight rollup).

_piece_score()/_weight_from_scores() are pure. record_metric_snapshot()/rollup_atom_weights()
are DB-backed — mocked pool, same convention as test_aa301_quarter.py.
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.acp_planning.constants import ATOM_WEIGHT_MAX, ATOM_WEIGHT_MIN, ENGAGEMENT_RATE_BASELINE
from services.acp_shared.content_metrics import (PieceNotFoundError, PieceNotOwnedError,
                                                 _piece_score, _weight_from_scores,
                                                 record_metric_snapshot, rollup_atom_weights)

TENANT = uuid.uuid4()


def _mock_pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


class TestPieceScore:
    def test_none_when_reach_missing(self):
        assert _piece_score(None, 50) is None

    def test_none_when_reach_zero(self):
        assert _piece_score(0, 50) is None

    def test_engagement_none_treated_as_zero(self):
        assert _piece_score(100, None) == 0.0

    def test_plain_rate(self):
        assert _piece_score(1000, 50) == 0.05


class TestWeightFromScores:
    def test_score_at_baseline_is_neutral_weight(self):
        assert _weight_from_scores([ENGAGEMENT_RATE_BASELINE]) == 1.0

    def test_score_above_baseline_increases_weight(self):
        assert _weight_from_scores([ENGAGEMENT_RATE_BASELINE + 0.1]) > 1.0

    def test_score_below_baseline_decreases_weight(self):
        assert _weight_from_scores([0.0]) < 1.0

    def test_magnitude_capped_at_max(self):
        assert _weight_from_scores([100.0]) == ATOM_WEIGHT_MAX

    def test_magnitude_capped_at_min(self):
        assert _weight_from_scores([-100.0]) == ATOM_WEIGHT_MIN

    def test_averages_multiple_scores(self):
        w = _weight_from_scores([ENGAGEMENT_RATE_BASELINE, ENGAGEMENT_RATE_BASELINE])
        assert w == 1.0


class TestRecordMetricSnapshot:
    @pytest.mark.asyncio
    async def test_unknown_piece_raises_not_found(self):
        conn = AsyncMock()
        conn.fetchval.return_value = None
        pool = _mock_pool(conn)
        with pytest.raises(PieceNotFoundError):
            await record_metric_snapshot(TENANT, "piece_x", 100, 10, 1, "user@x", pool)

    @pytest.mark.asyncio
    async def test_piece_owned_by_other_tenant_raises_not_owned(self):
        conn = AsyncMock()
        conn.fetchval.return_value = str(uuid.uuid4())  # different tenant owns it
        pool = _mock_pool(conn)
        with pytest.raises(PieceNotOwnedError):
            await record_metric_snapshot(TENANT, "piece_x", 100, 10, 1, "user@x", pool)

    @pytest.mark.asyncio
    async def test_own_piece_inserts_snapshot(self):
        conn = AsyncMock()
        snapshot_id = uuid.uuid4()
        conn.fetchval.side_effect = [str(TENANT), snapshot_id]
        pool = _mock_pool(conn)
        result = await record_metric_snapshot(TENANT, "piece_x", 100, 10, 1, "user@x", pool)
        assert result == snapshot_id


class TestRollupAtomWeights:
    @pytest.mark.asyncio
    async def test_below_confidence_gate_not_adjusted(self):
        """Only 2 posts use this atom — CONFIDENCE_ATOM_MIN_POSTS=3 — weight untouched."""
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"piece_id": "p1", "atom_ids_json": json.dumps(["atom_1"]), "reach": 1000, "engagement": 100},
            {"piece_id": "p2", "atom_ids_json": json.dumps(["atom_1"]), "reach": 1000, "engagement": 100},
        ]
        pool = _mock_pool(conn)
        moved = await rollup_atom_weights(TENANT, pool)
        assert moved == {}
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_confidence_gate_cleared_updates_weight(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"piece_id": f"p{i}", "atom_ids_json": json.dumps(["atom_1"]),
             "reach": 1000, "engagement": 200}  # rate 0.2, well above baseline 0.05
            for i in range(3)
        ]
        pool = _mock_pool(conn)
        moved = await rollup_atom_weights(TENANT, pool)
        assert "atom_1" in moved
        assert moved["atom_1"] > 1.0
        conn.execute.assert_awaited_once()
        query, weight_param, atom_id_param, owner_scope_param = conn.execute.call_args[0]
        assert "tour_atoms" in query
        assert atom_id_param == "atom_1"
        assert owner_scope_param == str(TENANT)

    @pytest.mark.asyncio
    async def test_pieces_with_no_reach_excluded_from_average(self):
        """A piece with reach=None never contributes a score — 'unknown stays unknown', never
        guessed as 0."""
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"piece_id": "p1", "atom_ids_json": json.dumps(["atom_1"]), "reach": None, "engagement": 5},
            {"piece_id": "p2", "atom_ids_json": json.dumps(["atom_1"]), "reach": 1000, "engagement": 50},
            {"piece_id": "p3", "atom_ids_json": json.dumps(["atom_1"]), "reach": 1000, "engagement": 50},
        ]
        pool = _mock_pool(conn)
        moved = await rollup_atom_weights(TENANT, pool)
        # only 2 REAL scores (p2/p3) -> below the 3-post gate despite 3 rows total
        assert moved == {}

    @pytest.mark.asyncio
    async def test_jsonb_string_shape_parsed(self):
        """acp_v2_slots.payload->'atom_ids' arrives as a raw JSON string via asyncpg (no jsonb
        codec, same gap _row_to_atom already works around) — confirms this module handles it."""
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"piece_id": f"p{i}", "atom_ids_json": '["atom_1", "atom_2"]',
             "reach": 1000, "engagement": 200}
            for i in range(3)
        ]
        pool = _mock_pool(conn)
        moved = await rollup_atom_weights(TENANT, pool)
        assert "atom_1" in moved and "atom_2" in moved
