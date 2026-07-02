"""AA-249: seo_context UNIQUE moved from cache_key to tour_id (migration 075).

Root cause: cache_key = f"{country} tours" (country-level) was the UNIQUE
constraint target, so ON CONFLICT (cache_key) DO UPDATE collapsed every
same-country tour onto ONE physical row — whichever tour upserted last "won"
(including tour_id), silently deleting every other same-country tour's row.
Confirmed via live batch test (S88): 5 South Korea tours -> 5 successful
DataForSEO fetches, 5 "seo_inserted" logs, all sharing ONE db row id.

Fix: ON CONFLICT target is now tour_id (matches migration 075's
seo_context_tour_id_key UNIQUE constraint) — every tour gets its own row even
when it shares a cache_key/seed with other tours. cache_key stays in the SET
list as a trace-only column (no longer part of row identity).

These are unit tests against a mocked asyncpg connection (matches the
existing AA-218 test_aa218_paa_related.py convention) — they pin the SQL text
and parameter wiring, not a live-DB row-collision integration test.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from shared.repository.seo_context_repository import SeoContextRepository


def _make_repo():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": "fake-id"})
    return conn, SeoContextRepository(conn, tenant_slug="aa_internal")


@pytest.mark.asyncio
async def test_on_conflict_target_is_tour_id_not_cache_key():
    conn, repo = _make_repo()
    await repo.insert({
        "tour_id": "11111111-1111-1111-1111-111111111111",
        "keyword_search": "South Korea tours",
        "cache_key": "seo:south_korea_tours:2840",
    })

    sql = conn.fetchrow.await_args.args[0]
    assert "ON CONFLICT (tour_id)" in sql
    assert "ON CONFLICT (cache_key)" not in sql


@pytest.mark.asyncio
async def test_set_clause_updates_cache_key_trace_but_not_tour_id():
    conn, repo = _make_repo()
    await repo.insert({
        "tour_id": "11111111-1111-1111-1111-111111111111",
        "keyword_search": "South Korea tours",
        "cache_key": "seo:south_korea_tours:2840",
    })

    sql = conn.fetchrow.await_args.args[0]
    assert "cache_key        = EXCLUDED.cache_key" in sql
    # tour_id is the conflict TARGET now — it must not also self-assign in SET.
    assert "tour_id          = EXCLUDED.tour_id" not in sql


@pytest.mark.asyncio
async def test_two_tours_same_cache_key_each_get_their_own_insert_call():
    """The bug: 2 same-country tours sharing one cache_key used to collapse onto
    ONE db row via ON CONFLICT (cache_key). With the constraint now on tour_id,
    each tour_id is an independent conflict target — verify the repository issues
    a separate, correctly-keyed statement per tour_id rather than silently
    de-duping in application code."""
    conn, repo = _make_repo()
    shared_cache_key = "seo:south_korea_tours:2840"

    await repo.insert({
        "tour_id": "11111111-1111-1111-1111-111111111111",
        "keyword_search": "South Korea tours",
        "cache_key": shared_cache_key,
        "top_keywords": "[\"South Korea tours\"]",
    })
    await repo.insert({
        "tour_id": "22222222-2222-2222-2222-222222222222",
        "keyword_search": "South Korea tours",
        "cache_key": shared_cache_key,
        "top_keywords": "[\"South Korea tours\"]",
    })

    assert conn.fetchrow.await_count == 2
    call_1_args = conn.fetchrow.await_args_list[0].args
    call_2_args = conn.fetchrow.await_args_list[1].args

    # $1 = tour_id — distinct per call, both still carrying the same cache_key ($9).
    assert call_1_args[1] == "11111111-1111-1111-1111-111111111111"
    assert call_2_args[1] == "22222222-2222-2222-2222-222222222222"
    assert call_1_args[9] == shared_cache_key
    assert call_2_args[9] == shared_cache_key
    # Both statements target tour_id for conflict resolution, so at the real
    # UNIQUE(tour_id) constraint (migration 075) these land as 2 separate rows.
    assert "ON CONFLICT (tour_id)" in call_1_args[0]
    assert "ON CONFLICT (tour_id)" in call_2_args[0]


@pytest.mark.asyncio
async def test_cache_key_still_persisted_for_debugging():
    conn, repo = _make_repo()
    await repo.insert({
        "tour_id": "11111111-1111-1111-1111-111111111111",
        "keyword_search": "South Korea tours",
        "cache_key": "seo:south_korea_tours:2840",
    })

    args = conn.fetchrow.await_args.args
    # cache_key is param $9 (tour_id, tenant_id, keyword_search, provider,
    # keyword_ideas, demographics, trends, top_keywords, cache_key, ...).
    assert args[9] == "seo:south_korea_tours:2840"
