from shared.secrets import get_dataforseo_creds
import httpx
import structlog

logger = structlog.get_logger()

DATAFORSEO_BASE = "https://api.dataforseo.com/v3"

# AA-197: defaults kept only as fallbacks; callers pass buyer-market resolved values.
DEFAULT_LOCATION_CODE = 2840          # United States
DEFAULT_LOCATION_NAME = "United States"
DEFAULT_LANGUAGE_CODE = "en"


class DataForSEOClient:
    def __init__(self, login: str = None, password: str = None):
        if not login or not password:
            login, password = get_dataforseo_creds()
        self.login    = login
        self.password = password

    def _auth(self) -> tuple[str, str]:
        return (self.login, self.password)

    async def fetch_keywords(
        self,
        seed: str,
        location_code: int = DEFAULT_LOCATION_CODE,
        location_name: str = DEFAULT_LOCATION_NAME,
        language_code: str = DEFAULT_LANGUAGE_CODE,
    ) -> dict:
        # AA-197: seed is pre-built by seed_builder — DO NOT append "tours" here.
        payload = [{
            "language_code": language_code,
            "location_code": location_code,
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
        logger.info("dfs_keywords_fetched", seed=seed, location=location_name)
        return self._parse_keywords(data)

    async def _serp_advanced(
        self,
        seed: str,
        location_code: int = DEFAULT_LOCATION_CODE,
        language_code: str = DEFAULT_LANGUAGE_CODE,
    ) -> dict:
        # One SERP call serves both People-Also-Ask and related searches (cost-neutral).
        payload = [{
            "language_code": language_code,
            "location_code": location_code,
            "keyword":       seed,
        }]
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{DATAFORSEO_BASE}/serp/google/organic/live/advanced",
                auth=self._auth(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def fetch_people_also_ask(
        self,
        seed: str,
        location_code: int = DEFAULT_LOCATION_CODE,
        language_code: str = DEFAULT_LANGUAGE_CODE,
    ) -> list[str]:
        data = await self._serp_advanced(seed, location_code, language_code)
        return self._parse_paa(data)

    async def fetch_related(
        self,
        seed: str,
        location_code: int = DEFAULT_LOCATION_CODE,
        language_code: str = DEFAULT_LANGUAGE_CODE,
    ) -> list[str]:
        data = await self._serp_advanced(seed, location_code, language_code)
        return self._parse_related(data)

    async def fetch_keyword_ideas(
        self,
        seed: str,
        location_code: int = DEFAULT_LOCATION_CODE,
        language_code: str = DEFAULT_LANGUAGE_CODE,
    ) -> list[dict]:
        # Real keyword ideas (~100s of rows) with volume/competition/cpc. Self-contained: [] on error.
        payload = [{
            "keywords":      [seed],
            "location_code": location_code,
            "language_code": language_code,
            "limit":         25,
        }]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{DATAFORSEO_BASE}/keywords_data/google_ads/keywords_for_keywords/live",
                    auth=self._auth(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning("dfs_ideas_failed", error=str(e))
            return []
        return self._parse_keyword_ideas(data)

    async def fetch_all(
        self,
        seed: str,
        location_code: int = DEFAULT_LOCATION_CODE,
        location_name: str = DEFAULT_LOCATION_NAME,
        language_code: str = DEFAULT_LANGUAGE_CODE,
        activity: str = None,
    ) -> dict:
        try:
            keywords = await self.fetch_keywords(seed, location_code, location_name, language_code)
        except Exception as e:
            logger.warning("dfs_keywords_failed", error=str(e))
            keywords = {}

        paa: list[str] = []
        related: list[str] = []
        try:
            # Single SERP call → parse PAA + related (no second HTTP request).
            serp = await self._serp_advanced(seed, location_code, language_code)
            paa = self._parse_paa(serp)
            related = self._parse_related(serp)
        except Exception as e:
            logger.warning("dfs_serp_failed", error=str(e))

        # AA-197: real keyword ideas (full dicts w/ volume/competition/cpc) — never raises.
        keyword_ideas = await self.fetch_keyword_ideas(seed, location_code, language_code)

        keywords = keywords if isinstance(keywords, dict) else {}
        top_keywords = keywords.get("top_keywords", [])
        # AA-197 #4: promote ideas to primary keywords when search_volume returns none,
        # so prompts.py always has a keyword to lead with.
        if not top_keywords and keyword_ideas:
            top_keywords = [i["keyword"] for i in keyword_ideas[:10]]
            keywords = {**keywords, "top_keywords": top_keywords}

        return {
            "keywords":         keywords,
            "people_also_ask":  paa,
            "related_keywords": related,
            "keyword_ideas":    keyword_ideas,
            "destination":      seed,
            "activity":         activity,
        }

    def _parse_keywords(self, data: dict) -> dict:
        try:
            results = data["tasks"][0]["result"] or []
            # DataForSEO search_volume returns list of keyword objects directly
            items = [r for r in results if isinstance(r, dict) and "keyword" in r]
            if not items:
                return {}
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
        return [q for q in questions if q][:10]

    def _parse_keyword_ideas(self, data: dict) -> list[dict]:
        # keywords_for_keywords: tasks[0].result[] flat list of idea objects. Dedupe casefold, ≤25.
        try:
            results = data["tasks"][0]["result"] or []
        except (KeyError, IndexError, TypeError):
            return []
        out: list[dict] = []
        seen: set[str] = set()
        for el in results:
            if not isinstance(el, dict):
                continue
            kw = el.get("keyword")
            if not kw:
                continue
            key = kw.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "keyword":           kw,
                "search_volume":     el.get("search_volume"),
                "competition":       el.get("competition"),
                "competition_index": el.get("competition_index"),
                "cpc":               el.get("cpc"),
            })
            if len(out) >= 25:
                break
        return out

    def _parse_related(self, data: dict) -> list[str]:
        related = []
        try:
            items = data["tasks"][0]["result"][0]["items"]
            for item in items:
                if item.get("type") == "related_searches":
                    for r in item.get("items", []):
                        # related_searches items are plain strings or {title}/{keyword} dicts
                        if isinstance(r, str):
                            related.append(r)
                        elif isinstance(r, dict):
                            related.append(r.get("title") or r.get("keyword") or "")
        except (KeyError, IndexError, TypeError):
            pass
        return [r for r in related if r][:10]
