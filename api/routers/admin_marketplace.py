"""
api/routers/admin_marketplace.py — AA-330 Phần A curation-for-tenant catalog backend.

Auth: x-admin-secret header only, same convention as admin.py/admin_atoms.py
(verify_admin_secret reused, not redefined).

Scope (AA-330 Phần A, per Linear STEP 0 comment 07/08/2026 + task instructions):
  - Catalog browse/filter over acp_contract.v_trip_registry, joined to a real
    per-tour atom count/richness aggregate (same tour_atoms filter admin_atoms.py
    uses: NOT deleted AND NOT is_empty_marker).
  - Save a DRAFT portfolio (acp_shared.marketplace_portfolios, migration 097).
    atom_snapshot.total_atoms is a real re-computed SELECT — runway_months and
    posts_per_week are NULL (Phần B: no runway_months() formula exists yet,
    STEP 0 grep confirmed zero hits for runway_months/estimate_runway/months_of).

Explicitly NOT in this file (Phần B, deferred):
  - No price filter — price_raw is free text with no parser yet (unlike
    duration_raw/period, which runway.py already parses from a live 749-row
    survey; price_raw has had no equivalent survey).
  - No finalize-portfolio endpoint (draft -> finalized transition).
  - No runway_months() computation — field is always null here.

GET  /admin/marketplace/catalog     — list/filter tours with real atom counts
POST /admin/marketplace/portfolios  — save a draft portfolio (INSERT only)
"""
import json
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from api.routers.admin import verify_admin_secret
from services.acp_planning.runway import parse_duration_days, parse_period

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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_admin_secret: str = Header(None),
):
    """List/filter the AA-internal catalog for tenant browse (D4 Mode A —
    platform-scoped catalog, no tenant_id involved at this step, see STEP 0).

    destination + min_atoms are applied in SQL. duration_min/duration_max/
    period_month are applied in Python via runway.py's parse_duration_days/
    parse_period — reused as-is (AA-330 STEP 0 instruction: don't re-derive a
    parser that's already survey-built from live duration_raw/period data).
    Dataset is catalog-sized (~793 rows max, aa_internal), so fetching the SQL-
    filtered set and narrowing further in Python needs no pagination-breaking
    two-pass query."""
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

    total = len(tours)
    page = tours[offset:offset + limit]

    return {"tours": page, "count": len(page), "total": total, "limit": limit, "offset": offset}


# ── POST /admin/marketplace/portfolios ──────────────────────────────────────

class SavePortfolioRequest(BaseModel):
    tour_ids: list[str]
    filters_used: dict = {}


@router.post("/portfolios")
async def save_portfolio(
    body: SavePortfolioRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    """Save a DRAFT portfolio only — no finalize/status-transition endpoint
    exists yet (Phần B). atom_snapshot.total_atoms is a real re-computed
    COUNT against acp_contract.tour_atoms for exactly the submitted tour_ids
    (same NOT deleted AND NOT is_empty_marker filter as everywhere else in
    this file) — never taken from the catalog list response, so a stale
    client-side count can't be persisted. runway_months/posts_per_week are
    always null (no formula exists yet — do not fabricate)."""
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

        atom_snapshot = {"total_atoms": total_atoms, "runway_months": None, "posts_per_week": None}
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
