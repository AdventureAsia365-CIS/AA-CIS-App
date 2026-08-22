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
GET   /admin/atoms/summary            — dashboard counts + by-tour accordion data
PATCH /admin/atoms/bulk               — star / soft-delete many atoms at once
PATCH /admin/atoms/{atom_id}          — star / soft-delete / light text edit
GET   /admin/atoms/preview-slotgrid   — runway_map -> plan_quarter ->
                                         approve_quarter_plan -> allocate_month
                                         for one tenant, returns the SlotGrid
                                         (optional ?version_id= reads one
                                         specific approved historical version
                                         instead of the current one, AA-323
                                         round 6 Phần A)

Route order note: /atoms/bulk and /atoms/summary/preview-slotgrid are
registered BEFORE /atoms/{atom_id} — this repo's own CRITICAL rule
(CLAUDE.md: "/{id}/full MUST come BEFORE /{id}") applies here too, since
FastAPI would otherwise greedily match "bulk" as {atom_id} on a PATCH
/atoms/bulk request.
"""
import json
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from api.routers.admin import verify_admin_secret
from api.routers.auth import verify_jwt
from services.acp_planning.allocator import allocate_month, allocate_month_from_db
from services.acp_planning.quarter import (
    approve_quarter_plan, fetch_approved_quarter_plan, fetch_current_version_no,
    fetch_quarter_plan_version, plan_quarter,
)
from services.acp_planning.runway import runway_map
from services.acp_planning.tenant_config import fetch_tenant_planning_config
from services.acp_shared.atom_constants import THIN_TRIP_ATOM_MIN

router = APIRouter(prefix="/admin", tags=["admin-atoms"])

# AA_internal — the only tenant with real tour/atom data today (verified live,
# AA-301 STEP 0: 793/793 raw_tours rows). Used as the default for the preview
# endpoint's tenant_id query param so the demo works out of the box.
_AA_INTERNAL_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


# ── AA-431 — tenant-JWT auth + owner_scope filter for list/summary/patch ────────
#
# Before this, every endpoint here was x-admin-secret only (module header comment,
# AA-300 STEP 0 decision) — fine while the only UI was /admin/curation (staff-only,
# platform-owned atoms). AA-425's T5 (services/acp_produce/tenant_pipeline.py)
# started writing atoms with owner_scope = <tenant_id> (a TENANT's own atoms, from
# their own rewritten content) alongside the pre-existing owner_scope = 'platform'
# rows — but nothing here ever filtered by owner_scope, and there was no tenant-JWT
# auth path at all. Building a tenant-facing curation UI (AA-431, /portal/t6-atoms)
# straight on top of these endpoints as they were would have let tenant A see/edit
# tenant B's atoms (or platform's) — same class of gap AA-424 already closed for
# brand-identity. Mirrors that fix's exact shape (_resolve_brand_tenant_id,
# admin_pipeline.py): try a tenant Bearer JWT first, fall back to X-Admin-Secret.
#
# owner_scope is NEVER accepted as a client-supplied query param for a tenant
# caller — it's derived only from the verified JWT's `sub` claim, so a tenant can't
# request a different owner_scope than its own. An admin/staff caller (X-Admin-
# Secret) gets owner_scope=None (no filter) — unchanged from before, staff still
# need to see platform + every tenant's atoms for curation/support.
_atoms_bearer = HTTPBearer(auto_error=False)


def _resolve_atom_owner_scope(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_atoms_bearer),
    x_admin_secret: str = Header(None),
) -> Optional[str]:
    """Returns the owner_scope to filter tour_atoms by (a tenant_id string), or
    None for a staff/admin caller (no filter — sees platform + every tenant)."""
    if credentials is not None:
        try:
            payload = verify_jwt(credentials.credentials)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return payload["sub"]
    verify_admin_secret(x_admin_secret)
    return None


def _preview_month_for_quarter(year: int, quarter: int) -> int:
    """AA-323 round 7 — single source of truth for "which month does a Slot
    Grid Preview compute", used by BOTH preview_slotgrid() branches below.
    Before this, the two branches derived `month` independently
    (`?version_id=` used the quarter's first month; the no-`version_id`
    default used `date.today().month`) — for the SAME (year, quarter) these
    only agree when today happens to fall in the quarter's first month.
    Live-verified round 7: for aa_internal's actually-current v6 (Q3 2026,
    today=2026-08-13), that mismatch (month=7 vs month=8) made
    `runway.stage("South Korea", "US", month)` return MOFU for one path and
    BOFU for the other — same approved version, two different Slot Grids
    (funnel_stage AND framework, since FRAMEWORK_TABLE keys off funnel_stage)
    depending only on which UI button was clicked. Fix: derive month from
    (year, quarter) alone — if it's the REAL current quarter, "what should
    ship right now" is today's actual month (matches what the default,
    no-`?version_id=` Preview button has always shown); otherwise (a
    genuinely different quarter — a true historical version, or one that's
    not yet current) there is no meaningful "today" for it, so it falls
    back to the quarter's first month. This makes `?version_id=<the current
    version's id>` and no `?version_id=` at all ALWAYS resolve to the exact
    same (year, quarter, month) and therefore the exact same computed
    SlotGrid — the invariant round 7 requires."""
    today = date.today()
    if (year, quarter) == (today.year, (today.month - 1) // 3 + 1):
        return today.month
    return (quarter - 1) * 3 + 1


def _safe(row) -> dict:
    """Same pattern as v1_tours.py's local safe() helper — UUID/Decimal/
    datetime -> JSON-safe. No shared api/utils.safe() exists in this repo
    (checked); every router defines its own local copy.

    Also parses `media` (tour_atoms.media, JSONB) if it comes back as a raw
    string — asyncpg has no jsonb codec registered on this app's
    connections (same gap AA-314 already found for src_highlights
    elsewhere, api/routers/v1_tours.py; also just found for
    cooldown_until/usage_log in services/acp_planning/quarter.py). Without
    this, atom.media?.has_photo on the frontend silently reads undefined
    off a JSON string instead of the real boolean — no crash, just always
    "no photo" regardless of actual data."""
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
    if "media" in d and isinstance(d["media"], str):
        d["media"] = json.loads(d["media"]) if d["media"] else {}
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
    tour_ids: Optional[str] = Query(None),
    atom_ids: Optional[str] = Query(None),
    distinctiveness: Optional[str] = Query(None, pattern="^(HIGH|MED|LOW)$"),
    unreviewed_only: bool = Query(False),
    thin_only: bool = Query(False),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    owner_scope: Optional[str] = Depends(_resolve_atom_owner_scope),
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
    (< THIN_TRIP_ATOM_MIN, the same constant N5's B5 fix imports).

    AA-431: owner_scope resolved server-side from the caller's identity (tenant JWT
    -> that tenant's own atoms only; admin secret -> no filter) — never a query
    param, so a tenant can't ask to see another owner_scope's atoms."""
    pool = request.app.state.pool

    clauses = []
    params: list = []

    def _add(clause: str, value) -> None:
        params.append(value)
        clauses.append(clause.format(n=len(params)))

    if owner_scope is not None:
        _add("ta.owner_scope = ${n}", owner_scope)

    # AA-345 round 2, Việc 4: tour_ids (comma-separated, plural) is the deep
    # link from /admin/atomize after a multi-tour decompose run — lets the
    # curation page filter to exactly the tours just processed instead of
    # losing them in a long list. tour_id (singular) is the older single-tour
    # link, kept unchanged for backward compat; tour_ids wins if both given.
    if tour_ids:
        id_list = [t.strip() for t in tour_ids.split(",") if t.strip()]
        if id_list:
            _add("ta.tour_id = ANY(${n}::uuid[])", id_list)
    elif tour_id:
        _add("ta.tour_id = ${n}::uuid", tour_id)
    # AA-323 Gap 4 — Preview's slot cards link an atom_id list straight to this
    # endpoint for a detail panel, rather than adding a separate single-purpose
    # route. Independent of tour_id/tour_ids so it can be combined or used alone.
    if atom_ids:
        atom_id_list = [a.strip() for a in atom_ids.split(",") if a.strip()]
        if atom_id_list:
            _add("ta.atom_id = ANY(${n})", atom_id_list)
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


# ── GET /admin/atoms/summary — dashboard counts + by-tour accordion data ───

@router.get("/atoms/summary")
async def atoms_summary(
    request: Request,
    owner_scope: Optional[str] = Depends(_resolve_atom_owner_scope),
):
    """Whole-dataset counts, deliberately independent of whatever filter is
    currently applied on the paginated /atoms list — a separate endpoint
    rather than extra fields bolted onto GET /atoms, because the dashboard
    only needs to change when the underlying data changes (a star/delete/
    bulk action), not on every filter click or load-more page fetch. Folding
    it into the list response would mean recomputing 3 extra aggregate
    queries on every single filter/pagination round-trip for no reason —
    fewer total queries over a real editing session with this split.

    AA-431: same owner_scope resolution as GET /atoms — a tenant caller only
    ever sees counts for its own atoms."""
    pool = request.app.state.pool
    scope_clause = "AND owner_scope = $1" if owner_scope is not None else ""
    scope_params = [owner_scope] if owner_scope is not None else []
    scope_clause_ta = "AND ta.owner_scope = $1" if owner_scope is not None else ""

    async with pool.acquire() as conn:
        breakdown_rows = await conn.fetch(f"""
            SELECT distinctiveness, count(*) AS c
            FROM acp_contract.tour_atoms
            WHERE NOT deleted AND NOT is_empty_marker {scope_clause}
            GROUP BY distinctiveness
        """, *scope_params)
        totals = await conn.fetchrow(f"""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE updated_at != created_at) AS reviewed
            FROM acp_contract.tour_atoms
            WHERE NOT deleted AND NOT is_empty_marker {scope_clause}
        """, *scope_params)
        by_tour_rows = await conn.fetch(f"""
            SELECT ta.tour_id, rt.src_name AS tour_name,
                   count(*) AS atom_count,
                   count(*) FILTER (WHERE ta.updated_at = ta.created_at) AS unreviewed_count,
                   MAX(ta.created_at) AS atomized_at
            FROM acp_contract.tour_atoms ta
            JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = ta.tour_id
            WHERE NOT ta.deleted AND NOT ta.is_empty_marker {scope_clause_ta}
            GROUP BY ta.tour_id, rt.src_name
            ORDER BY rt.src_name
        """, *scope_params)

    breakdown = {"HIGH": 0, "MED": 0, "LOW": 0}
    for r in breakdown_rows:
        if r["distinctiveness"] in breakdown:
            breakdown[r["distinctiveness"]] = r["c"]

    by_tour = [
        {
            "tour_id": str(r["tour_id"]), "tour_name": r["tour_name"],
            "atom_count": r["atom_count"], "is_thin": r["atom_count"] < THIN_TRIP_ATOM_MIN,
            "unreviewed_count": r["unreviewed_count"],
            # AA-345 round 2, Việc 4: MAX(created_at) — same "last touched"
            # choice as GET /admin/tours-for-atomization's atomized_at, for
            # the new "Newest first" sort + section-header date display.
            "atomized_at": r["atomized_at"].isoformat() if r["atomized_at"] else None,
        }
        for r in by_tour_rows
    ]

    return {
        "distinctiveness_breakdown": breakdown,
        "total_count": totals["total"] if totals else 0,
        "reviewed_count": totals["reviewed"] if totals else 0,
        "by_tour": by_tour,
    }


# ── PATCH /admin/atoms/bulk — star / delete many atoms at once ─────────────

class BulkAtomPatchRequest(BaseModel):
    atom_ids: list[str]
    starred: Optional[bool] = None
    deleted: Optional[bool] = None


@router.patch("/atoms/bulk")
async def patch_atoms_bulk(
    body: BulkAtomPatchRequest,
    request: Request,
    owner_scope: Optional[str] = Depends(_resolve_atom_owner_scope),
):
    """Star/soft-delete many atoms in a single UPDATE ... WHERE atom_id =
    ANY($1), not N sequential PATCH calls — for the curation UI's
    multi-select bulk actions. Only starred/deleted are supported in bulk
    (no bulk text edit — editing many atoms' text to the same value isn't
    a real use case).

    AA-431: a tenant caller's UPDATE is also WHERE-scoped to owner_scope, not
    just filtered on read — an atom_id belonging to another tenant/platform
    silently matches 0 rows instead of being editable via a guessed id (IDOR)."""
    if not body.atom_ids:
        raise HTTPException(status_code=400, detail="atom_ids must not be empty")
    if body.starred is None and body.deleted is None:
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
    sets.append("updated_at = now()")

    params.append(body.atom_ids)
    atom_ids_idx = len(params)
    scope_clause = ""
    if owner_scope is not None:
        params.append(owner_scope)
        scope_clause = f" AND owner_scope = ${len(params)}"
    query = f"""
        UPDATE acp_contract.tour_atoms
        SET {", ".join(sets)}
        WHERE atom_id = ANY(${atom_ids_idx}){scope_clause} AND NOT is_empty_marker
        RETURNING atom_id, tour_id, text, distinctiveness, starred, deleted,
                  visual_potential, media, created_at, updated_at
    """

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    return {"updated": [_safe(r) for r in rows], "updated_count": len(rows)}


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
    owner_scope: Optional[str] = Depends(_resolve_atom_owner_scope),
):
    """Star / soft-delete / light text edit. `deleted=true` is the existing
    tour_atoms.deleted column (soft delete) — already excluded from the N6
    allocator's eligible pool (services/acp_planning/allocator.py's
    _eligible_atoms(): `if a.deleted ... continue`). `starred=true` is the
    existing tour_atoms.starred column — already boosted 1.5x in the same
    allocator. No new columns, no migration (AA-300 STEP 0 finding).

    AA-431: same owner_scope guard as the bulk endpoint — a tenant's UPDATE
    is WHERE-scoped, so a guessed atom_id from outside their own scope 404s
    (not found) instead of being editable."""
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
    atom_id_idx = len(params)
    scope_clause = ""
    if owner_scope is not None:
        params.append(owner_scope)
        scope_clause = f" AND owner_scope = ${len(params)}"
    query = f"""
        UPDATE acp_contract.tour_atoms
        SET {", ".join(sets)}
        WHERE atom_id = ${atom_id_idx}{scope_clause} AND NOT is_empty_marker
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
    version_id: Optional[str] = Query(None),
    x_admin_secret: str = Header(None),
):
    """Runs the real N4/N5/N6 chain (services/acp_planning/) against the
    just-curated atom pool for one tenant and returns the resulting
    SlotGrid — the first screen in the whole ACP v2 build (N0-N6) that
    shows anything visually, rather than test code + direct DB queries.

    markets/channels come from acp_shared.tenant_config (AA-323 Gap 3,
    migration 101, defaults to ["US"]/["blog"] if unset); capacity comes from
    shared.tenants.posts_per_week (AA-384) — no more hardcoded constants.

    AA-323 Gap 1: checks for a real Gate-B-approved quarter_plan_version
    first (fetch_approved_quarter_plan) and reads N6 through
    allocate_month_from_db() when one exists. Only falls back to the
    in-memory "admin-preview-demo" auto-approve + allocate_month() path when
    no approved plan exists yet for this tenant/year/quarter — this is what
    makes the full create -> Gate B approve -> N6-reads-the-real-version
    chain observable from this screen without a separate production
    endpoint. Either way nothing here writes a NEW row — the demo path never
    persisted (unchanged from AA-300); the real path only ever reads.

    AA-323 round 6, Phần A: optional `version_id` reads one SPECIFIC
    historical version (from the History tab's new "View in Slot Grid
    Preview" link) instead of always the tenant/quarter's current approved
    version. version_id alone determines tenant/year/quarter (via
    fetch_quarter_plan_version) — the `tenant_id` query param is ignored
    when version_id is given. Only an approved version may be previewed
    (Gate B: N6 must never read an un-approved plan, historical or not) —
    a pending/rejected version_id 400s with a clear reason rather than
    silently allocating from it.

    AA-323 round 7: `month` for BOTH branches now comes from the single
    shared `_preview_month_for_quarter()` (see its docstring for the full
    root-cause story) instead of each branch computing it independently —
    that divergence was a real, live-verified bug: the exact same approved
    version rendered two different Slot Grids (different funnel_stage AND
    framework) depending only on whether it was reached via `?version_id=`
    or the plain default link."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    version_row = None
    if version_id:
        try:
            version_uuid = UUID(version_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid version_id: {version_id!r}")
        version_row = await fetch_quarter_plan_version(version_uuid, pool)
        if version_row is None:
            raise HTTPException(status_code=404, detail=f"Quarter plan version {version_id} not found")
        if version_row["approval_status"] != "approved":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Version v{version_row['version_no']} is '{version_row['approval_status']}', not "
                    "approved — Gate B requires approval before a slot grid can be computed for it."
                ),
            )
        tenant_uuid = version_row["tenant_id"]
        year = version_row["year"]
        quarter = version_row["quarter"]
        month = _preview_month_for_quarter(year, quarter)
    else:
        try:
            tenant_uuid = UUID(tenant_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid tenant_id: {tenant_id!r}")
        today = date.today()
        year = today.year
        quarter = (today.month - 1) // 3 + 1
        month = _preview_month_for_quarter(year, quarter)

    config = await fetch_tenant_planning_config(tenant_uuid, pool)
    markets = config.markets
    channels = config.channels
    capacity_posts_per_week = config.capacity_posts_per_week

    runway = await runway_map(tenant_uuid, year, markets, pool)

    if version_row is not None:
        quarter_plan = version_row["plan"]
        demo_mode = False
        version_no = version_row["version_no"]
        grid = await allocate_month(
            tenant_uuid, year, month, channels, capacity_posts_per_week,
            quarter_plan, runway, markets[0], pool,
        )
        note = (
            f"Reading historical quarter plan version v{version_no} (Q{quarter} {year}) — "
            "not necessarily the tenant's current live version."
        )
    else:
        # AA-323 round 7: confirmed (not assumed) that the in-memory demo
        # path below can NEVER run while a real current_version_id exists —
        # fetch_approved_quarter_plan()'s own query requires
        # `qpv.version_id = qp.current_version_id AND qpv.approval_status =
        # 'approved'`, so `demo_mode` is only True when no plan row exists
        # yet, or current_version_id is unset. This is what round 5's live
        # curl already showed (demo_mode=False, trip_ids matched v6
        # byte-for-byte) — round 7 re-confirmed it live again after this
        # round's changes; see TestPreviewSlotgridDemoNeverRunsWithCurrent
        # in test_aa300_admin_atoms.py for the locked-in regression test.
        quarter_plan = await fetch_approved_quarter_plan(tenant_uuid, year, quarter, pool)
        demo_mode = quarter_plan is None
        version_no = None
        if demo_mode:
            quarter_plan = await plan_quarter(
                tenant_uuid, year, quarter, markets, capacity_posts_per_week, [], runway, pool,
            )
            approve_quarter_plan(quarter_plan, approved_by="admin-preview-demo")
            grid = await allocate_month(
                tenant_uuid, year, month, channels, capacity_posts_per_week,
                quarter_plan, runway, markets[0], pool,
            )
            note = (
                "No Gate B-approved quarter plan exists yet for this tenant/quarter — showing an "
                "unpersisted preview auto-approved in-memory as \"admin-preview-demo\". Create and "
                "approve a real plan via Quarter Plan Approval to replace this."
            )
        else:
            # AA-323 round 5 — Việc 2: which persisted version this screen is reading.
            version_no = await fetch_current_version_no(tenant_uuid, year, quarter, pool)
            grid = await allocate_month_from_db(
                tenant_uuid, year, month, channels, capacity_posts_per_week,
                runway, markets[0], pool,
            )
            note = "Reading a real Gate B-approved quarter plan (not a preview)."

    return {
        "runway_cell_count": len(runway.cells),
        "runway_cells": [c.model_dump(mode="json") for c in runway.cells],
        "quarter_plan": quarter_plan.model_dump(mode="json"),
        "quarter_plan_version_no": version_no,
        "slot_grid": grid.model_dump(mode="json"),
        "demo_params": {
            "markets": markets, "channels": channels,
            "capacity_posts_per_week": capacity_posts_per_week,
            "demo_mode": demo_mode,
            "note": note,
        },
    }
