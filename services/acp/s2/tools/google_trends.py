"""
Google Trends via pytrends (free). Always runs. TTL 14d.
S3 path: .../trends.json
pytrends is sync — wrapped in run_in_executor to avoid blocking the event loop.
"""
import asyncio
import json
import os
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

_S3_BUCKET = os.environ.get("ACP_BRONZE_BUCKET", "acp-cis-bronze-867490540162")


def make_google_trends_node(pool, s3_client):

    async def google_trends(state: dict) -> dict:
        run_id = state["run_id"]
        country = state["country"]
        tenant_id = state["tenant_id"]

        # Cache check (14d)
        async with pool.acquire() as conn:
            cached = await conn.fetchrow("""
                SELECT trends_s3_key
                FROM acp_silver_s2.visibility_reports
                WHERE tenant_id = $1 AND country = $2
                  AND trends_s3_key IS NOT NULL
                  AND fetched_at > NOW() - INTERVAL '14 days'
                ORDER BY fetched_at DESC
                LIMIT 1
            """, tenant_id, country)

        if cached:
            logger.info("google_trends_cache_hit", run_id=run_id)
            completed = list(state.get("completed_tools", []))
            completed.append("google_trends")
            return {"trends_s3_key": cached["trends_s3_key"], "completed_tools": completed}

        kw = f"{country} tours"
        trend_data = []
        try:
            from pytrends.request import TrendReq

            def _fetch_trends():
                pt = TrendReq(hl="en-US", tz=360)
                pt.build_payload([kw], cat=0, timeframe="today 12-m")
                df = pt.interest_over_time()
                if df.empty:
                    return []
                return df.reset_index().to_dict(orient="records")

            loop = asyncio.get_event_loop()
            trend_data = await loop.run_in_executor(None, _fetch_trends)
        except Exception as exc:
            logger.warning("google_trends_error", run_id=run_id, error=str(exc))

        s3_key = f"acp/s2/{run_id}/trends.json"
        s3_client.put_object(
            Bucket=_S3_BUCKET,
            Key=s3_key,
            Body=json.dumps({
                "run_id": run_id,
                "country": country,
                "trends": trend_data,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }, default=str),
            ContentType="application/json",
        )

        completed = list(state.get("completed_tools", []))
        completed.append("google_trends")
        logger.info("google_trends_complete", run_id=run_id, data_points=len(trend_data))
        return {"trends_s3_key": s3_key, "completed_tools": completed}

    return google_trends
