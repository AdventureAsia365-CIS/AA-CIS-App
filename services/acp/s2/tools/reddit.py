"""
Reddit data collection via public JSON API.
Conditional: only runs if informational_intent_pct < 30.
TTL 7d. S3 path: .../reddit.json
No auth required for public subreddit search.
"""
import json
import os
import structlog
from datetime import datetime, timezone

import httpx

logger = structlog.get_logger()

_S3_BUCKET = os.environ.get("ACP_BRONZE_BUCKET", "aa-cis-bronze-867490540162")
_REDDIT_SEARCH_URL = "https://www.reddit.com/search.json"
_INFORMATIONAL_THRESHOLD = 30.0


def make_reddit_node(pool, s3_client):

    async def reddit(state: dict) -> dict:
        run_id = state["run_id"]
        country = state["country"]
        tenant_id = state["tenant_id"]
        intent_pct = state.get("informational_intent_pct")

        # Skip if informational intent is high enough
        if intent_pct is None or intent_pct >= _INFORMATIONAL_THRESHOLD:
            completed = list(state.get("completed_tools", []))
            completed.append("reddit")
            return {"reddit_s3_key": None, "completed_tools": completed}

        # Cache check (7d)
        async with pool.acquire() as conn:
            cached = await conn.fetchrow("""
                SELECT reddit_s3_key
                FROM acp_silver_s2.visibility_reports
                WHERE tenant_id = $1 AND country = $2
                  AND reddit_s3_key IS NOT NULL
                  AND fetched_at > NOW() - INTERVAL '7 days'
                ORDER BY fetched_at DESC
                LIMIT 1
            """, tenant_id, country)

        if cached:
            logger.info("reddit_cache_hit", run_id=run_id)
            completed = list(state.get("completed_tools", []))
            completed.append("reddit")
            return {"reddit_s3_key": cached["reddit_s3_key"], "completed_tools": completed}

        posts = []
        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                headers={"User-Agent": "AA-CIS-Research/1.0 (research bot)"},
            ) as client:
                resp = await client.get(
                    _REDDIT_SEARCH_URL,
                    params={"q": f"{country} travel", "sort": "relevance", "limit": 25, "type": "link"},
                )
                resp.raise_for_status()
                data = resp.json()

            posts = [
                {
                    "title": child["data"].get("title", ""),
                    "url": child["data"].get("url", ""),
                    "score": child["data"].get("score", 0),
                    "num_comments": child["data"].get("num_comments", 0),
                    "subreddit": child["data"].get("subreddit", ""),
                }
                for child in (data.get("data", {}).get("children") or [])
                if child.get("kind") == "t3"
            ]
        except Exception as exc:
            logger.warning("reddit_api_error", run_id=run_id, error=str(exc))

        s3_key = f"acp/s2/{run_id}/reddit.json"
        s3_client.put_object(
            Bucket=_S3_BUCKET,
            Key=s3_key,
            Body=json.dumps({
                "run_id": run_id,
                "country": country,
                "posts": posts,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }),
            ContentType="application/json",
        )

        completed = list(state.get("completed_tools", []))
        completed.append("reddit")
        logger.info("reddit_complete", run_id=run_id, post_count=len(posts))
        return {"reddit_s3_key": s3_key, "completed_tools": completed}

    return reddit
