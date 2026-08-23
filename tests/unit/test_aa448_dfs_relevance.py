"""AA-448 — dfs_relevance (tour-level DFS search-demand signal).

score_dfs_relevance() is pure — tested with no mocks. fetch_dfs_relevance_by_tour() is
DB-backed — tested with a mocked asyncpg pool, same pool.acquire() mocking shape as
test_aa301_quarter.py's TestFetchAtomsByTripDbWrapper / test_aa299_atom_insert.py.
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.acp_shared.dfs_relevance import (
    DfsRelevanceThresholds,
    fetch_dfs_relevance_by_tour,
    score_dfs_relevance,
)


class TestScoreDfsRelevance:
    def test_empty_list_returns_med(self):
        """No seo_context row at all for this tour -> honest middle default, not LOW."""
        assert score_dfs_relevance([]) == "MED"

    def test_all_none_filtered_upstream_same_as_empty(self):
        """fetch_dfs_relevance_by_tour() filters out None search_volume before calling this —
        confirm the pure function's own empty-list contract matches that expectation."""
        assert score_dfs_relevance([]) == "MED"

    def test_below_low_max_is_low(self):
        assert score_dfs_relevance([10, 20]) == "LOW"

    def test_at_low_max_boundary_is_med_not_low(self):
        # low_max=50 -> volume < 50 is LOW, volume == 50 is already MED (exclusive boundary)
        assert score_dfs_relevance([50]) == "MED"

    def test_between_thresholds_is_med(self):
        assert score_dfs_relevance([10, 200]) == "MED"  # max=200, in [50, 500)

    def test_at_high_min_boundary_is_high(self):
        assert score_dfs_relevance([499, 500]) == "HIGH"

    def test_above_high_min_is_high(self):
        assert score_dfs_relevance([1200]) == "HIGH"

    def test_uses_max_not_average(self):
        """One strong keyword should not be diluted by a pile of near-zero long-tail ideas —
        confirms MAX semantics, not AVG (which would land this in MED/LOW instead)."""
        volumes = [0, 0, 0, 0, 0, 0, 0, 0, 0, 900]
        assert score_dfs_relevance(volumes) == "HIGH"

    def test_custom_thresholds_respected(self):
        thresholds = DfsRelevanceThresholds(low_max=100, high_min=1000)
        assert score_dfs_relevance([80], thresholds) == "LOW"
        assert score_dfs_relevance([500], thresholds) == "MED"
        assert score_dfs_relevance([1500], thresholds) == "HIGH"

    def test_output_is_one_of_the_three_literal_values(self):
        """Must match services.acp_planning.models's HIGH/MED/LOW convention exactly —
        compute_quarter_plan()'s SIGNAL_SCORE_MAP has no other keys."""
        for volumes in ([], [1], [100], [10000]):
            assert score_dfs_relevance(volumes) in ("HIGH", "MED", "LOW")


class TestFetchDfsRelevanceByTourDbWrapper:
    @pytest.mark.asyncio
    async def test_empty_tour_ids_short_circuits_no_query(self):
        pool = MagicMock()
        result = await fetch_dfs_relevance_by_tour([], pool)
        assert result == {}
        pool.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_real_asyncpg_string_shaped_jsonb_parsed(self):
        """keyword_ideas arrives as a raw JSON string (asyncpg has no jsonb codec registered on
        this app's connections — same gap AA-300/_row_to_atom's _parse_jsonb already found),
        not a pre-parsed list — confirms this wrapper handles that shape."""
        tour_id = uuid.uuid4()
        conn = AsyncMock()
        conn.fetch.return_value = [{
            "tour_id": tour_id,
            "keyword_ideas": json.dumps([
                {"keyword": "sapa trekking", "search_volume": 720, "competition": "LOW"},
                {"keyword": "sapa homestay", "search_volume": None, "competition": None},
            ]),
        }]
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        result = await fetch_dfs_relevance_by_tour([tour_id], pool)

        assert result == {tour_id: "HIGH"}  # max(720) >= 500

    @pytest.mark.asyncio
    async def test_missing_tour_id_absent_from_result_not_defaulted(self):
        """A tour with no seo_context row (empty rows from the query) must be ABSENT from the
        returned dict, not silently inserted as MED — callers default missing keys themselves
        (see compute_quarter_plan's own dfs_relevance_by_trip.get(t.id, 'MED') pattern)."""
        tour_id = uuid.uuid4()
        conn = AsyncMock()
        conn.fetch.return_value = []
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        result = await fetch_dfs_relevance_by_tour([tour_id], pool)

        assert result == {}
        assert tour_id not in result

    @pytest.mark.asyncio
    async def test_all_null_search_volumes_scores_med(self):
        """Real, live-confirmed case (AA-439-05): a seo_context row exists but every
        keyword_idea's search_volume is null — must score MED, not crash or default LOW."""
        tour_id = uuid.uuid4()
        conn = AsyncMock()
        conn.fetch.return_value = [{
            "tour_id": tour_id,
            "keyword_ideas": json.dumps([
                {"keyword": "x", "search_volume": None},
                {"keyword": "y", "search_volume": None},
            ]),
        }]
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        result = await fetch_dfs_relevance_by_tour([tour_id], pool)

        assert result == {tour_id: "MED"}
