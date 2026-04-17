import pytest
import asyncio
from shared.cache.local_cache import LocalCache

@pytest.mark.asyncio
async def test_cache_set_get():
    cache = LocalCache()
    await cache.set("seo:vietnam", {"keywords": ["vietnam tour"]}, ttl_seconds=60)
    result = await cache.get("seo:vietnam")
    assert result == {"keywords": ["vietnam tour"]}

@pytest.mark.asyncio
async def test_cache_miss():
    cache = LocalCache()
    result = await cache.get("seo:nonexistent")
    assert result is None

@pytest.mark.asyncio
async def test_cache_expired():
    cache = LocalCache()
    await cache.set("seo:expired", {"data": "old"}, ttl_seconds=0)
    await asyncio.sleep(0.01)
    result = await cache.get("seo:expired")
    assert result is None

def test_cache_key_format():
    assert LocalCache.make_key("Vietnam", "trekking") == "seo:vietnam:trekking"

def test_cache_key_no_activity():
    assert LocalCache.make_key("Thailand") == "seo:thailand"

def test_cache_key_spaces():
    assert LocalCache.make_key("Sri Lanka", "beach tour") == "seo:sri_lanka:beach_tour"
