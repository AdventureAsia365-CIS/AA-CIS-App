"""
tests/unit/test_aa298_dataforseo.py — services/acp_produce/dataforseo.py::parse_top_pages()
(N7 P0-2, AA-298).

No live DataForSEO calls — httpx.AsyncClient.post/get patched. The response
shapes mocked here match a live smoke test against the real API (24/07/2026,
target https://www.lonelyplanet.com/sri-lanka) captured while building this
module, including the two non-obvious real behaviors it caught: a redirected
target needs the post-redirect url for content_parsing, and body text lives
under page_content.main_topic[].primary_content[].text.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_produce.dataforseo import parse_top_pages

SERP_RESPONSE = {
    "tasks": [{"result": [{"items": [
        {"type": "organic", "url": "https://example.com/sri-lanka-guide"},
        {"type": "people_also_ask"},  # non-organic item must be skipped
    ]}]}]
}
TASK_POST_RESPONSE = {"tasks": [{"id": "task-123"}]}
SUMMARY_FINISHED = {"tasks": [{"result": [{"crawl_progress": "finished"}]}]}
SUMMARY_IN_PROGRESS = {"tasks": [{"result": [{"crawl_progress": "in_progress"}]}]}
PAGES_RESPONSE = {"tasks": [{"result": [{"items": [{"url": "https://example.com/"}]}]}]}  # redirected!
CONTENT_PARSING_RESPONSE = {
    "tasks": [{"result": [{"items": [{"page_content": {
        "header": {"primary_content": [{"text": "nav link text — must NOT appear in output"}]},
        "main_topic": [
            {"main_title": "Best time to visit", "primary_content": [{"text": "December to March is dry season."}]},
            {"main_title": "Getting around", "primary_content": [{"text": "Trains connect major cities."}]},
        ],
    }}]}]}]}


def _resp(json_data, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data
    m.raise_for_status = MagicMock()
    return m


@pytest.mark.asyncio
async def test_parse_top_pages_returns_real_body_text_not_nav_chrome():
    client = AsyncMock()
    client.post.side_effect = [
        _resp(SERP_RESPONSE),           # _top_ranking_urls
        _resp(TASK_POST_RESPONSE),      # task_post
        _resp(PAGES_RESPONSE),          # on_page/pages (redirect lookup)
        _resp(CONTENT_PARSING_RESPONSE),  # content_parsing
    ]
    client.get.return_value = _resp(SUMMARY_FINISHED)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("services.acp_produce.dataforseo.httpx.AsyncClient", return_value=client):
        pages = await parse_top_pages("user", "pass", "sri lanka tours", "US", n=3)

    assert len(pages) == 1
    page = pages[0]
    assert page["url"] == "https://example.com/sri-lanka-guide"  # original target
    assert page["crawled_url"] == "https://example.com/"  # actual crawled (post-redirect)
    assert "December to March is dry season." in page["content"]
    assert "Trains connect major cities." in page["content"]
    assert "nav link text" not in page["content"]  # header chrome excluded


@pytest.mark.asyncio
async def test_parse_top_pages_content_parsing_uses_crawled_url_not_target():
    """The exact bug a live smoke test caught: passing the original target url
    (pre-redirect) to content_parsing returns items_count=0."""
    client = AsyncMock()
    client.post.side_effect = [
        _resp(SERP_RESPONSE),
        _resp(TASK_POST_RESPONSE),
        _resp(PAGES_RESPONSE),
        _resp(CONTENT_PARSING_RESPONSE),
    ]
    client.get.return_value = _resp(SUMMARY_FINISHED)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("services.acp_produce.dataforseo.httpx.AsyncClient", return_value=client):
        await parse_top_pages("user", "pass", "sri lanka tours", "US", n=3)

    content_parsing_call = client.post.call_args_list[3]
    assert content_parsing_call.kwargs["json"][0]["url"] == "https://example.com/"  # NOT the original target


@pytest.mark.asyncio
async def test_parse_top_pages_degrades_on_crawl_timeout_not_fabricated_content():
    client = AsyncMock()
    client.post.side_effect = [_resp(SERP_RESPONSE), _resp(TASK_POST_RESPONSE)]
    client.get.return_value = _resp(SUMMARY_IN_PROGRESS)  # never finishes
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("services.acp_produce.dataforseo.httpx.AsyncClient", return_value=client), \
         patch("services.acp_produce.dataforseo._POLL_BUDGET_S", 0.01), \
         patch("services.acp_produce.dataforseo._POLL_INTERVAL_S", 0.01), \
         patch("services.acp_produce.dataforseo.asyncio.sleep", new=AsyncMock()):
        pages = await parse_top_pages("user", "pass", "sri lanka tours", "US", n=3)

    assert pages == []  # dropped, not returned with content: ""


@pytest.mark.asyncio
async def test_parse_top_pages_no_credentials_returns_empty_no_call():
    with patch("services.acp_produce.dataforseo.httpx.AsyncClient") as mock_client_cls:
        pages = await parse_top_pages("", "", "sri lanka tours", "US")
    assert pages == []
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_parse_top_pages_no_ranking_urls_returns_empty():
    client = AsyncMock()
    client.post.return_value = _resp({"tasks": [{"result": [{"items": []}]}]})
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("services.acp_produce.dataforseo.httpx.AsyncClient", return_value=client):
        pages = await parse_top_pages("user", "pass", "an obscure keyword", "US")

    assert pages == []
