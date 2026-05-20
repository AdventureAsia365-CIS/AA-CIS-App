"""
test_s2_keyword_cap: DataForSEO returning 500 keywords should be capped at ACP_MAX_KEYWORDS_PER_RUN.
Default cap is 200. Override via env var to test smaller caps.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_pool_no_cache():
    """Pool that returns no cached visibility_reports and no published_content rows."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _build_dataforseo_response(num_keywords: int) -> dict:
    """Build a mock DataForSEO API response with num_keywords items."""
    items = [{"keyword": f"keyword {i}", "search_volume": 100 + i} for i in range(num_keywords)]
    return {
        "tasks": [{"result": [{"items": items}]}]
    }


def _make_s3():
    s3 = MagicMock()
    s3.put_object = MagicMock()
    return s3


@pytest.mark.asyncio
async def test_keyword_cap_default_200():
    """DataForSEO returns 500 keywords → stored payload contains <= 200."""
    from services.acp.s2.tools.dataforseo import make_dataforseo_node

    pool = _make_pool_no_cache()
    s3 = _make_s3()
    api_keys = {"DATAFORSEO_LOGIN": "login", "DATAFORSEO_PASSWORD": "pass"}

    node = make_dataforseo_node(pool, s3, api_keys)
    state = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "country": "Thailand",
        "tenant_id": "00000000-0000-0000-0000-000000000002",
        "completed_tools": [],
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=_build_dataforseo_response(500))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await node(state)

    assert result["keyword_count"] <= 200, f"Expected <= 200, got {result['keyword_count']}"
    assert result["keyword_count"] == 200

    # Verify what was written to S3
    call_kwargs = s3.put_object.call_args[1]
    stored_payload = json.loads(call_kwargs["Body"])
    assert len(stored_payload["keywords"]) == 200


@pytest.mark.asyncio
async def test_keyword_cap_env_override(monkeypatch):
    """ACP_MAX_KEYWORDS_PER_RUN=50 caps at 50 even when API returns 200."""
    monkeypatch.setenv("ACP_MAX_KEYWORDS_PER_RUN", "50")

    # Re-import module to pick up new env var
    import importlib
    import services.acp.s2.tools.dataforseo as mod
    importlib.reload(mod)

    pool = _make_pool_no_cache()
    s3 = _make_s3()
    api_keys = {"DATAFORSEO_LOGIN": "login", "DATAFORSEO_PASSWORD": "pass"}

    node = mod.make_dataforseo_node(pool, s3, api_keys)
    state = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "country": "Vietnam",
        "tenant_id": "00000000-0000-0000-0000-000000000002",
        "completed_tools": [],
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=_build_dataforseo_response(200))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await node(state)

    assert result["keyword_count"] == 50
