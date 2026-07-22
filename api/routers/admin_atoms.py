"""
api/routers/admin_atoms.py — AA-300 curation UI backend.

Auth: x-admin-secret header only (no tenant JWT) — same convention as
admin.py/admin_pipeline.py (STEP 0/PHẦN A decision, AA-300). Reuses
verify_admin_secret from admin.py rather than redefining it. Reached only
through the existing frontend/app/api/admin/[...path]/route.ts BFF proxy —
no new proxy route needed (it already forwards any /api/admin/* path to
/admin/* on this backend).

Does NOT touch api/routers/v1_atoms.py (decompose) at all — this is a
separate, purely additive resource: list/filter + star/delete/edit on
already-decomposed atoms, plus a read-only preview wrapper around the real
N4/N5/N6 pipeline (services/acp_planning/) for the first visual look at the
whole ACP v2 pipeline end to end.

GET   /admin/atoms                    — list/filter, batch of 50 by default
PATCH /admin/atoms/{atom_id}          — star / soft-delete / light text edit
GET   /admin/atoms/preview-slotgrid   — runway_map -> plan_quarter ->
                                         approve_quarter_plan -> allocate_month
                                         for one tenant, returns the SlotGrid
"""
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from api.routers.admin import verify_admin_secret
from services.acp_planning.allocator import allocate_month
from services.acp_planning.quarter import approve_quarter_plan, plan_quarter
from services.acp_planning.runway import runway_map
from services.acp_shared.atom_constants import THIN_TRIP_ATOM_MIN

router = APIRouter(prefix="/admin", tags=["admin-atoms"])

# AA_internal — the only tenant with real tour/atom data today (verified live,
# AA-301 STEP 0: 793/793 raw_tours rows). Used as the default for the preview
# endpoint's tenant_id query param so the demo works out of the box.
_AA_INTERNAL_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _safe(row) -> dict:
    """Same pattern as v1_tours.py's local safe() helper — UUID/Decimal/
    datetime -> JSON-safe. No shared api/utils.safe() exists in this repo
    (checked); every router defines its own local copy."""
    if not row:
        return {}
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, UUID):
            d[k] = str(v)
        elif isinstance(v, Decimal):
            d[k] = float(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


# ── GET /admin/atoms — list/filter, batch of 50 ─────────────────────────────

_LIST_FROM = """
    FROM acp_contract.tour_atoms ta
    JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = ta.tour_id
    JOIN (
        SELECT tour_id, count(*) AS atom_count
        FROM acp_contract.tour_atoms
        WHERE NOT deleted AND NOT is_empty_marker
        GROUP BY tour_id
    ) tc ON tc.tour_id = ta.tour_id
    WHERE NOT ta.is_empty_marker
"""

_LIST_SELECT_COLS = """
    SELECT ta.atom_id, ta.tour_id, rt.src_name AS tour_name, ta.text,
           ta.activity_type, ta.emotional_hook, ta.visual_potential,
           ta.distinctiveness, ta.media, ta.starred, ta.deleted,
           ta.created_at, ta.updated_at,
           (ta.updated_at = ta.created_at) AS unreviewed,
           tc.atom_count AS tour_atom_count
"""


@router.get("/atoms")
async def list_atoms(
    request: Request,
    tour_id: Optional[str] = Query(None),
    distinctiveness: Optional[str] = Query(None, pattern="^(HIGH|MED|LOW)$"),
    unreviewed_only: bool = Query(False),
    thin_only: bool = Query(False),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_admin_secret: str = Header(None),
):
    """List/filter atoms for curation. Defaults to a 50-atom batch (issue
    AA-300: "50 atom trên 1 màn hình", not one atom at a time). Returns a
    `total` matching-filter count (a second COUNT(*) query, same WHERE
    clause) alongside the page — needed so the frontend can reuse the
    existing Pagination.tsx component as-is, which requires a total item
    count to compute page numbers (not something the original single-query
    design produced; added specifically for that reuse — self-chosen, see
    AA-300 implementation notes).

    "unreviewed" is derived from updated_at == created_at rather than a new
    column — tour_atoms has no reviewed/reviewed_at field, and both
    timestamps are set to the same now() at insert time (v1_atoms.py's
    INSERT, migration 079/084/085), so they stay exactly equal until the
    first PATCH touches the row. Self-chosen — see AA-300 implementation
    notes. "thin" reuses the tour_atom_count already computed in the JOIN
    (< THIN_TRIP_ATOM_MIN, the same constant N5's B5 fix imports)."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    clauses = []
    params: list = []

    def _add(clause: str, value) -> None:
        params.append(value)
        clauses.append(clause.format(n=len(params)))

    if tour_id:
        _add("ta.tour_id = ${n}::uuid", tour_id)
    if distinctiveness:
        _add("ta.distinctiveness = ${n}", distinctiveness)
    if not include_deleted:
        clauses.append("NOT ta.deleted")
    if unreviewed_only:
        clauses.append("ta.updated_at = ta.created_at")
    if thin_only:
        _add("tc.atom_count < ${n}", THIN_TRIP_ATOM_MIN)

    where_sql = _LIST_FROM
    if clauses:
        where_sql += " AND " + " AND ".join(clauses)

    count_query = "SELECT count(*) " + where_sql
    select_query = _LIST_SELECT_COLS + where_sql

    select_params = list(params)
    select_params.append(limit)
    select_query += f" ORDER BY ta.tour_id, ta.created_at LIMIT ${len(select_params)}"
    select_params.append(offset)
    select_query += f" OFFSET ${len(select_params)}"

    async with pool.acquire() as conn:
        total = await conn.fetchval(count_query, *params)
        rows = await conn.fetch(select_query, *select_params)

    return {
        "atoms": [_safe(r) for r in rows], "count": len(rows),
        "total": total, "limit": limit, "offset": offset,
    }


# ── PATCH /admin/atoms/{atom_id} — star / delete / light edit ──────────────

class AtomPatchRequest(BaseModel):
    starred: Optional[bool] = None
    deleted: Optional[bool] = None
    text: Optional[str] = None


@router.patch("/atoms/{atom_id}")
async def patch_atom(
    atom_id: str,
    body: AtomPatchRequest,
    request: Request,
    x_admin_secret: str = Header(None),
):
    """Star / soft-delete / light text edit. `deleted=true` is the existing
    tour_atoms.deleted column (soft delete) — already excluded from the N6
    allocator's eligible pool (services/acp_planning/allocator.py's
    _eligible_atoms(): `if a.deleted ... continue`). `starred=true` is the
    existing tour_atoms.starred column — already boosted 1.5x in the same
    allocator. No new columns, no migration (AA-300 STEP 0 finding)."""
    verify_admin_secret(x_admin_secret)

    if body.text is not None and not body.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")
    if body.starred is None and body.deleted is None and body.text is None:
        raise HTTPException(status_code=400, detail="no fields to update")

    sets = []
    params: list = []

    def _set(column: str, value) -> None:
        params.append(value)
        sets.append(f"{column} = ${len(params)}")

    if body.starred is not None:
        _set("starred", body.starred)
    if body.deleted is not None:
        _set("deleted", body.deleted)
    if body.text is not None:
        _set("text", body.text)
    sets.append("updated_at = now()")

    params.append(atom_id)
    query = f"""
        UPDATE acp_contract.tour_atoms
        SET {", ".join(sets)}
        WHERE atom_id = ${len(params)} AND NOT is_empty_marker
        RETURNING atom_id, tour_id, text, distinctiveness, starred, deleted,
                  visual_potential, media, created_at, updated_at
    """

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *params)

    if not row:
        raise HTTPException(status_code=404, detail=f"Atom {atom_id} not found (or is an empty-marker row)")
    return _safe(row)


# ── GET /admin/atoms/preview-slotgrid — first visual look at N0->N6 ────────

@router.get("/atoms/preview-slotgrid")
async def preview_slotgrid(
    request: Request,
    tenant_id: str = Query(str(_AA_INTERNAL_TENANT_ID)),
    x_admin_secret: str = Header(None),
):
    """Runs the real N4/N5/N6 chain (services/acp_planning/) against the
    just-curated atom pool for one tenant and returns the resulting
    SlotGrid — the first screen in the whole ACP v2 build (N0-N6) that
    shows anything visually, rather than test code + direct DB queries.

    markets=["US"], channels=["blog"], capacity_posts_per_week=4 are
    hardcoded demo defaults, NOT read from any tenant-config table — none
    exists yet (flagged as a real gap in AA-301's own implementation notes,
    same gap resurfacing here, not silently invented further). Quarter plan
    is auto-approved as "admin-preview-demo" purely for this read-only demo
    endpoint — Gate B (no auto-approval) still holds for the real N5/N6
    production path; nothing here writes to the DB."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    try:
        tenant_uuid = UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid tenant_id: {tenant_id!r}")

    today = date.today()
    quarter = (today.month - 1) // 3 + 1
    markets = ["US"]
    channels = ["blog"]
    capacity_posts_per_week = 4

    runway = await runway_map(tenant_uuid, today.year, markets, pool)
    quarter_plan = await plan_quarter(
        tenant_uuid, today.year, quarter, markets, capacity_posts_per_week, [], runway, pool,
    )
    approve_quarter_plan(quarter_plan, approved_by="admin-preview-demo")
    grid = await allocate_month(
        tenant_uuid, today.year, today.month, channels, capacity_posts_per_week,
        quarter_plan, runway, markets[0], pool,
    )

    return {
        "runway_cell_count": len(runway.cells),
        "quarter_plan": quarter_plan.model_dump(mode="json"),
        "slot_grid": grid.model_dump(mode="json"),
        "demo_params": {
            "markets": markets, "channels": channels,
            "capacity_posts_per_week": capacity_posts_per_week,
            "note": "hardcoded demo defaults — no tenant-config table exists yet (AA-301 gap)",
        },
    }
