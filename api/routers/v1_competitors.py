"""
/v1/competitors — Competitor URL management per tenant.
GET    /v1/competitors?country= — list tenant's URLs
POST   /v1/competitors          — add URL (max 10 active per country)
PATCH  /v1/competitors/{id}     — update label / is_active (ownership verified)
DELETE /v1/competitors/{id}     — soft delete: is_active=false (ownership verified)
"""
import os
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from pydantic import BaseModel
from typing import Optional

from api.routers.auth import verify_jwt as _verify_jwt

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/competitors", tags=["competitors"])

MAX_PER_COUNTRY = 10


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


class AddCompetitorRequest(BaseModel):
    country: str
    url: str
    label: Optional[str] = None


class UpdateCompetitorRequest(BaseModel):
    label: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("")
async def list_competitors(
    request: Request,
    tenant=Depends(_get_tenant),
    country: Optional[str] = None,
):
    """Return all competitor URLs for the tenant, optionally filtered by country."""
    pool = request.app.state.pool
    tenant_id = tenant.get("sub")
    async with pool.acquire() as conn:
        if country:
            rows = await conn.fetch("""
                SELECT id, country, url, label, is_active, created_at
                FROM acp_silver_s2.competitor_inputs
                WHERE tenant_id = $1::uuid AND LOWER(country) = LOWER($2)
                ORDER BY created_at DESC
            """, tenant_id, country)
        else:
            rows = await conn.fetch("""
                SELECT id, country, url, label, is_active, created_at
                FROM acp_silver_s2.competitor_inputs
                WHERE tenant_id = $1::uuid
                ORDER BY country, created_at DESC
            """, tenant_id)

    # Count active per country for the limit indicator
    by_country: dict[str, int] = {}
    for r in rows:
        if r["is_active"]:
            by_country[r["country"]] = by_country.get(r["country"], 0) + 1

    return {
        "data": [
            {
                "id":         str(r["id"]),
                "country":    r["country"],
                "url":        r["url"],
                "label":      r["label"],
                "is_active":  r["is_active"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
        "active_count_by_country": by_country,
        "max_per_country": MAX_PER_COUNTRY,
    }


@router.post("", status_code=201)
async def add_competitor(
    body: AddCompetitorRequest,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Add a competitor URL. Rejects if active count for that country already at 10."""
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "url must start with http:// or https://")

    pool = request.app.state.pool
    tenant_id = tenant.get("sub")

    async with pool.acquire() as conn:
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM acp_silver_s2.competitor_inputs
            WHERE tenant_id = $1::uuid
              AND LOWER(country) = LOWER($2)
              AND is_active = true
        """, tenant_id, body.country)

        if count >= MAX_PER_COUNTRY:
            raise HTTPException(
                422,
                f"Maximum {MAX_PER_COUNTRY} active competitor URLs per country reached",
            )

        try:
            row = await conn.fetchrow("""
                INSERT INTO acp_silver_s2.competitor_inputs
                    (tenant_id, country, url, label)
                VALUES ($1::uuid, $2, $3, $4)
                RETURNING id, country, url, label, is_active, created_at
            """, tenant_id, body.country, body.url, body.label)
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(409, "URL already tracked for this tenant")
            raise

    logger.info("competitor_added", tenant_id=tenant_id,
                country=body.country, url=body.url)
    return {
        "id":         str(row["id"]),
        "country":    row["country"],
        "url":        row["url"],
        "label":      row["label"],
        "is_active":  row["is_active"],
        "created_at": row["created_at"].isoformat(),
    }


@router.patch("/{competitor_id}")
async def update_competitor(
    competitor_id: str,
    body: UpdateCompetitorRequest,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Update label or is_active. Verifies ownership before any write."""
    if body.label is None and body.is_active is None:
        raise HTTPException(400, "Provide at least one of: label, is_active")

    pool = request.app.state.pool
    tenant_id = tenant.get("sub")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE acp_silver_s2.competitor_inputs
            SET
                label      = COALESCE($1, label),
                is_active  = COALESCE($2, is_active),
                updated_at = NOW()
            WHERE id = $3::uuid AND tenant_id = $4::uuid
            RETURNING id, country, url, label, is_active, updated_at
        """, body.label, body.is_active, competitor_id, tenant_id)

    if not row:
        raise HTTPException(404, "Competitor not found")

    return {
        "id":         str(row["id"]),
        "country":    row["country"],
        "url":        row["url"],
        "label":      row["label"],
        "is_active":  row["is_active"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.delete("/{competitor_id}", status_code=204)
async def delete_competitor(
    competitor_id: str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Soft delete: sets is_active=false. Verifies ownership."""
    pool = request.app.state.pool
    tenant_id = tenant.get("sub")

    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE acp_silver_s2.competitor_inputs
            SET is_active = false, updated_at = NOW()
            WHERE id = $1::uuid AND tenant_id = $2::uuid
        """, competitor_id, tenant_id)

    if result == "UPDATE 0":
        raise HTTPException(404, "Competitor not found")
