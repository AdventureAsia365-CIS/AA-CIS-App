"""
GET /v1/acp/s1-keywords — keywords used in S1 for a country (S2 dedup input).
"""
import json as _json
import os
import structlog

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from typing import Optional

from api.routers.auth import verify_jwt as _verify_jwt

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/acp", tags=["acp"])


def _get_tenant(
    request: Request,
    credentials: Optional[_Creds] = Depends(_HTTPBearer(auto_error=False)),
):
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    x_admin = request.headers.get("X-Admin-Secret", "")
    if admin_secret and x_admin == admin_secret:
        return {"sub": "00000000-0000-0000-0000-000000000001", "role": "admin"}
    if credentials:
        try:
            return _verify_jwt(credentials.credentials)
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


@router.get("/s1-keywords")
async def get_s1_keywords(
    country: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """
    Return deduplicated keywords used in S1 for the given country.
    S2 calls this to avoid keyword cannibalization across runs.
    """
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT sc.top_keywords, sc.keyword_search
            FROM silver_aa_internal.seo_context sc
            JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = sc.tour_id
            WHERE LOWER(rt.country) = LOWER($1)
              AND sc.top_keywords IS NOT NULL
            ORDER BY sc.fetched_at DESC
            LIMIT 20
        """, country)

    keywords: list = []
    seen: set = set()
    for row in rows:
        kw_data = row["top_keywords"]
        if isinstance(kw_data, str):
            try:
                kw_data = _json.loads(kw_data)
            except Exception:
                continue
        if isinstance(kw_data, list):
            items = kw_data
        elif isinstance(kw_data, dict):
            items = kw_data.get("top_keywords") or []
        else:
            items = []
        for item in items:
            kw = item.get("keyword") if isinstance(item, dict) else str(item)
            if kw and kw not in seen:
                seen.add(kw)
                keywords.append({
                    "keyword":       kw,
                    "search_volume": item.get("search_volume") if isinstance(item, dict) else None,
                })

    logger.info("s1_keywords_fetched", country=country, keyword_count=len(keywords))
    return {
        "country":       country,
        "keyword_count": len(keywords),
        "keywords":      keywords,
    }
