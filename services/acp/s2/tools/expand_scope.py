"""
Scope expander. Conditional: runs only if keyword_count < 20 after dataforseo.
Calls DataForSEO with broader travel seed terms. Updates keyword_count and
keywords_s3_key to point to the expanded file.

Circuit breaker (AA-113): if expand_attempts >= 1 when called (i.e. this node
already fired once but keyword_count is still < threshold), return immediately
with gate1_override='manual_required' to force HITL regardless of score.

On first expand attempt: if keyword_count is still < threshold after the API
call, set gate1_override='manual_required' for the same reason.
"""
import json
import os
import structlog
from datetime import datetime, timezone

import httpx

logger = structlog.get_logger()

_S3_BUCKET = os.environ.get("ACP_BRONZE_BUCKET", "aa-cis-bronze-867490540162")
_DATAFORSEO_URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
_EXPAND_THRESHOLD = 20


def make_expand_scope_node(s3_client, api_keys: dict):
    login = api_keys.get("DATAFORSEO_LOGIN", "")
    password = api_keys.get("DATAFORSEO_PASSWORD", "")

    async def expand_scope(state: dict) -> dict:
        run_id = state["run_id"]
        country = state["country"]
        kw_count = state.get("keyword_count", 0)
        expand_attempts = state.get("expand_attempts", 0)
        completed = list(state.get("completed_tools", []))

        if kw_count >= _EXPAND_THRESHOLD:
            completed.append("expand_scope")
            return {"completed_tools": completed}

        # Circuit breaker: already expanded once, still below threshold — force manual review
        if expand_attempts >= 1:
            logger.warning("expand_scope_circuit_breaker_fired",
                           run_id=run_id, expand_attempts=expand_attempts, keyword_count=kw_count)
            completed.append("expand_scope")
            return {
                "completed_tools": completed,
                "data_quality": "low",
                "gate1_override": "manual_required",
            }

        seeds = [
            f"{country} travel",
            f"visit {country}",
            f"{country} tourism",
            f"{country} itinerary",
        ]
        extra = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    _DATAFORSEO_URL,
                    auth=(login, password),
                    json=[{"keywords": seeds, "language_code": "en", "location_code": 2840}],
                )
                resp.raise_for_status()
                data = resp.json()

            for task in (data.get("tasks") or []):
                for item in (task.get("result") or []):
                    for kw_item in (item.get("items") or []):
                        extra.append(kw_item)
        except Exception as exc:
            logger.warning("expand_scope_api_error", run_id=run_id, error=str(exc))

        new_count = kw_count + len(extra)
        s3_key = f"acp/s2/{run_id}/keywords_expanded.json"
        s3_client.put_object(
            Bucket=_S3_BUCKET,
            Key=s3_key,
            Body=json.dumps({
                "run_id": run_id,
                "country": country,
                "extra_keywords": extra,
                "original_count": kw_count,
                "expanded_count": new_count,
                "expanded_at": datetime.now(timezone.utc).isoformat(),
            }),
            ContentType="application/json",
        )

        completed.append("expand_scope")
        result: dict = {
            "keyword_count": new_count,
            "keywords_s3_key": s3_key,
            "expand_attempts": expand_attempts + 1,
            "iteration": state.get("iteration", 0) + 1,
            "completed_tools": completed,
        }

        if new_count < _EXPAND_THRESHOLD:
            logger.warning("expand_scope_exhausted",
                           run_id=run_id, original=kw_count, expanded=new_count)
            result["gate1_override"] = "manual_required"
            result["data_quality"] = "low"
        else:
            logger.info("expand_scope_complete",
                        run_id=run_id, original=kw_count, expanded=new_count)

        return result

    return expand_scope
