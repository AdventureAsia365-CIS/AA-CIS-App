from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from pydantic import BaseModel as _BM
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


# ── P3-S4: Shared Pool Browse ─────────────────────────────────────────────────

@router.get("/pool")
async def browse_pool(
    request: Request,
    tenant=Depends(get_tenant),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    country: Optional[str] = Query(None),
    min_quality: Optional[float] = Query(None, ge=0, le=10),
    search: Optional[str] = Query(None),
):
    """Browse AA shared pool (published_tours from aa_internal).
    All active tenants can read the pool — RLS bypassed via aa_internal filter.
    """
    tenant_id = tenant["sub"]
    pool = request.app.state.pool
    offset = (page - 1) * page_size

    conditions = ["pt.tenant_id = '00000000-0000-0000-0000-000000000001'::uuid"]
    params: list = []

    if country:
        params.append(country)
        conditions.append(f"LOWER(rt.country) = LOWER(${len(params)})")
    if min_quality is not None:
        params.append(min_quality)
        conditions.append(f"pt.quality_score >= ${len(params)}")
    if search:
        params.append(f"%{search}%")
        conditions.append(f"pt.aa_name ILIKE ${len(params)}")

    where = "WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        total = await conn.fetchval(f"""
            SELECT COUNT(*)
            FROM gold_aa_internal.published_tours pt
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            {where}
        """, *params)

        # tenant_id added as last param for already_rewritten subquery
        params_paged = params + [page_size, offset, tenant_id]
        tid_idx = len(params) + 3  # position of tenant_id in params_paged
        rows = await conn.fetch(f"""
            SELECT pt.id, pt.tour_id, pt.aa_name, pt.aa_subtitle, pt.aa_summary,
                   pt.aa_highlights, pt.aa_itineraries, pt.aa_description,
                   pt.seo_title, pt.seo_meta, pt.seo_keywords_used,
                   pt.quality_score, pt.published_at,
                   rt.country, rt.duration, rt.price_raw,
                   EXISTS(
                       SELECT 1 FROM gold_aa_internal.tenant_tour_versions ttv
                       WHERE ttv.published_tour_id = pt.id
                         AND ttv.tenant_id = ${tid_idx}::uuid
                   ) AS already_rewritten
            FROM gold_aa_internal.published_tours pt
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            {where}
            ORDER BY pt.quality_score DESC, pt.published_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
        """, *params_paged)

        # Countries for filter dropdown
        countries = await conn.fetch("""
            SELECT DISTINCT rt.country
            FROM gold_aa_internal.published_tours pt
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE pt.tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
              AND rt.country IS NOT NULL
            ORDER BY rt.country
        """)

    return {
        "data": [dict(r) for r in rows],
        "pagination": {"page": page, "page_size": page_size,
                       "total": total, "pages": -(-total // page_size)},
        "countries": [r["country"] for r in countries],
        "tenant_id": tenant_id,
    }


# ── P3-S4: Trigger Rewrite ────────────────────────────────────────────────────


class RewriteRequest(_BM):
    rewrite_language: str = "en-US"
    seo_mode: str = "standard"
    custom_notes: Optional[str] = None


@router.post("/pool/{published_tour_id}/rewrite")
async def trigger_rewrite(
    published_tour_id: str,
    body: RewriteRequest,
    request: Request,
    tenant=Depends(get_tenant),
):
    """Trigger tenant rewrite of a published tour.
    Creates tenant_tour_versions record (status=pending) and calls pipeline.
    """
    tenant_id = tenant["sub"]
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        # Check published tour exists
        pt = await conn.fetchrow("""
            SELECT id, aa_name, aa_summary, aa_description, aa_highlights,
                   aa_itineraries, seo_title, seo_meta, seo_keywords_used
            FROM gold_aa_internal.published_tours
            WHERE id = $1::uuid
        """, published_tour_id)
        if not pt:
            raise HTTPException(status_code=404, detail="Tour not found in pool")

        # Get next version number
        next_ver = await conn.fetchval("""
            SELECT COALESCE(MAX(version_number), 0) + 1
            FROM gold_aa_internal.tenant_tour_versions
            WHERE tenant_id = $1::uuid AND published_tour_id = $2::uuid
        """, tenant_id, published_tour_id)

        # Create pending version record
        import json as _json
        version_id = await conn.fetchval("""
            INSERT INTO gold_aa_internal.tenant_tour_versions
                (tenant_id, published_tour_id, version_number,
                 rewritten_content, status, edit_source,
                 rewrite_language, seo_mode)
            VALUES ($1::uuid, $2::uuid, $3,
                    $4::jsonb, 'pending', 'ai_generated',
                    $5, $6)
            RETURNING id
        """,
            tenant_id, published_tour_id, next_ver,  # noqa: E128
            _json.dumps({  # noqa: E128
                "name": pt["aa_name"], "summary": pt["aa_summary"],
                "status": "generating",
            }),
            body.rewrite_language, body.seo_mode)

    # P3-S9 fix: actually call LLM rewrite
    import asyncio as _asyncio
    import sys as _sys
    _sys.path.insert(0, '/app')
    from api.routers.v1_pipeline import _rewrite_tour as _do_rewrite

    # Build tour dict from published tour
    tour_dict = {
        "name":        pt["aa_name"],
        "subtitle":    pt.get("aa_subtitle", ""),
        "summary":     pt.get("aa_summary", ""),
        "description": pt.get("aa_description", ""),
        "highlights":  pt.get("aa_highlights", ""),
        "itineraries": pt.get("aa_itineraries", ""),
        "seo_title":   pt.get("aa_seo_title", ""),
        "seo_meta":    pt.get("aa_seo_meta", ""),
        "country":     "",
        "duration":    "",
    }

    # Fetch brand rules for this tenant
    brand_rules = {}
    try:
        import json as _json2
        br_row = await pool.acquire().__aenter__()
        async with pool.acquire() as _conn2:
            _br = await _conn2.fetchrow("""
                SELECT system_prompt, style_guide, forbidden_words
                FROM shared.tenant_brand_rules
                WHERE tenant_id = $1::uuid AND is_active = true
                ORDER BY version DESC LIMIT 1
            """, tenant_id)
        if _br:
            brand_rules = {
                "system_prompt":    _br["system_prompt"] or "",
                "style_guide":      _br["style_guide"] or "",
                "forbidden_words":  list(_br["forbidden_words"] or []),
                "rewrite_language": body.rewrite_language,
            }
    except Exception:
        brand_rules = {"rewrite_language": body.rewrite_language}

    # Run LLM rewrite in background (don't block response)
    async def _do_rewrite_and_save():
        try:
            result = await _do_rewrite(tour_dict, idx=0, total=1, brand_rules=brand_rules)
            if result.get("status") == "success" and result.get("generated"):
                import json as _j3
                gen = result["generated"]
                rewritten = {
                    "name":        gen.get("name", tour_dict["name"]),
                    "subtitle":    gen.get("subtitle", ""),
                    "summary":     gen.get("summary", ""),
                    "highlights":  gen.get("highlights", []),
                    "itineraries": gen.get("itineraries", tour_dict.get("itineraries", "")),
                    "seo_title":   gen.get("seo_title", ""),
                    "seo_meta":    gen.get("seo_meta", ""),
                    "trip_type":   gen.get("trip_type", ""),
                    "status":      "done",
                }
                new_status = "approved" if result.get("quality_score", 0) >= 7.0 else "pending"
                async with pool.acquire() as _conn3:
                    await _conn3.execute("""
                        UPDATE gold_aa_internal.tenant_tour_versions
                        SET rewritten_content = $1::jsonb,
                            status = $2,
                            quality_score = $3
                        WHERE id = $4::uuid
                    """,
                        _j3.dumps(rewritten), new_status,
                        result.get("quality_score"), version_id)
        except Exception as _e:
            import structlog as _sl
            _sl.get_logger().error("tenant_rewrite_failed", error=str(_e))

    _asyncio.create_task(_do_rewrite_and_save())

    return {
        "version_id": str(version_id),
        "published_tour_id": published_tour_id,
        "version_number": next_ver,
        "status": "pending",
        "message": "Rewrite started — check My Catalog in ~30 seconds for results",
    }


# ── P3-S4: My Versions (Tenant Catalog) ──────────────────────────────────────

@router.get("/my-versions")
async def list_my_versions(
    request: Request,
    tenant=Depends(get_tenant),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
):
    """List tenant's own rewritten versions."""
    tenant_id = tenant["sub"]
    pool = request.app.state.pool
    offset = (page - 1) * page_size

    conditions = ["ttv.tenant_id = $1::uuid"]
    params: list = [tenant_id]

    if status:
        params.append(status)
        conditions.append(f"ttv.status = ${len(params)}")
    if country:
        params.append(country)
        conditions.append(f"LOWER(rt.country) = LOWER(${len(params)})")

    where = "WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        total = await conn.fetchval(f"""
            SELECT COUNT(*)
            FROM gold_aa_internal.tenant_tour_versions ttv
            JOIN gold_aa_internal.published_tours pt ON pt.id = ttv.published_tour_id
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            {where}
        """, *params)

        params_paged = params + [page_size, offset]
        rows = await conn.fetch(f"""
            SELECT ttv.id, ttv.version_number, ttv.status, ttv.quality_score,
                   ttv.edit_source, ttv.rewrite_language, ttv.created_at,
                   ttv.rewritten_content,
                   pt.id AS published_tour_id, pt.aa_name, pt.quality_score AS aa_quality,
                   rt.country, rt.duration
            FROM gold_aa_internal.tenant_tour_versions ttv
            JOIN gold_aa_internal.published_tours pt ON pt.id = ttv.published_tour_id
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            {where}
            ORDER BY ttv.created_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
        """, *params_paged)

    return {
        "data": [dict(r) for r in rows],
        "pagination": {"page": page, "page_size": page_size,
                       "total": total, "pages": -(-total // page_size)},
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


# ── P3-S4: Version Detail + Approve/Reject/Edit ───────────────────────────────

@router.get("/versions/{version_id}")
async def get_version(
    version_id: str,
    request: Request,
    tenant=Depends(get_tenant),
):
    """Get version detail with AA original for before/after diff."""
    tenant_id = tenant["sub"]
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT ttv.*, pt.aa_name, pt.aa_subtitle, pt.aa_summary,
                   pt.aa_description, pt.aa_highlights, pt.aa_itineraries,
                   pt.seo_title AS aa_seo_title, pt.seo_meta AS aa_seo_meta,
                   pt.quality_score AS aa_quality_score,
                   rt.country, rt.duration, rt.price_raw
            FROM gold_aa_internal.tenant_tour_versions ttv
            JOIN gold_aa_internal.published_tours pt ON pt.id = ttv.published_tour_id
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE ttv.id = $1::uuid AND ttv.tenant_id = $2::uuid
        """, version_id, tenant_id)

        if not row:
            raise HTTPException(status_code=404, detail="Version not found")

        # Version history
        history = await conn.fetch("""
            SELECT id, version_number, status, edit_source, quality_score, created_at
            FROM gold_aa_internal.tenant_tour_versions
            WHERE tenant_id = $1::uuid AND published_tour_id = $2::uuid
            ORDER BY version_number ASC
        """, tenant_id, row["published_tour_id"])

    return {
        **dict(row),
        "version_history": [dict(h) for h in history],
    }


class VersionActionRequest(_BM):
    action: str  # approve | reject | edit
    edited_content: Optional[dict] = None
    edited_by: Optional[str] = None


@router.patch("/versions/{version_id}")
async def update_version(
    version_id: str,
    body: VersionActionRequest,
    request: Request,
    tenant=Depends(get_tenant),
):
    """Approve, reject, or inline-edit a tenant tour version."""
    import json as _json
    tenant_id = tenant["sub"]
    pool = request.app.state.pool

    if body.action not in ("approve", "reject", "edit"):
        raise HTTPException(status_code=400, detail="action must be approve|reject|edit")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, published_tour_id, version_number, rewritten_content
            FROM gold_aa_internal.tenant_tour_versions
            WHERE id = $1::uuid AND tenant_id = $2::uuid
        """, version_id, tenant_id)
        if not row:
            raise HTTPException(status_code=404, detail="Version not found")

        if body.action == "edit" and body.edited_content:
            # Inline edit → create new version
            next_ver = await conn.fetchval("""
                SELECT COALESCE(MAX(version_number), 0) + 1
                FROM gold_aa_internal.tenant_tour_versions
                WHERE tenant_id = $1::uuid AND published_tour_id = $2::uuid
            """, tenant_id, row["published_tour_id"])

            new_id = await conn.fetchval("""
                INSERT INTO gold_aa_internal.tenant_tour_versions
                    (tenant_id, published_tour_id, version_number,
                     parent_version_id, rewritten_content, status,
                     edit_source, edited_at, edited_by_user)
                VALUES ($1::uuid, $2::uuid, $3,
                        $4::uuid, $5::jsonb, 'pending',
                        'tenant_edit', NOW(), $6)
                RETURNING id
            """,
            tenant_id, row["published_tour_id"], next_ver,  # noqa: E128
            version_id,  # noqa: E128 E122
            _json.dumps(body.edited_content), body.edited_by or "tenant")  # noqa: E128 E122
            return {
                "status": "edited",
                "new_version_id": str(new_id),
                "version_number": next_ver,
            }

        else:
            new_status = "approved" if body.action == "approve" else "rejected"
            await conn.execute("""
                UPDATE gold_aa_internal.tenant_tour_versions
                SET status = $1, edited_at = NOW()
                WHERE id = $2::uuid AND tenant_id = $3::uuid
            """, new_status, version_id, tenant_id)
            return {"status": new_status, "version_id": version_id}
# P3 complete Tue May  5 11:42:07 +07 2026


# ── P4: Full review endpoint — before/after + inline edit + approve ───────────
@router.get("/{tour_id}/full")
async def get_tour_full(
    tour_id: str,
    request: Request,
    tenant=Depends(get_tenant),
):
    """Full before/after data for catalog review panel."""
    tenant_id = tenant["sub"]
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        pt = await conn.fetchrow("""
            SELECT * FROM gold_aa_internal.published_tours
            WHERE id = $1::uuid AND tenant_id = $2::uuid
        """, tour_id, tenant_id)
        if not pt:
            raise HTTPException(status_code=404, detail="Tour not found")

        # Raw source data (before)
        raw = await conn.fetchrow("""
            SELECT * FROM silver_aa_internal.raw_tours
            WHERE tour_id = $1::uuid
        """, pt["tour_id"])

        # Generated content (AI output before export)
        gen = await conn.fetchrow("""
            SELECT * FROM silver_aa_internal.generated_content
            WHERE tour_id = $1::uuid
            ORDER BY version_num DESC LIMIT 1
        """, pt["tour_id"])

        # Quality scores
        qs = await conn.fetchrow("""
            SELECT * FROM silver_aa_internal.quality_scores
            WHERE generated_content_id = $1::uuid
            ORDER BY created_at DESC LIMIT 1
        """, gen["id"] if gen else None
        ) if gen else None

    def safe(row):
        if not row: return {}
        d = dict(row)
        for k, v in d.items():
            if hasattr(v, 'isoformat'):
                d[k] = v.isoformat()
        return d

    return {
        "published": safe(pt),
        "raw": safe(raw),
        "generated": safe(gen),
        "quality": safe(qs),
    }


class TourEditRequest(_BM):
    field: str
    value: str
    approved_by: Optional[str] = "content_team"


@router.patch("/{tour_id}/approve")
async def approve_tour_edit(
    tour_id: str,
    body: TourEditRequest,
    request: Request,
    tenant=Depends(get_tenant),
):
    """Inline edit + save a field on published_tour."""
    tenant_id = tenant["sub"]
    pool = request.app.state.pool

    ALLOWED = {
        "aa_name", "aa_subtitle", "aa_summary", "aa_description",
        "aa_highlights", "aa_itineraries", "mobile_card_text",
        "seo_title", "seo_meta",
    }
    if body.field not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"Field '{body.field}' not editable")

    async with pool.acquire() as conn:
        await conn.execute(f"""
            UPDATE gold_aa_internal.published_tours
            SET {body.field} = $1, approved_by = $2
            WHERE id = $3::uuid AND tenant_id = $4::uuid
        """, body.value, body.approved_by, tour_id, tenant_id)

    return {"ok": True, "field": body.field}
