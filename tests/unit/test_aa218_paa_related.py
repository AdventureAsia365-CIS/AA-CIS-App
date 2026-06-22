"""AA-218: persist people_also_ask + related_keywords into seo_context.

DFS (DataForSEOClient.fetch_all) already returns both top-level lists; the handler
dropped them and the repository never stored them. These tests pin the full path:
  1. Repository.insert  → both values land in the INSERT args at $11 / $12.
  2. Handler dict        → repo.insert receives both keys (json.dumps'd).
  3. Endpoint return     → real columns parsed via _as_list; empty row → [].
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.seo_intelligence import handler as seo_handler
from shared.repository.seo_context_repository import SeoContextRepository
from api.routers import admin_pipeline


# ── Group 1: repository persists the 2 fields at $11 / $12 ─────────────────────

@pytest.mark.asyncio
async def test_repository_insert_sends_paa_and_related_as_params_11_12():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": "fake-id"})
    repo = SeoContextRepository(conn, tenant_slug="aa_internal")

    paa = json.dumps(["what is the best time to visit korea?"])
    related = json.dumps(["korea tours", "seoul packages"])
    await repo.insert({
        "tour_id": "11111111-1111-1111-1111-111111111111",
        "keyword_search": "South Korea tours",
        "people_also_ask": paa,
        "related_keywords": related,
    })

    assert conn.fetchrow.await_count == 1
    args = conn.fetchrow.await_args.args        # (sql, $1, $2, ... $12)
    sql = args[0]
    assert "people_also_ask" in sql and "related_keywords" in sql
    assert "$12" in sql
    # appended at the END → $11 = people_also_ask, $12 = related_keywords
    assert args[11] == paa
    assert args[12] == related


@pytest.mark.asyncio
async def test_repository_insert_defaults_paa_related_to_empty_list():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": "fake-id"})
    repo = SeoContextRepository(conn, tenant_slug="aa_internal")

    await repo.insert({
        "tour_id": "11111111-1111-1111-1111-111111111111",
        "keyword_search": "South Korea tours",
    })  # no paa/related keys

    args = conn.fetchrow.await_args.args
    assert args[11] == "[]"
    assert args[12] == "[]"


# ── Group 2: handler forwards both keys to repo.insert ─────────────────────────

class _FakeCache:
    def __init__(self):
        self.store = {}

    async def get(self, _key):
        return None

    async def set(self, key, value, ttl_seconds=None):
        self.store[key] = value


async def _run_and_capture(seo_data):
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
        await seo_handler.process_seo(
            tour_id="11111111-1111-1111-1111-111111111111",
            destination="South Korea tours",
            seed="South Korea tours",
            tenant_id=None,
            seo_mode="dataforseo",
            cache=_FakeCache(),
        )

    assert insert_mock.await_count == 1
    return insert_mock.await_args.args[0]


@pytest.mark.asyncio
async def test_handler_persists_paa_and_related_from_seo_data():
    seo_data = {
        "keywords": {"top_keywords": [], "search_volumes": {}},
        "keyword_ideas": [],
        "people_also_ask": ["is korea safe?", "best month for korea"],
        "related_keywords": ["korea tours", "seoul trip"],
    }
    payload = await _run_and_capture(seo_data)

    assert json.loads(payload["people_also_ask"]) == ["is korea safe?", "best month for korea"]
    assert json.loads(payload["related_keywords"]) == ["korea tours", "seoul trip"]


@pytest.mark.asyncio
async def test_handler_defaults_when_seo_data_missing_keys():
    seo_data = {"keywords": {"top_keywords": [], "search_volumes": {}}, "keyword_ideas": []}
    payload = await _run_and_capture(seo_data)

    assert json.loads(payload["people_also_ask"]) == []
    assert json.loads(payload["related_keywords"]) == []


# ── Group 3: endpoint returns the real columns (parsed), [] when no row ─────────

class _FakeConn:
    def __init__(self, seo_row):
        self._seo_row = seo_row

    async def fetchrow(self, query, *args):
        if "raw_tours" in query:
            return {"tenant_id": "00000000-0000-0000-0000-000000000001", "country": "South Korea"}
        if "seo_context" in query:
            return self._seo_row
        return None  # TenantConfigService etc. — buyer-market branch degrades gracefully


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


class _FakeRequest:
    def __init__(self, pool):
        self.app = type("A", (), {"state": type("S", (), {"pool": pool})()})()


async def _call_seo(seo_row):
    request = _FakeRequest(_FakePool(_FakeConn(seo_row)))
    with patch.object(admin_pipeline, "verify_admin_secret", lambda *_a, **_k: None):
        return await admin_pipeline.get_tour_seo_context(
            "11111111-1111-1111-1111-111111111111", request, "secret"
        )


@pytest.mark.asyncio
async def test_endpoint_returns_persisted_paa_and_related_parsed():
    seo_row = {
        "keyword_search": "South Korea tours", "provider": "dataforseo",
        "keyword_ideas": "[]", "top_keywords": "[]",
        "demographics": "{}", "trends": "{}",
        "people_also_ask": json.dumps(["is korea safe?", "best month for korea"]),
        "related_keywords": json.dumps(["korea tours", "seoul trip"]),
        "fetched_at": None, "expires_at": None,
    }
    resp = await _call_seo(seo_row)

    assert resp["has_data"] is True
    assert resp["people_also_ask"] == ["is korea safe?", "best month for korea"]
    assert resp["related_keywords"] == ["korea tours", "seoul trip"]
    assert resp["notes"] is None


@pytest.mark.asyncio
async def test_endpoint_returns_empty_lists_when_no_seo_row():
    resp = await _call_seo(None)

    assert resp["has_data"] is False
    assert resp["people_also_ask"] == []
    assert resp["related_keywords"] == []
