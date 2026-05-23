"""
Apify website content crawler for competitor analysis.

Source URLs: acp_silver_s2.competitor_inputs (tenant_id + country, is_active=TRUE).
TTL cache: 3d. Stores run metadata to S3: .../competitors.json.
STUB if no competitor URLs found — returns competitors_s3_key=None.
"""
import json
import os
import structlog
from datetime import datetime, timezone

import httpx

logger = structlog.get_logger()

_S3_BUCKET = os.environ.get("ACP_BRONZE_BUCKET", "aa-cis-bronze-867490540162")
_APIFY_RUN_URL = "https://api.apify.com/v2/acts/apify~website-content-crawler/runs"


def make_apify_node(pool, s3_client, api_keys: dict):
    apify_token = api_keys.get("APIFY_API_TOKEN", "")

    async def apify(state: dict) -> dict:
        run_id = state["run_id"]
        country = state["country"]
        tenant_id = state["tenant_id"]

        async with pool.acquire() as conn:
            # Cache check (3d)
            cached = await conn.fetchrow("""
                SELECT competitors_s3_key
                FROM acp_silver_s2.visibility_reports
                WHERE tenant_id = $1 AND country = $2
                  AND competitors_s3_key IS NOT NULL
                  AND fetched_at > NOW() - INTERVAL '3 days'
                ORDER BY fetched_at DESC
                LIMIT 1
            """, tenant_id, country)

            if cached:
                logger.info("apify_cache_hit", run_id=run_id)
                completed = list(state.get("completed_tools", []))
                completed.append("apify")
                return {"competitors_s3_key": cached["competitors_s3_key"], "completed_tools": completed}

            urls = await conn.fetch("""
                SELECT url, label
                FROM acp_silver_s2.competitor_inputs
                WHERE tenant_id = $1 AND country = $2 AND is_active = TRUE
            """, tenant_id, country)

        if not urls:
            logger.info("apify_no_competitors", run_id=run_id, tenant_id=tenant_id)
            completed = list(state.get("completed_tools", []))
            completed.append("apify")
            return {"competitors_s3_key": None, "completed_tools": completed}

        start_urls = [{"url": row["url"]} for row in urls]
        apify_run_id = None
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    _APIFY_RUN_URL,
                    headers={"Authorization": f"Bearer {apify_token}"},
                    json={"startUrls": start_urls, "maxPagesPerCrawl": 5},
                )
                resp.raise_for_status()
                apify_run_id = resp.json().get("data", {}).get("id")
        except Exception as exc:
            logger.error("apify_api_error", run_id=run_id, error=str(exc))
            completed = list(state.get("completed_tools", []))
            completed.append("apify")
            return {"competitors_s3_key": None, "error": f"apify_failed: {exc}", "completed_tools": completed}

        s3_key = f"acp/s2/{run_id}/competitors.json"
        payload = {
            "run_id": run_id,
            "country": country,
            "apify_run_id": apify_run_id,
            "competitor_urls": [row["url"] for row in urls],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        s3_client.put_object(
            Bucket=_S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(payload),
            ContentType="application/json",
        )

        completed = list(state.get("completed_tools", []))
        completed.append("apify")
        logger.info("apify_complete", run_id=run_id, competitor_count=len(urls))
        return {"competitors_s3_key": s3_key, "completed_tools": completed}

    return apify
