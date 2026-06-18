"""AA-203 Bug 1: process_seo must persist the top-level keyword_ideas LIST
(AA-197 full-metric dicts) into seo_context.keyword_ideas — NOT the often-empty
keywords.search_volumes dict. top_keywords must keep reading keywords.top_keywords.
"""

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.seo_intelligence import handler as seo_handler


class _FakeCache:
    """Async cache stub — always a miss so the DataForSEO + persist path runs."""

    def __init__(self):
        self.store = {}

    async def get(self, _key):
        return None

    async def set(self, key, value, ttl_seconds=None):
        self.store[key] = value


def _make_seo_data(keyword_ideas, search_volumes=None, top_keywords=None):
    """fetch_all() output shape: keyword_ideas is TOP-LEVEL; search_volumes nested."""
    return {
        "keywords": {
            "top_keywords": top_keywords if top_keywords is not None else [],
            "search_volumes": search_volumes if search_volumes is not None else {},
        },
        "people_also_ask": [],
        "related_keywords": [],
        "keyword_ideas": keyword_ideas,
        "destination": "South Korea tours",
        "activity": None,
    }


async def _run_and_capture(seo_data):
    """Run process_seo with every external I/O mocked; return (insert_payload, result)."""
    insert_mock = AsyncMock(return_value="fake-seo-id")
    repo_mock = MagicMock()
    repo_mock.insert = insert_mock

    fake_client = MagicMock()
    fake_client.fetch_all = AsyncMock(return_value=seo_data)

    fake_conn = AsyncMock()  # await conn.close() in finally

    with patch.object(seo_handler, "DataForSEOClient", return_value=fake_client), \
         patch.object(seo_handler, "SeoContextRepository", return_value=repo_mock), \
         patch.object(seo_handler, "asyncpg") as asyncpg_mock, \
         patch.object(seo_handler, "get_database_url", return_value="postgres://stub"):
        asyncpg_mock.connect = AsyncMock(return_value=fake_conn)
        result = await seo_handler.process_seo(
            tour_id="11111111-1111-1111-1111-111111111111",
            destination="South Korea tours",
            seed="South Korea tours",
            tenant_id=None,            # skip the buyer-market resolve branch
            seo_mode="dataforseo",
            cache=_FakeCache(),
        )

    assert insert_mock.await_count == 1, "repo.insert was not called exactly once"
    payload = insert_mock.await_args.args[0]
    return payload, result


# ── Test 1: correct key — list, not empty search_volumes dict ──────────────────

@pytest.mark.asyncio
async def test_persists_top_level_keyword_ideas_list_not_search_volumes():
    ideas = [
        {"keyword": "hiking in South Korea", "search_volume": 320,
         "competition": "LOW", "competition_index": 5, "cpc": 0.93},
        {"keyword": "best hikes seoul", "search_volume": 110,
         "competition": "MEDIUM", "competition_index": 33, "cpc": 1.2},
    ]
    # search_volumes deliberately EMPTY — the old buggy code would have stored {}.
    seo_data = _make_seo_data(ideas, search_volumes={})

    payload, _ = await _run_and_capture(seo_data)
    stored = json.loads(payload["keyword_ideas"])

    assert isinstance(stored, list), "keyword_ideas must be a list, not a dict"
    assert stored != {}, "must NOT store the empty search_volumes dict"
    assert len(stored) == 2
    assert stored[0]["keyword"] == "hiking in South Korea"
    assert stored[0]["search_volume"] == 320
    assert "cpc" in stored[0]


# ── Test 2: empty fallback — no keyword_ideas key → [] (no raise) ──────────────

@pytest.mark.asyncio
async def test_persists_empty_list_when_keyword_ideas_key_absent():
    seo_data = {"keywords": {"top_keywords": [], "search_volumes": {}}}  # no keyword_ideas

    payload, _ = await _run_and_capture(seo_data)
    stored = json.loads(payload["keyword_ideas"])

    assert stored == []


# ── Test 3: default=str safe — Decimal cpc must not raise ──────────────────────

@pytest.mark.asyncio
async def test_keyword_ideas_with_decimal_cpc_serializes_via_default_str():
    ideas = [{"keyword": "korea trek", "search_volume": 50,
              "competition": "LOW", "competition_index": 7, "cpc": Decimal("1.37")}]
    seo_data = _make_seo_data(ideas)

    payload, _ = await _run_and_capture(seo_data)  # must not raise TypeError
    stored = json.loads(payload["keyword_ideas"])

    # default=str turns Decimal into its string form
    assert stored[0]["cpc"] == "1.37"


# ── Test 4: no regression — top_keywords still from keywords.top_keywords ──────

@pytest.mark.asyncio
async def test_top_keywords_still_read_from_keywords_top_keywords():
    ideas = [{"keyword": "kw1", "search_volume": 5, "cpc": 0.1}]
    seo_data = _make_seo_data(ideas, top_keywords=["korea tours", "seoul trip"])

    payload, _ = await _run_and_capture(seo_data)
    stored_top = json.loads(payload["top_keywords"])

    assert stored_top == ["korea tours", "seoul trip"]
