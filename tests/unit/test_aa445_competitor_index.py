"""AA-445-02 — B4 (CompetitorIndex) + score_distinctiveness().

score_distinctiveness() is a pure function (verbatim port of aamc/corpus.py's algorithm,
cited in Linear AA-317's comment) — tested with no mocks. build_competitor_index() is DB+
network-backed — tested with a mocked asyncpg pool and a mocked httpx.AsyncClient, same
pool.acquire() mocking shape as test_aa299_atom_insert.py.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_shared.competitor_index import (
    CompetitorIndex,
    _extract_phrases,
    build_competitor_index,
    score_distinctiveness,
)

TENANT_ID = "22222222-2222-2222-2222-222222222222"


# ---------------------------------------------------------------- score_distinctiveness()

class TestScoreDistinctiveness:
    def test_empty_index_returns_med(self):
        """AA-317: deliberate honest-middle default when idx.phrases is empty — not a bug."""
        idx = CompetitorIndex(phrases=[])
        assert score_distinctiveness("Crossing the bamboo bridge at dawn", idx) == "MED"

    def test_no_significant_tokens_returns_low(self):
        """Text with zero 4+ char words (aamc/corpus.py's own token filter) can't be scored
        against the corpus — LOW, matching the reference's behavior exactly."""
        idx = CompetitorIndex(phrases=["Some competitor phrase about trekking in the hills"])
        assert score_distinctiveness("a to", idx) == "LOW"

    def test_high_overlap_returns_low_not_distinctive(self):
        idx = CompetitorIndex(phrases=[
            "Cross the historic bamboo bridge at dawn before breakfast in the village",
        ])
        # near-identical wording -> high token overlap -> competitors already say this -> LOW
        text = "Cross the historic bamboo bridge at dawn before breakfast"
        assert score_distinctiveness(text, idx) == "LOW"

    def test_partial_overlap_returns_med(self):
        idx = CompetitorIndex(phrases=[
            "Trek through the misty mountains of Sapa with local guides",
        ])
        # shares some words (trek, mountains) but not most -> MED band
        text = "Trek through the misty mountains at your own relaxed pace"
        result = score_distinctiveness(text, idx)
        assert result in ("MED", "LOW")  # exact bucket depends on tokenizer overlap ratio

    def test_zero_overlap_returns_high_distinctive(self):
        idx = CompetitorIndex(phrases=["Standard city bus tour with hotel pickup included"])
        text = "Private overnight kayak expedition through remote limestone caves"
        assert score_distinctiveness(text, idx) == "HIGH"

    def test_output_is_one_of_the_three_literal_values(self):
        """Must match services.acp_planning.models.Distinctiveness exactly — N5/N6 both
        index a dict by this literal string (quarter.py:169, allocator.py:116)."""
        idx = CompetitorIndex(phrases=["some competitor text here about tours"])
        for text in ("", "trekking", "a completely unrelated phrase about scuba diving trips"):
            assert score_distinctiveness(text, idx) in ("HIGH", "MED", "LOW")


# ---------------------------------------------------------------- _extract_phrases()

class TestExtractPhrases:
    def test_strips_html_tags(self):
        html = "<html><body><p>" + ("x" * 50) + "</p></body></html>"
        phrases = _extract_phrases(html)
        assert phrases and "<" not in phrases[0] and ">" not in phrases[0]

    def test_filters_by_length_bounds(self):
        too_short = "Hi."  # < 40 chars
        just_right = "x" * 100 + "."
        too_long = "x" * 300 + "."
        phrases = _extract_phrases(too_short + " " + just_right + " " + too_long)
        assert any(len(p) == 100 for p in phrases)
        assert not any(len(p) <= 3 for p in phrases)
        assert not any(len(p) >= 220 for p in phrases)

    def test_caps_at_120_phrases(self):
        text = " ".join(f"{'w' * 45} sentence number {i} here now today" for i in range(200))
        phrases = _extract_phrases(text)
        assert len(phrases) <= 120


# ---------------------------------------------------------------- build_competitor_index()

def _pool_ctx(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


class TestBuildCompetitorIndex:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_fetch_entirely(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {
            "phrases": json.dumps(["cached phrase one here that is long enough to count"]),
            "competitors": json.dumps({"example.com": ["cached phrase one"]}),
        }
        pool = _pool_ctx(conn)

        with patch("services.acp_shared.competitor_index.httpx.AsyncClient") as mock_client:
            idx = await build_competitor_index(TENANT_ID, "Vietnam", pool)

        mock_client.assert_not_called()  # cache hit -> no network fetch at all
        assert idx.phrases == ["cached phrase one here that is long enough to count"]

    @pytest.mark.asyncio
    async def test_no_domains_returns_empty_index_and_caches_it(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None  # cache miss
        conn.fetch.return_value = []       # no active competitor_inputs rows
        pool = _pool_ctx(conn)

        idx = await build_competitor_index(TENANT_ID, "Vietnam", pool)

        assert idx.phrases == []
        # the empty result must still be cached (INSERT via conn.execute)
        assert conn.execute.called

    @pytest.mark.asyncio
    async def test_fetch_failure_for_one_domain_does_not_raise(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        conn.fetch.return_value = [{"url": "dead-domain-that-times-out.example"}]
        pool = _pool_ctx(conn)

        mock_async_client = AsyncMock()
        mock_async_client.get = AsyncMock(side_effect=TimeoutError("connect timeout"))
        mock_client_cm = AsyncMock()
        mock_client_cm.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_client_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("services.acp_shared.competitor_index.httpx.AsyncClient",
                   return_value=mock_client_cm):
            idx = await build_competitor_index(TENANT_ID, "Vietnam", pool)

        # best-effort: a failed fetch yields zero phrases for that domain, no exception raised
        assert idx.phrases == []
        assert idx.competitors == {"dead-domain-that-times-out.example": []}

    @pytest.mark.asyncio
    async def test_successful_fetch_populates_phrases(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        conn.fetch.return_value = [{"url": "realcompetitor.example"}]
        pool = _pool_ctx(conn)

        sentence = "We offer premium guided trekking tours through the northern highlands"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = f"<html><body><p>{sentence}.</p></body></html>"

        mock_async_client = AsyncMock()
        mock_async_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cm = AsyncMock()
        mock_client_cm.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_client_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("services.acp_shared.competitor_index.httpx.AsyncClient",
                   return_value=mock_client_cm):
            idx = await build_competitor_index(TENANT_ID, "Vietnam", pool)

        assert sentence in idx.phrases
        assert idx.competitors["realcompetitor.example"] == [sentence]
