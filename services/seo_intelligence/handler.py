import asyncio
import asyncpg
import json
import os
import structlog
from datetime import datetime, timedelta
from .dataforseo_client import (
    DataForSEOClient,
    DEFAULT_LOCATION_CODE, DEFAULT_LOCATION_NAME, DEFAULT_LANGUAGE_CODE,
)
from .seed_builder import resolve_buyer_market
from shared.secrets import get_database_url
from shared.services.tenant_config_service import TenantConfigService
from shared.repository.seo_context_repository import SeoContextRepository
from shared.cache.redis_cache import RedisCache
from shared.cache.local_cache import LocalCache

logger = structlog.get_logger()


async def process_seo(
    tour_id: str,
    destination: str,
    activity: str = None,
    cache=None,
    seo_mode: str = "dataforseo",
    seed: str = "",
    tenant_id: str = None,
) -> dict:
    # "disabled" — skip SEO step entirely
    if seo_mode == "disabled":
        logger.info("seo_disabled", tour_id=tour_id)
        return {"status": "disabled", "data": {}}

    # AA-197: caller passes a pre-built seed; fall back to destination for old callers.
    effective_seed = seed or destination

    # AA-197: resolve buyer market from tenant target_market (UNWIRED before).
    location_code, location_name, language_code = (
        DEFAULT_LOCATION_CODE, DEFAULT_LOCATION_NAME, DEFAULT_LANGUAGE_CODE,
    )
    if tenant_id:
        try:
            mkt_conn = await asyncpg.connect(get_database_url())
            try:
                cfg = await TenantConfigService(mkt_conn).get_seo_config(tenant_id)
                location_code, location_name, language_code = resolve_buyer_market(cfg.target_market)
            finally:
                await mkt_conn.close()
        except Exception as _mkt_err:
            logger.warning("seo_market_resolve_failed", tenant_id=tenant_id, error=str(_mkt_err))

    cache = cache or LocalCache()
    # Cache per (seed, buyer market) — same tour for a different market is a distinct entry.
    cache_key = RedisCache.make_key(effective_seed, str(location_code))

    cached = await cache.get(cache_key)
    if cached:
        logger.info("cache_hit", destination=effective_seed, seo_mode=seo_mode)
        return {"status": "cache_hit", "data": cached}

    # "custom_keywords" — use existing seo_context from DB, skip DataForSEO API call
    if seo_mode == "custom_keywords":
        logger.info("seo_custom_keywords", tour_id=tour_id, destination=destination)
        conn = await asyncpg.connect(get_database_url())
        try:
            row = await conn.fetchrow(
                """SELECT top_keywords, keyword_ideas
                   FROM silver_aa_internal.seo_context
                   WHERE tour_id = $1::uuid
                   ORDER BY fetched_at DESC LIMIT 1""",
                tour_id,
            )
            if row:
                existing = {
                    "keywords": {
                        "top_keywords": json.loads(row["top_keywords"] or "[]"),
                        "search_volumes": json.loads(row["keyword_ideas"] or "{}"),
                    }
                }
                await cache.set(cache_key, existing, ttl_seconds=86400)
                return {"status": "custom_keywords", "data": existing}
        finally:
            await conn.close()
        # No existing data — return empty rather than calling DataForSEO
        return {"status": "custom_keywords_empty", "data": {}}

    # "dataforseo" (default) — live keyword fetch
    logger.info("cache_miss", destination=effective_seed, seo_mode=seo_mode, location=location_name)
    client = DataForSEOClient()
    seo_data = await client.fetch_all(
        effective_seed, location_code, location_name, language_code, activity,
    )

    conn = await asyncpg.connect(get_database_url())
    try:
        repo = SeoContextRepository(conn, tenant_slug="aa_internal")
        seo_id = await repo.insert({
            "tour_id":        tour_id,
            "keyword_search": effective_seed,
            # AA-203: persist the AA-197 top-level keyword_ideas list (full-metric:
            # volume/competition/cpc) — NOT keywords.search_volumes (an often-empty dict).
            "keyword_ideas":  json.dumps(seo_data.get("keyword_ideas", []), default=str),
            "demographics":   json.dumps(seo_data.get("demographics", {})),
            "trends":         json.dumps(seo_data.get("trends", {})),
            "top_keywords":   json.dumps(seo_data.get("keywords", {}).get("top_keywords", [])),
            # AA-218: DFS fetch_all returns these top-level lists — persist them
            # (real keys are people_also_ask / related_keywords, not "related").
            "people_also_ask":  json.dumps(seo_data.get("people_also_ask", []), default=str),
            "related_keywords": json.dumps(seo_data.get("related_keywords", []), default=str),
            "cache_key":      cache_key,
            "expires_at":     datetime.utcnow() + timedelta(hours=24),
        })
        logger.info("seo_inserted", id=seo_id)
    finally:
        await conn.close()

    await cache.set(cache_key, seo_data, ttl_seconds=86400)
    return {"status": "fetched", "id": seo_id, "data": seo_data}


async def _lookup_destination(tour_id: str) -> str:
    """Lookup country/name from DB when destination not in SF payload."""
    conn = await asyncpg.connect(get_database_url())
    try:
        row = await conn.fetchrow(
            "SELECT country, src_name FROM silver_aa_internal.raw_tours "
            "WHERE tour_id = $1::uuid",
            tour_id
        )
        if row:
            return row["country"] or row["src_name"] or ""
        return ""
    finally:
        await conn.close()


def lambda_handler(event: dict, context) -> dict:
    results = []

    # Pattern 1: SF direct invoke
    if "destination" in event:
        records = [event]
    # Pattern 2: SQS trigger (Phase 2)
    elif "Records" in event:
        records = [json.loads(r["body"]) for r in event["Records"]]
    elif "tour_id" in event:
        # SF invoke without destination — lookup from DB
        records = [event]
    else:
        logger.warning("unknown_event_format", keys=list(event.keys()))
        return {"processed": 0, "results": []}

    for body in records:
        try:
            tour_id     = body.get("tour_id", "unknown")
            destination = body.get("destination")
            activity    = body.get("activity")
            seo_mode    = body.get("seo_mode", "dataforseo")

            # Lookup destination from DB if not provided
            if not destination and tour_id != "unknown":
                try:
                    destination = asyncio.run(_lookup_destination(tour_id))
                except Exception as _e:
                    logger.warning("destination_lookup_failed", error=str(_e))

            if not destination and seo_mode != "disabled":
                logger.warning("missing_destination", tour_id=tour_id)
                continue

            result = asyncio.run(process_seo(tour_id, destination or "", activity, seo_mode=seo_mode))
            results.append({"destination": destination, **result})
        except Exception as e:
            logger.error("seo_failed", error=str(e))
            results.append({"status": "failed", "error": str(e)})

    return {"processed": len(results), "results": results}
