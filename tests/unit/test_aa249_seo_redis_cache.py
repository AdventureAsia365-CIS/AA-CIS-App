"""AA-249: process_seo() now defaults to a real cache (Redis singleton) instead
of a LocalCache() built fresh per call (which never actually cached anything
across tours/requests — confirmed via S88 batch test: 5/5 calls logged
cache_miss, 0 cache_hit). These are interface-level unit tests: they exercise
the cache.get/cache.set contract process_seo() relies on, using a stateful
fake cache — no real Redis/ElastiCache connection is made.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.seo_intelligence import handler as seo_handler


class _StatefulFakeCache:
    """In-memory cache stub that actually remembers what was set — unlike
    AA-203's _FakeCache (always a miss), this lets us prove a second
    process_seo() call for the same seed hits the cache."""

    def __init__(self):
        self.store = {}
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key):
        self.get_calls += 1
        return self.store.get(key)

    async def set(self, key, value, ttl_seconds=None):
        self.set_calls += 1
        self.store[key] = value


def _seo_data():
    return {
        "keywords": {"top_keywords": ["South Korea tours"], "search_volumes": {}},
        "people_also_ask": [],
        "related_keywords": [],
        "keyword_ideas": [{"keyword": "south korea tours", "search_volume": 100}],
        "destination": "South Korea tours",
        "activity": None,
    }


async def _run_with_shared_cache(cache, seo_data):
    insert_mock = AsyncMock(return_value="fake-seo-id")
    repo_mock = MagicMock()
    repo_mock.insert = insert_mock

    fake_client = MagicMock()
    fake_client.fetch_all = AsyncMock(return_value=seo_data)

    fake_conn = AsyncMock()

    with patch.object(seo_handler, "DataForSEOClient", return_value=fake_client), \
         patch.object(seo_handler, "SeoContextRepository", return_value=repo_mock), \
         patch.object(seo_handler, "asyncpg") as asyncpg_mock, \
         patch.object(seo_handler, "get_database_url", return_value="postgres://stub"):
        asyncpg_mock.connect = AsyncMock(return_value=fake_conn)
        result = await seo_handler.process_seo(
            tour_id="11111111-1111-1111-1111-111111111111",
            destination="South Korea tours",
            seed="South Korea tours",
            tenant_id=None,
            seo_mode="dataforseo",
            cache=cache,
        )
    return result, fake_client.fetch_all


@pytest.mark.asyncio
async def test_second_call_same_seed_is_cache_hit_no_second_dataforseo_call():
    cache = _StatefulFakeCache()
    seo_data = _seo_data()

    result_1, fetch_all_1 = await _run_with_shared_cache(cache, seo_data)
    assert result_1["status"] == "fetched"
    assert fetch_all_1.await_count == 1

    # Second tour, same country/seed, same cache instance (simulates 2 same-country
    # tours in one batch sharing the TTL window) — must NOT call DataForSEO again.
    result_2, fetch_all_2 = await _run_with_shared_cache(cache, seo_data)
    assert result_2["status"] == "cache_hit"
    assert fetch_all_2.await_count == 0
    assert result_2["data"] == seo_data


@pytest.mark.asyncio
async def test_cache_get_and_set_both_invoked_on_a_miss():
    cache = _StatefulFakeCache()
    await _run_with_shared_cache(cache, _seo_data())

    assert cache.get_calls == 1
    assert cache.set_calls == 1


@pytest.mark.asyncio
async def test_default_cache_is_redis_singleton_not_local_cache():
    """No cache= passed -> process_seo() must build RedisCache(client=_seo_redis_client),
    not a per-call LocalCache() (that was the AA-249 root behavior: a fresh in-memory
    dict per call meant no caching ever actually happened between tours)."""
    fake_redis_cache = MagicMock()
    fake_redis_cache.get = AsyncMock(return_value=None)
    fake_redis_cache.set = AsyncMock()

    insert_mock = AsyncMock(return_value="fake-seo-id")
    repo_mock = MagicMock()
    repo_mock.insert = insert_mock

    fake_client = MagicMock()
    fake_client.fetch_all = AsyncMock(return_value=_seo_data())

    fake_conn = AsyncMock()

    with patch.object(seo_handler, "RedisCache", return_value=fake_redis_cache) as redis_cache_cls, \
         patch.object(seo_handler, "DataForSEOClient", return_value=fake_client), \
         patch.object(seo_handler, "SeoContextRepository", return_value=repo_mock), \
         patch.object(seo_handler, "asyncpg") as asyncpg_mock, \
         patch.object(seo_handler, "get_database_url", return_value="postgres://stub"):
        asyncpg_mock.connect = AsyncMock(return_value=fake_conn)
        await seo_handler.process_seo(
            tour_id="11111111-1111-1111-1111-111111111111",
            destination="South Korea tours",
            seed="South Korea tours",
            tenant_id=None,
            seo_mode="dataforseo",
            # cache intentionally omitted — exercise the default.
        )

    redis_cache_cls.assert_called_once_with(client=seo_handler._seo_redis_client)
    assert fake_redis_cache.get.await_count == 1
    assert fake_redis_cache.set.await_count == 1
