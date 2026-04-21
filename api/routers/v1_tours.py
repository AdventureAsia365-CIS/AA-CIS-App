from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from api.routers.auth import verify_jwt

router = APIRouter(prefix="/v1/tours", tags=["B2B Tours"])
security = HTTPBearer()

def get_tenant(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        return verify_jwt(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def get_pool(request: Request):
    return request.app.state.pool

@router.get("")
async def list_tours(
    request: Request,
    tenant=Depends(get_tenant),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    min_quality: Optional[float] = Query(None, ge=0, le=1),
):
    tenant_id = tenant["sub"]
    pool = request.app.state.pool
    offset = (page - 1) * page_size

    conditions = ["tenant_id = $1"]
    params = [tenant_id]

    if min_quality is not None:
        params.append(min_quality)
        conditions.append(f"quality_score >= ${len(params)}")

    where = "WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM gold_aa_internal.published_tours {where}",
            *params
        )
        params_paged = params + [page_size, offset]
        rows = await conn.fetch(f"""
            SELECT id, tour_id, aa_name, aa_subtitle, aa_summary,
                   seo_title, quality_score, published_at
            FROM gold_aa_internal.published_tours
            {where}
            ORDER BY published_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
        """, *params_paged)

    return {
        "data": [dict(r) for r in rows],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": -(-total // page_size)
        },
        "tenant_id": tenant_id
    }

@router.get("/{tour_id}")
async def get_tour(
    tour_id: str,
    request: Request,
    tenant=Depends(get_tenant),
):
    tenant_id = tenant["sub"]
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM gold_aa_internal.published_tours
            WHERE id = $1 AND tenant_id = $2
        """, tour_id, tenant_id)

    if not row:
        raise HTTPException(status_code=404, detail="Tour not found")

    return dict(row)
