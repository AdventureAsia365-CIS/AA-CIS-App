import asyncio
import asyncpg
import boto3
import json
import os
import structlog

from .dataforseo_client import DataForSEOClient
from shared.repository.seo_context_repository import SeoContextRepository
from shared.cache.redis_cache import RedisCache
from shared.cache.local_cache import LocalCache

logger = structlog.get_logger()

async def process_seo(destination: str, activity: str = None, cache=None) -> dict:
    cache = cache or LocalCache()
    cache_key = RedisCache.make_key(destination, activity)

    # 1. Cache check
    cached = await cache.get(cache_key)
    if cached:
        logger.info("cache_hit", destination=destination)
        return {"status": "cache_hit", "data": cached}

    logger.info("cache_miss", destination=destination)

    # 2. DataForSEO fetch
    client = DataForSEOClient()
    seo_data = await client.fetch_all(destination, activity)

    # 3. Upsert DB
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        repo = SeoContextRepository(conn)
        seo_id = await repo.upsert({
            "destination":  destination,
            "activity":     activity,
            "keywords":     json.dumps(seo_data.get("keywords", {})),
            "demographics": json.dumps({}),
        })
        logger.info("seo_upserted", id=seo_id)
    finally:
        await conn.close()

    # 4. Update cache
    await cache.set(cache_key, seo_data, ttl_seconds=86400)

    return {"status": "fetched", "id": seo_id, "data": seo_data}

def lambda_handler(event: dict, context) -> dict:
    results = []
    for record in event.get("Records", []):
        try:
            body        = json.loads(record["body"])
            destination = body.get("destination")
            activity    = body.get("activity")

            if not destination:
                logger.warning("missing_destination", body=body)
                continue

            result = asyncio.run(process_seo(destination, activity))
            results.append({"destination": destination, **result})

        except Exception as e:
            logger.error("seo_failed", error=str(e))
            results.append({"status": "failed", "error": str(e)})

    return {"processed": len(results), "results": results}
