"""
DataForSEO keyword volume tool.

Cache check: acp_silver_s2.visibility_reports (TTL 7d via fetched_at).
Cap: ACP_MAX_KEYWORDS_PER_RUN (default 200).
S3 path: acp-cis-bronze-867490540162/acp/s2/{run_id}/keywords.json
Cannibalization: checks acp_gold_output.published_content for overlapping keywords.
"""
import json
import os
import structlog
from datetime import datetime, timezone

import httpx

logger = structlog.get_logger()

_MAX_KEYWORDS = int(os.environ.get("ACP_MAX_KEYWORDS_PER_RUN", "200"))
_S3_BUCKET = os.environ.get("ACP_BRONZE_BUCKET", "aa-cis-bronze-867490540162")
_DATAFORSEO_URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
_INFORMATIONAL_WORDS = frozenset({"how", "what", "guide", "tips", "best", "top", "vs", "why", "when"})


def make_dataforseo_node(pool, s3_client, api_keys: dict):
    login = api_keys.get("DATAFORSEO_LOGIN", "")
    password = api_keys.get("DATAFORSEO_PASSWORD", "")

    async def dataforseo(state: dict) -> dict:
        run_id = state["run_id"]
        country = state["country"]
        tenant_id = state["tenant_id"]

        # Cache check (7d)
        async with pool.acquire() as conn:
            cached = await conn.fetchrow("""
                SELECT keywords_s3_key, keyword_count
                FROM acp_silver_s2.visibility_reports
                WHERE tenant_id = $1 AND country = $2
                  AND keywords_s3_key IS NOT NULL
                  AND fetched_at > NOW() - INTERVAL '7 days'
                ORDER BY fetched_at DESC
                LIMIT 1
            """, tenant_id, country)

        if cached:
            logger.info("dataforseo_cache_hit", run_id=run_id, country=country)
            completed = list(state.get("completed_tools", []))
            completed.append("dataforseo")
            return {
                "keywords_s3_key": cached["keywords_s3_key"],
                "keyword_count": cached["keyword_count"] or 0,
                "dataforseo_cache_hit": True,
                "completed_tools": completed,
            }

        # Fetch from DataForSEO
        seed = f"{country} tours"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    _DATAFORSEO_URL,
                    auth=(login, password),
                    json=[{"keywords": [seed], "language_code": "en", "location_code": 2840}],
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.error("dataforseo_api_error", run_id=run_id, error=str(exc))
            completed = list(state.get("completed_tools", []))
            completed.append("dataforseo")
            return {
                "error": f"dataforseo_failed: {exc}",
                "keyword_count": 0,
                "dataforseo_cache_hit": False,
                "completed_tools": completed,
            }

        # Extract and cap results
        raw_items = []
        for task in (data.get("tasks") or []):
            for item in (task.get("result") or []):
                for kw_item in (item.get("items") or []):
                    raw_items.append(kw_item)
        results = raw_items[:_MAX_KEYWORDS]
        kw_count = len(results)

        # Informational intent heuristic
        info_count = sum(
            1 for r in results
            if _INFORMATIONAL_WORDS & set((r.get("keyword") or "").lower().split())
        )
        informational_intent_pct = round((info_count / kw_count * 100) if kw_count else 0.0, 2)

        # Cannibalization check
        existing_content_risk = False
        keyword_set = {(r.get("keyword") or "").lower() for r in results}
        try:
            async with pool.acquire() as conn:
                pub_rows = await conn.fetch("""
                    SELECT primary_keyword
                    FROM acp_gold_output.published_content
                    WHERE tenant_id = $1
                      AND published_at > NOW() - INTERVAL '6 months'
                      AND quality_score >= 7.0
                """, tenant_id)
            for row in pub_rows:
                if (row["primary_keyword"] or "").lower() in keyword_set:
                    existing_content_risk = True
                    break
        except Exception as exc:
            logger.warning("cannibalization_check_skipped", run_id=run_id, error=str(exc))

        if existing_content_risk:
            results = [
                {**r, "search_volume": int((r.get("search_volume") or 0) * 0.2)}
                for r in results
            ]
            logger.info("cannibalization_risk_detected", run_id=run_id, tenant_id=tenant_id)

        # Store to S3
        s3_key = f"acp/s2/{run_id}/keywords.json"
        payload = {
            "run_id": run_id,
            "country": country,
            "keyword_count": kw_count,
            "informational_intent_pct": informational_intent_pct,
            "existing_content_risk": existing_content_risk,
            "keywords": results,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        s3_client.put_object(
            Bucket=_S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(payload),
            ContentType="application/json",
        )

        completed = list(state.get("completed_tools", []))
        completed.append("dataforseo")
        logger.info("dataforseo_complete", run_id=run_id, keyword_count=kw_count,
                    informational_intent_pct=informational_intent_pct,
                    existing_content_risk=existing_content_risk)
        return {
            "keywords_s3_key": s3_key,
            "keyword_count": kw_count,
            "informational_intent_pct": informational_intent_pct,
            "existing_content_risk": existing_content_risk,
            "dataforseo_cache_hit": False,
            "completed_tools": completed,
        }

    return dataforseo
