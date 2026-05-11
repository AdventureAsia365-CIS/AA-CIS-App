from shared.secrets import get_dataforseo_creds
import httpx
import os
import json
import structlog
from typing import Any

logger = structlog.get_logger()

DATAFORSEO_BASE = "https://api.dataforseo.com/v3"

class DataForSEOClient:
    def __init__(self, login: str = None, password: str = None):
        if not login or not password:
            login, password = get_dataforseo_creds()
        self.login    = login
        self.password = password

    def _auth(self) -> tuple[str, str]:
        return (self.login, self.password)

    async def fetch_keywords(self, destination: str, activity: str = None) -> dict:
        seed = f"{destination} {activity}".strip() if activity else f"{destination} tours"
        payload = [{
            "language_name": "English",
            "location_name": "United States",
            "keywords":      [seed],
        }]
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{DATAFORSEO_BASE}/keywords_data/google_ads/search_volume/live",
                auth=self._auth(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        logger.info("dfs_keywords_fetched", destination=destination)
        return self._parse_keywords(data)

    async def fetch_people_also_ask(self, destination: str, activity: str = None) -> list[str]:
        query = f"{destination} {activity} tour".strip() if activity else f"{destination} tour"
        payload = [{
            "language_code": "en",
            "location_code": 2840,
            "keyword":       query,
        }]
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{DATAFORSEO_BASE}/serp/google/organic/live/advanced",
                auth=self._auth(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return self._parse_paa(data)

    async def fetch_all(self, destination: str, activity: str = None) -> dict:
        try:
            keywords = await self.fetch_keywords(destination, activity)
        except Exception as e:
            logger.warning("dfs_keywords_failed", error=str(e))
            keywords = {}
        try:
            paa = await self.fetch_people_also_ask(destination, activity)
        except Exception as e:
            logger.warning("dfs_paa_failed", error=str(e))
            paa = []
        return {
            "keywords":        keywords,
            "people_also_ask": paa,
            "destination":     destination,
            "activity":        activity,
        }

    def _parse_keywords(self, data: dict) -> dict:
        try:
            items = data["tasks"][0]["result"][0]["items"]
            return {
                "top_keywords":   [i["keyword"] for i in items[:10]],
                "search_volumes": {i["keyword"]: i.get("search_volume", 0) for i in items[:10]},
            }
        except (KeyError, IndexError, TypeError):
            return {}

    def _parse_paa(self, data: dict) -> list[str]:
        questions = []
        try:
            items = data["tasks"][0]["result"][0]["items"]
            for item in items:
                if item.get("type") == "people_also_ask":
                    for q in item.get("items", []):
                        questions.append(q.get("title", ""))
        except (KeyError, IndexError, TypeError):
            pass
        return questions[:10]
