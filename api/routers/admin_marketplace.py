"""
api/routers/admin_marketplace.py — AA-330 curation-for-tenant catalog backend.

Auth: x-admin-secret header only, same convention as admin.py/admin_atoms.py
(verify_admin_secret reused, not redefined).

Phần A (07/08/2026): catalog browse/filter over acp_contract.v_trip_registry,
joined to a real per-tour atom count/richness aggregate (same tour_atoms
filter admin_atoms.py uses: NOT deleted AND NOT is_empty_marker), and saving
a DRAFT portfolio (acp_shared.marketplace_portfolios, migration 097).

Phần B (08/08/2026, this pass): wires services.acp_shared.marketplace_estimates'
runway_months()/parse_price() into the two Phần A endpoints (real
atom_snapshot.runway_months on save, real price_usd/price_available +
min_price/max_price filter on the catalog list — see that module's own
docstring for the commercial-decision reasoning behind both), plus a new
finalize endpoint. See docs/implementation-notes/AA-330.md for the STEP 0
survey + the 4 commercial decisions (Nghiep) this implements verbatim.

GET   /admin/marketplace/catalog                     — list/filter tours (atoms + price)
POST  /admin/marketplace/portfolios                   — save a draft portfolio
PATCH /admin/marketplace/portfolios/{portfolio_id}/finalize — draft -> finalized
"""
import json
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from api.routers.admin import verify_admin_secret
from services.acp_planning.runway import parse_duration_days, parse_period
from services.acp_shared.marketplace_estimates import parse_price, runway_months

router = APIRouter(prefix="/admin/marketplace", tags=["admin-marketplace"])


_JSON_FIELDS = ("filters_used", "atom_snapshot")


def _safe(row) -> dict:
    """Same local UUID/Decimal/datetime -> JSON-safe pattern as admin_atoms.py's
    _safe() — no shared api/utils.safe() exists in this repo (checked there).

    Two extras admin_atoms.py's version doesn't need: (1) tour_ids is a
    Postgres UUID[] — asyncpg hands back a list[UUID], not a single UUID, so
    the scalar isinstance check is extended to lists; (2) filters_used/
    atom_snapshot are JSONB with no codec registered on this app's
    connections (same asyncpg gap admin_atoms.py's _safe() already found for
    tour_atoms.media) — parsed here the same way."""
    if not row:
        return {}
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, UUID):
            d[k] = str(v)
        elif isinstance(v, list):
            d[k] = [str(item) if isinstance(item, UUID) else item for item in v]
        elif isinstance(v, Decimal):
            d[k] = float(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    for k in _JSON_FIELDS:
        if k in d and isinstance(d[k], str):
            d[k] = json.loads(d[k]) if d[k] else None
    return d


# ── GET /admin/marketplace/catalog ──────────────────────────────────────────

_CATALOG_QUERY = """
    SELECT
        vtr.id                              AS tour_id,
        COALESCE(vtr.aa_name, vtr.name)     AS name,
        vtr.destination                     AS destination,
        vtr.duration_raw                    AS duration_raw,
        vtr.period                          AS period,
        vtr.price_raw                       AS price_raw,
        vtr.trip_url                        AS trip_url,
        vtr.url_alive                       AS url_alive,
        COALESCE(ac.atom_count, 0)          AS total_atoms,
        COALESCE(ac.high_count, 0)          AS high_atoms_count,
        COALESCE(ac.has_image, false)       AS has_image
    FROM acp_contract.v_trip_registry vtr
    LEFT JOIN (
        SELECT tour_id,
               count(*) AS atom_count,
               count(*) FILTER (WHERE distinctiveness = 'HIGH') AS high_count,
               bool_or((media->>'has_photo')::boolean) AS has_image
        FROM acp_contract.tour_atoms
        WHERE NOT deleted AND NOT is_empty_marker
        GROUP BY tour_id
    ) ac ON ac.tour_id = vtr.id
"""


@router.get("/catalog")
async def list_catalog(
    request: Request,
    destination: Optional[str] = Query(None),
    duration_min: Optional[int] = Query(None, ge=0),
    duration_max: Optional[int] = Query(None, ge=0),
    period_month: Optional[int] = Query(None, ge=1, le=12),
    min_atoms: Optional[int] = Query(None, ge=0),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_admin_secret: str = Header(None),
):
    """List/filter the AA-internal catalog for tenant browse (D4 Mode A —
    platform-scoped catalog, no tenant_id involved at this step, see STEP 0).

    destination + min_atoms are applied in SQL. duration_min/duration_max/
    period_month/min_price/max_price are applied in Python — duration/period
    via runway.py's parse_duration_days/parse_period (reused as-is), price via
    services.acp_shared.marketplace_estimates.parse_price(). Dataset is
    catalog-sized (~793 rows max, aa_internal), so fetching the SQL-filtered
    set and narrowing further in Python needs no pagination-breaking two-pass
    query.

    AA-330 Phần B commercial-decision D2 (Nghiep, confirmed before build): a
    tour whose price_raw doesn't parse reliably is NEVER dropped from
    results — it always appears, with `price_available=false` (frontend
    shows "Giá: liên hệ"), regardless of whether a price filter is active.
    min_price/max_price only narrow the price_available=true subset."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    clauses = []
    params: list = []

    def _add(clause: str, value) -> None:
        params.append(value)
        clauses.append(clause.format(n=len(params)))

    if destination:
        _add("vtr.destination ILIKE ${n}", f"%{destination}%")
    if min_atoms is not None:
        _add("COALESCE(ac.atom_count, 0) >= ${n}", min_atoms)

    query = _CATALOG_QUERY
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY vtr.destination, name"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    tours = [_safe(r) for r in rows]

    for t in tours:
        price_usd = parse_price(t.pop("price_raw"))
        t["price_usd"] = price_usd
        t["price_available"] = price_usd is not None

    if duration_min is not None or duration_max is not None:
        def _duration_ok(t: dict) -> bool:
            days = parse_duration_days(t["duration_raw"])
            if days is None:
                return False
            if duration_min is not None and days < duration_min:
                return False
            if duration_max is not None and days > duration_max:
                return False
            return True
        tours = [t for t in tours if _duration_ok(t)]

    if period_month is not None:
        tours = [t for t in tours if period_month in parse_period(t["period"])]

    if min_price is not None or max_price is not None:
        def _price_ok(t: dict) -> bool:
            if not t["price_available"]:
                return True  # D2 — never dropped, filter is a no-op for these
            if min_price is not None and t["price_usd"] < min_price:
                return False
            if max_price is not None and t["price_usd"] > max_price:
                return False
            return True
        tours = [t for t in tours if _price_ok(t)]

    total = len(tours)
    page = tours[offset:offset + limit]

    return {"tours": page, "count": len(page), "total": total, "limit": limit, "offset": offset}


# ── POST /admin/marketplace/portfolios ──────────────────────────────────────

class SavePortfolioRequest(BaseModel):
    tour_ids: list[str]
    filters_used: dict = {}
    posts_per_week: Optional[float] = None


@router.post("/portfolios")
async def save_portfolio(
    body: SavePortfolioRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    """Save a DRAFT portfolio. atom_snapshot.total_atoms is a real
    re-computed COUNT against acp_contract.tour_atoms for exactly the
    submitted tour_ids (same NOT deleted AND NOT is_empty_marker filter as
    everywhere else in this file) — never taken from the catalog list
    response, so a stale client-side count can't be persisted.

    runway_months is computed from that real total_atoms via
    services.acp_shared.marketplace_estimates.runway_months() — see that
    module's docstring for why it is a deliberate commercial simulation, not
    a technical measurement. `posts_per_week` is null (and so is
    runway_months, by runway_months()'s own contract) when the caller
    doesn't supply a cadence — never guessed."""
    verify_admin_secret(x_admin_secret)

    if not body.tour_ids:
        raise HTTPException(status_code=400, detail="tour_ids must not be empty")

    try:
        tour_uuids = [UUID(t) for t in body.tour_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="tour_ids must be valid UUIDs")

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        total_atoms = await conn.fetchval(
            """
            SELECT count(*) FROM acp_contract.tour_atoms
            WHERE tour_id = ANY($1) AND NOT deleted AND NOT is_empty_marker
            """,
            tour_uuids,
        )

        months = runway_months(total_atoms, body.posts_per_week) if body.posts_per_week else None
        atom_snapshot = {
            "total_atoms": total_atoms,
            "runway_months": months,
            "posts_per_week": body.posts_per_week,
        }
        row = await conn.fetchrow(
            """
            INSERT INTO acp_shared.marketplace_portfolios
                (tour_ids, filters_used, atom_snapshot, status)
            VALUES ($1, $2::jsonb, $3::jsonb, 'draft')
            RETURNING portfolio_id, tour_ids, filters_used, atom_snapshot, status, created_at, finalized_at
            """,
            tour_uuids, json.dumps(body.filters_used), json.dumps(atom_snapshot),
        )

    return _safe(row)


# ── PATCH /admin/marketplace/portfolios/{portfolio_id}/finalize ────────────

@router.patch("/portfolios/{portfolio_id}/finalize")
async def finalize_portfolio(
    portfolio_id: str,
    request: Request,
    x_admin_secret: str = Header(None),
):
    """draft -> finalized. Refuses (409) an already-finalized portfolio
    rather than silently re-stamping finalized_at — a second finalize call
    is almost certainly a client retry/bug, not an intentional re-finalize,
    and overwriting the original finalized_at would corrupt the audit
    trail of when the commercial commitment was actually made."""
    verify_admin_secret(x_admin_secret)

    try:
        portfolio_uuid = UUID(portfolio_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid portfolio_id: {portfolio_id!r}")

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        current = await conn.fetchrow(
            "SELECT status FROM acp_shared.marketplace_portfolios WHERE portfolio_id = $1",
            portfolio_uuid,
        )
        if current is None:
            raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
        if current["status"] == "finalized":
            raise HTTPException(status_code=409, detail=f"Portfolio {portfolio_id} is already finalized")

        row = await conn.fetchrow(
            """
            UPDATE acp_shared.marketplace_portfolios
            SET status = 'finalized', finalized_at = now()
            WHERE portfolio_id = $1
            RETURNING portfolio_id, tour_ids, filters_used, atom_snapshot, status, created_at, finalized_at
            """,
            portfolio_uuid,
        )

    return _safe(row)
