"""
test_s2_cannibalization: When published_content has a keyword matching the DataForSEO results,
existing_content_risk should be TRUE and search_volume should be scaled by 0.2.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_pool_with_published(published_keywords: list[str]):
    """
    Pool that:
    - Returns no cached visibility_reports (first fetchrow call → None)
    - Returns published_content rows for the given keywords (fetch call)
    """
    conn = AsyncMock()

    async def _fetchrow(*args, **kwargs):
        return None  # No cache hit

    async def _fetch(*args, **kwargs):
        return [{"primary_keyword": kw} for kw in published_keywords]

    conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    conn.fetch = AsyncMock(side_effect=_fetch)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _build_dataforseo_response(keywords: list[str], volume: int = 1000) -> dict:
    items = [{"keyword": kw, "search_volume": volume} for kw in keywords]
    return {"tasks": [{"result": [{"items": items}]}]}


def _make_s3():
    s3 = MagicMock()
    s3.put_object = MagicMock()
    return s3


@pytest.mark.asyncio
async def test_cannibalization_sets_risk_flag():
    """When a published keyword matches fetched keywords, existing_content_risk=True."""
    from services.acp.s2.tools.dataforseo import make_dataforseo_node

    overlapping_keyword = "thailand tours"
    pool = _make_pool_with_published([overlapping_keyword])
    s3 = _make_s3()
    api_keys = {"DATAFORSEO_LOGIN": "login", "DATAFORSEO_PASSWORD": "pass"}

    node = make_dataforseo_node(pool, s3, api_keys)
    state = {
        "run_id": "cccccccc-0000-0000-0000-000000000001",
        "country": "Thailand",
        "tenant_id": "dddddddd-0000-0000-0000-000000000001",
        "completed_tools": [],
    }

    fetched_keywords = [overlapping_keyword, "bangkok excursions", "phuket beach tours"]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=_build_dataforseo_response(fetched_keywords))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await node(state)

    assert result["existing_content_risk"] is True

    # Verify volumes were scaled down by 0.2
    call_kwargs = s3.put_object.call_args[1]
    stored = json.loads(call_kwargs["Body"])
    for kw_item in stored["keywords"]:
        assert kw_item["search_volume"] == int(1000 * 0.2), (
            f"Expected volume={int(1000*0.2)}, got {kw_item['search_volume']}"
        )


@pytest.mark.asyncio
async def test_no_cannibalization_when_no_overlap():
    """When no published keywords overlap, existing_content_risk=False."""
    from services.acp.s2.tools.dataforseo import make_dataforseo_node

    pool = _make_pool_with_published(["sri lanka tours", "colombo day trips"])
    s3 = _make_s3()
    api_keys = {"DATAFORSEO_LOGIN": "login", "DATAFORSEO_PASSWORD": "pass"}

    node = make_dataforseo_node(pool, s3, api_keys)
    state = {
        "run_id": "eeeeeeee-0000-0000-0000-000000000001",
        "country": "Thailand",
        "tenant_id": "ffffffff-0000-0000-0000-000000000001",
        "completed_tools": [],
    }

    # Thailand keywords — no overlap with Sri Lanka published content
    fetched_keywords = ["thailand tours", "bangkok excursions"]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=_build_dataforseo_response(fetched_keywords, volume=500))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await node(state)

    assert result["existing_content_risk"] is False

    call_kwargs = s3.put_object.call_args[1]
    stored = json.loads(call_kwargs["Body"])
    for kw_item in stored["keywords"]:
        assert kw_item["search_volume"] == 500, "Volumes should not be scaled when no risk"
