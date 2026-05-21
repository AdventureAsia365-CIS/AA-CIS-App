"""
Featured image sourcing chain: Unsplash → Pexels → none.
PRD v1.0 §4 S4: featured image for each blog draft.
Secrets: aa-cis/dev/unsplash-api-key, aa-cis/dev/pexels-api-key.
Fails gracefully — missing credentials → skip that source, try next.
"""
import json
import logging
from typing import Optional, Tuple

import boto3
import aiohttp

logger = logging.getLogger(__name__)

_SM_REGION = "us-west-1"
_TIMEOUT = aiohttp.ClientTimeout(total=10)


def _get_api_key(secret_id: str, field: str) -> str:
    try:
        client = boto3.client("secretsmanager", region_name=_SM_REGION)
        return json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"]).get(field, "")
    except Exception:
        return ""


async def _unsplash(query: str) -> Optional[Tuple[str, str]]:
    key = _get_api_key("aa-cis/dev/unsplash-api-key", "access_key")
    if not key:
        return None
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": 1, "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {key}"},
            ) as resp:
                if resp.status != 200:
                    return None
                results = (await resp.json()).get("results", [])
                if not results:
                    return None
                p = results[0]
                return p["urls"]["regular"], f"Photo by {p['user']['name']} on Unsplash"
    except Exception as exc:
        logger.warning("unsplash_failed: %s", exc)
        return None


async def _pexels(query: str) -> Optional[Tuple[str, str]]:
    key = _get_api_key("aa-cis/dev/pexels-api-key", "api_key")
    if not key:
        return None
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 1, "orientation": "landscape"},
                headers={"Authorization": key},
            ) as resp:
                if resp.status != 200:
                    return None
                photos = (await resp.json()).get("photos", [])
                if not photos:
                    return None
                p = photos[0]
                return p["src"]["large"], f"Photo by {p['photographer']} on Pexels"
    except Exception as exc:
        logger.warning("pexels_failed: %s", exc)
        return None


async def source_featured_image(
    country: str,
    primary_keyword: str,
) -> Tuple[Optional[str], Optional[str], str]:
    """
    Returns (image_url, credit, source_type).
    source_type: 'unsplash' | 'pexels' | 'none'
    Priority: Unsplash → Pexels → none.
    """
    query = f"{country} travel {primary_keyword}"

    result = await _unsplash(query)
    if result:
        return result[0], result[1], "unsplash"

    result = await _pexels(query)
    if result:
        return result[0], result[1], "pexels"

    logger.info("image_not_found query=%s", query)
    return None, None, "none"
