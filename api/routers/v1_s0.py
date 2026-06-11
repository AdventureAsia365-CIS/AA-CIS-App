"""
/v1/s0 — S0 Data Quality Review endpoints (admin-facing).

GET  /v1/s0/review?country=&status=&provider=&date_from=&date_to=
     → list raw_tours pending/under review; field_coverage_pct per row

PATCH /v1/s0/tours/{tour_id}
     → edit src_name, country, price_raw, provider; auto-sets review_status='reviewed'

POST  /v1/s0/approve
     → bulk approve {tour_ids: [...]}

POST  /v1/s0/reject
     → bulk reject {tour_ids: [...], notes: str} — notes required
"""
import os
import structlog
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from pydantic import BaseModel
from typing import Optional

from api.routers.auth import verify_jwt as _verify_jwt

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/s0", tags=["s0"])

_COVERAGE_FIELDS = (
    "src_name", "country", "src_subtitle",
    "src_summary", "src_highlights", "src_itineraries", "price_raw",
)


def _field_coverage_pct(row: dict) -> int:
    """Return int 0-100: fraction of 7 tracked fields that are non-null/non-empty."""
    filled = sum(
        1 for f in _COVERAGE_FIELDS
        if row.get(f) is not None and str(row.get(f, "")) != ""
    )
    return round(filled * 100 / len(_COVERAGE_FIELDS))


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


# ── Models ────────────────────────────────────────────────────────────────────

class TourEditRequest(BaseModel):
    src_name:  Optional[str] = None
    country:   Optional[str] = None
    price_raw: Optional[str] = None
    provider:  Optional[str] = None


class BulkApproveRequest(BaseModel):
    tour_ids: list[str]


class BulkRejectRequest(BaseModel):
    tour_ids: list[str]
    notes:    str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/review")
async def list_review(
    request: Request,
    tenant=Depends(_get_tenant),
    country:   Optional[str]  = None,
    status:    Optional[str]  = None,
    provider:  Optional[str]  = None,
    date_from: Optional[date] = None,
    date_to:   Optional[date] = None,
):
    """
    Return raw_tours for S0 review.
    Default: review_status IN ('pending_review','reviewed').
    With ?status=X: only that status (supports 'approved' for audit view).
    """
    pool = request.app.state.pool

    # Build WHERE clauses
    conditions = []
    params: list = []
    idx = 1

    if status:
        conditions.append(f"review_status = ${idx}")
        params.append(status)
        idx += 1
    else:
        conditions.append("review_status IN ('pending_review','reviewed')")

    if country:
        conditions.append(f"LOWER(country) = LOWER(${idx})")
        params.append(country)
        idx += 1

    if provider:
        conditions.append(f"LOWER(provider) LIKE LOWER(${idx})")
        params.append(f"%{provider}%")
        idx += 1

    if date_from:
        conditions.append(f"ingest_at >= ${idx}")
        params.append(date_from)
        idx += 1

    if date_to:
        conditions.append(f"ingest_at < ${idx} + INTERVAL '1 day'")
        params.append(date_to)
        idx += 1

    where = " AND ".join(conditions) if conditions else "TRUE"

    tenant_id = tenant.get("sub", "")
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT tour_id, src_name, country, provider,
                   src_subtitle, src_summary, src_highlights,
                   src_itineraries, price_raw,
                   ingest_at, review_status, review_notes
            FROM silver_aa_internal.raw_tours
            WHERE {where}
            ORDER BY ingest_at DESC
            LIMIT 500
        """, *params)

        # Brand brief reuse: include last uploaded key so frontend can auto-fill (M1)
        tenant_row = await conn.fetchrow(
            "SELECT last_brand_brief_s3_key FROM shared.tenants WHERE tenant_id=$1::uuid",
            tenant_id,
        )
        last_brief_key = tenant_row["last_brand_brief_s3_key"] if tenant_row else None

    return {
        "data": [
            {
                "id":                str(r["tour_id"]),
                "src_name":          r["src_name"],
                "country":           r["country"],
                "provider":          r["provider"],
                "ingest_at":        r["ingest_at"].isoformat() if r["ingest_at"] else None,
                "review_status":     r["review_status"],
                "review_notes":      r["review_notes"],
                "field_coverage_pct": _field_coverage_pct(dict(r)),
            }
            for r in rows
        ],
        "total": len(rows),
        "brand_brief": {
            "last_s3_key":           last_brief_key,
            "has_previous_brief":    last_brief_key is not None,
        },
    }


@router.patch("/tours/{tour_id}")
async def edit_tour(
    tour_id: str,
    body: TourEditRequest,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Edit editable S0 fields. Automatically sets review_status='reviewed'."""
    if all(v is None for v in (body.src_name, body.country, body.price_raw, body.provider)):
        raise HTTPException(400, "Provide at least one field to update")

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE silver_aa_internal.raw_tours
            SET
                src_name      = COALESCE($1, src_name),
                country       = COALESCE($2, country),
                price_raw     = COALESCE($3, price_raw),
                provider      = COALESCE($4, provider),
                review_status = 'reviewed',
                reviewed_at   = NOW()
            WHERE tour_id = $5::uuid
            RETURNING tour_id, src_name, country, price_raw, provider,
                      review_status, reviewed_at
        """, body.src_name, body.country, body.price_raw, body.provider, tour_id)

    if not row:
        raise HTTPException(404, "Tour not found")

    logger.info("s0_tour_edited", tour_id=tour_id)
    return {
        "id":            str(row["tour_id"]),
        "src_name":      row["src_name"],
        "country":       row["country"],
        "price_raw":     row["price_raw"],
        "provider":      row["provider"],
        "review_status": row["review_status"],
        "reviewed_at":   row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
    }


@router.post("/approve")
async def bulk_approve(
    body: BulkApproveRequest,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Bulk set review_status='approved'. Returns count approved."""
    if not body.tour_ids:
        raise HTTPException(400, "tour_ids must not be empty")

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET review_status = 'approved',
                reviewed_at   = NOW()
            WHERE tour_id = ANY($1::uuid[])
        """, body.tour_ids)

    count = int(result.split()[-1])
    logger.info("s0_bulk_approved", count=count)
    return {"approved": count, "message": f"{count} tours approved — ready for S1 rewrite"}


@router.post("/reject")
async def bulk_reject(
    body: BulkRejectRequest,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Bulk set review_status='rejected'. notes is required."""
    if not body.notes or not body.notes.strip():
        raise HTTPException(400, "notes is required for rejection")
    if not body.tour_ids:
        raise HTTPException(400, "tour_ids must not be empty")

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET review_status = 'rejected',
                review_notes  = $1,
                reviewed_at   = NOW()
            WHERE tour_id = ANY($2::uuid[])
        """, body.notes.strip(), body.tour_ids)

    count = int(result.split()[-1])
    logger.info("s0_bulk_rejected", count=count)
    return {"rejected": count}
