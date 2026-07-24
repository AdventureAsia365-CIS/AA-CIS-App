"""
services.acp_produce.dataforseo — P0-2 fix: real top-ranking-page content for
the N7 brief gap call (ADR-2026-029).

Bug: aa-marketing-v2/aamc/dataforseo.py::parse_top_pages() always returned
content: "" for every page, then asked an LLM "what do these ranking pages
cover that we don't" with nothing to read — a guaranteed hallucination
dressed up as competitive analysis.

Real fix, not a drop-the-feature workaround: DataForSEO OnPage API pricing is
$0.00015/page for a standard crawl (verified docs.dataforseo.com/help-center/
cost-of-onpage-api-parameters, 24/07/2026) — at n=3 pages that's ~$0.00045 per
brief, never the actual blocker. The real complexity is that content_parsing
needs a completed on_page crawl task first (task_post -> poll on_page/summary
for crawl_progress="finished" -> content_parsing), not a single synchronous
call. This polls with a bounded budget and degrades honestly — a page whose
crawl doesn't finish in time is dropped from the result, never returned with
fabricated content (L6: a stated partial result is not silence).

Two things verified via a live smoke test (24/07/2026, real DataForSEO
account) that the docs alone don't make obvious:
1. content_parsing's `url` must be the page DataForSEO actually crawled, NOT
   the originally requested target — a target that redirects (very common:
   www.example.com/some-slug -> www.example.com/) returns items_count=0 if
   you pass the original target url. The real crawled url has to be read
   back from on_page/pages before calling content_parsing.
2. The real article body lives in page_content.main_topic[].primary_content[]
   .text (one block per section, each with its own main_title) — NOT
   page_content.header.primary_content, which is nav/chrome text.
"""
from __future__ import annotations

import asyncio

import httpx
import structlog

logger = structlog.get_logger()

BASE = "https://api.dataforseo.com/v3"

LOCATION_CODES = {  # source-market -> DFS location_code
    "US": 2840, "USA": 2840, "UK": 2826, "GB": 2826, "AU": 2036, "DE": 2276,
    "FR": 2250, "NL": 2528, "CA": 2124, "SG": 2702, "VN": 2704,
}

# A 1-page on_page crawl finishes in well under this in practice (~20-25s
# observed live); a page not done by the deadline is dropped, not blocked on
# forever (L6).
_POLL_BUDGET_S = 45.0
_POLL_INTERVAL_S = 5.0


async def _top_ranking_urls(
    client: httpx.AsyncClient, login: str, password: str, keyword: str, market: str, n: int,
) -> list[str]:
    loc = LOCATION_CODES.get(market.upper())
    if not loc:
        return []
    try:
        r = await client.post(
            f"{BASE}/serp/google/organic/live/advanced",
            auth=(login, password),
            json=[{"keyword": keyword, "location_code": loc, "language_code": "en", "depth": 10}],
            timeout=30,
        )
        r.raise_for_status()
        items = r.json()["tasks"][0]["result"][0]["items"] or []
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as e:
        logger.warning("parse_top_pages_serp_read_failed", keyword=keyword, error=str(e))
        return []
    urls = [it["url"] for it in items if it.get("type") == "organic" and it.get("url")]
    return urls[:n]


def _extract_body_text(page_content: dict) -> str:
    """Real article body, not nav/chrome — see module docstring finding #2."""
    parts = []
    for section in page_content.get("main_topic") or []:
        title = section.get("main_title") or ""
        body = " ".join(
            b.get("text", "") for b in (section.get("primary_content") or [])
            if isinstance(b, dict) and b.get("text")
        )
        if title and body:
            parts.append(f"{title}: {body}")
        elif body:
            parts.append(body)
    return "\n".join(parts)


async def _crawl_and_parse_one(
    client: httpx.AsyncClient, login: str, password: str, url: str, deadline: float,
) -> dict | None:
    try:
        r = await client.post(
            f"{BASE}/on_page/task_post",
            auth=(login, password),
            json=[{"target": url, "max_crawl_pages": 1, "enable_content_parsing": True}],
            timeout=30,
        )
        r.raise_for_status()
        task_id = r.json()["tasks"][0]["id"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as e:
        logger.warning("parse_top_pages_task_post_failed", url=url, error=str(e))
        return None

    while True:
        try:
            r = await client.get(f"{BASE}/on_page/summary/{task_id}", auth=(login, password), timeout=30)
            r.raise_for_status()
            finished = r.json()["tasks"][0]["result"][0].get("crawl_progress") == "finished"
        except (httpx.HTTPError, KeyError, IndexError, TypeError):
            finished = False
        if finished:
            break
        if asyncio.get_event_loop().time() >= deadline:
            logger.warning("parse_top_pages_crawl_timed_out", url=url, budget_s=_POLL_BUDGET_S)
            return None
        await asyncio.sleep(_POLL_INTERVAL_S)

    # Finding #1: content_parsing needs the ACTUALLY-crawled url (post-redirect),
    # not the target we submitted — read it back from on_page/pages first.
    try:
        r = await client.post(f"{BASE}/on_page/pages", auth=(login, password), json=[{"id": task_id}], timeout=30)
        r.raise_for_status()
        page_items = r.json()["tasks"][0]["result"][0]["items"] or []
        crawled_url = page_items[0]["url"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as e:
        logger.warning("parse_top_pages_pages_lookup_failed", url=url, error=str(e))
        return None

    try:
        r = await client.post(
            f"{BASE}/on_page/content_parsing",
            auth=(login, password),
            json=[{"id": task_id, "url": crawled_url}],
            timeout=30,
        )
        r.raise_for_status()
        items = r.json()["tasks"][0]["result"][0]["items"] or []
        page_content = items[0]["page_content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as e:
        logger.warning("parse_top_pages_content_parsing_failed", url=url, error=str(e))
        return None

    content = _extract_body_text(page_content)
    return {"url": url, "crawled_url": crawled_url, "content": content}


async def parse_top_pages(login: str, password: str, keyword: str, market: str, n: int = 3) -> list[dict]:
    """Real content of the top-N organic-ranking pages for `keyword`, for the
    brief gap call. Returns [{"url", "crawled_url", "content"}] — only for
    pages whose crawl finished within the poll budget. Offline/no-credentials,
    no ranking pages found, or a page that never finishes crawling all
    degrade to fewer (or zero) entries — never to a fabricated content: ""
    placeholder that a caller could mistake for "checked, nothing there"."""
    if not (login and password):
        return []
    async with httpx.AsyncClient() as client:
        urls = await _top_ranking_urls(client, login, password, keyword, market, n)
        if not urls:
            return []
        deadline = asyncio.get_event_loop().time() + _POLL_BUDGET_S
        results = await asyncio.gather(
            *[_crawl_and_parse_one(client, login, password, url, deadline) for url in urls]
        )
    return [r for r in results if r]
