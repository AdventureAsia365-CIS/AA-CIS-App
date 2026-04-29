import asyncio
import asyncpg
import json
import os
import structlog
from datetime import datetime, timedelta
from .dataforseo_client import DataForSEOClient
from shared.secrets import get_database_url
from shared.repository.seo_context_repository import SeoContextRepository
from shared.cache.redis_cache import RedisCache
from shared.cache.local_cache import LocalCache

logger = structlog.get_logger()

async def process_seo(tour_id: str, destination: str, activity: str = None, cache=None) -> dict:
    cache = cache or LocalCache()
    cache_key = RedisCache.make_key(destination, activity)

    cached = await cache.get(cache_key)
    if cached:
        logger.info("cache_hit", destination=destination)
        return {"status": "cache_hit", "data": cached}

    logger.info("cache_miss", destination=destination)
    client = DataForSEOClient()
    seo_data = await client.fetch_all(destination, activity)

    conn = await asyncpg.connect(get_database_url())
    try:
        repo = SeoContextRepository(conn, tenant_slug="aa_internal")
        seo_id = await repo.insert({
            "tour_id":       tour_id,
            "keyword_search": destination,
            "keyword_ideas":  json.dumps(seo_data.get("keywords", [])),
            "demographics":   json.dumps(seo_data.get("demographics", {})),
            "trends":         json.dumps(seo_data.get("trends", {})),
            "top_keywords":   json.dumps(seo_data.get("top_keywords", [])),
            "cache_key":      cache_key,
            "expires_at":     datetime.utcnow() + timedelta(hours=24),
        })
        logger.info("seo_inserted", id=seo_id)
    finally:
        await conn.close()

    await cache.set(cache_key, seo_data, ttl_seconds=86400)
    return {"status": "fetched", "id": seo_id, "data": seo_data}


def lambda_handler(event: dict, context) -> dict:
    results = []

    # Pattern 1: SF direct invoke
    if "destination" in event:
        records = [event]
    # Pattern 2: SQS trigger (Phase 2)
    elif "Records" in event:
        records = [json.loads(r["body"]) for r in event["Records"]]
    else:
        logger.warning("unknown_event_format", keys=list(event.keys()))
        return {"processed": 0, "results": []}

    for body in records:
        try:
            tour_id     = body.get("tour_id", "unknown")
            destination = body.get("destination")
            activity    = body.get("activity")
            if not destination:
                logger.warning("missing_destination", body=body)
                continue
            result = asyncio.run(process_seo(tour_id, destination, activity))
            results.append({"destination": destination, **result})
        except Exception as e:
            logger.error("seo_failed", error=str(e))
            results.append({"status": "failed", "error": str(e)})

    return {"processed": len(results), "results": results}
