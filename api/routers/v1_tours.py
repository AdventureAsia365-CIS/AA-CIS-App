import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from pydantic import BaseModel as _BM
from api.routers.auth import verify_jwt

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/tours", tags=["B2B Tours"])
security = HTTPBearer()

# AA-425: strong refs to the fire-and-forget rewrite (T2 + T3 + T5) background task —
# asyncio only keeps a weak ref to a bare create_task() result, so an unreferenced task can be
# GC'd mid-flight (same class of bug AA-223 already found/fixed for admin_pipeline.py's
# run-tour-async path — see that file's own comment on this pattern). T3's repair loop adds up
# to 2 more LLM round trips and T5 adds another on top of T2's own call, so this task now runs
# meaningfully longer than it did pre-AA-425 — worth closing this gap while touching this code.
_background_tasks: set = set()


def get_tenant(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        return verify_jwt(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_pool(request: Request):
    return request.app.state.pool


async def _run_ranking_pipeline(tenant_id: str, pool) -> None:
    """AA-515 — research (demand for whatever Segments aren't already fresh) then rank-sum,
    for one tenant's whole current Segment set. Launched via `asyncio.create_task()` right
    after `run_segment_matching()` in `atomize_version()` below (background, not awaited — see
    that call site's own comment). Swallows every exception itself (this is the top of its own
    task, nothing awaits it to propagate one to) — logs and returns, same as every other
    best-effort step already in this file.
    """
    try:
        from services.acp_contract.atom_ranking import run_atom_ranking
        from services.acp_contract.segment_research import run_segment_research
        from services.seo_intelligence.seed_builder import (
            LOCATION_CODE_TO_MARKET,
            resolve_buyer_markets,
        )
        from shared.services.tenant_config_service import TenantConfigService

        async with pool.acquire() as conn:
            cfg = await TenantConfigService(conn).get_seo_config(tenant_id)

        research_result = await run_segment_research(tenant_id, cfg.target_market, pool)
        market_codes = [
            LOCATION_CODE_TO_MARKET[loc]
            for loc, _name, _lang in resolve_buyer_markets(cfg.target_market)
        ]
        ranking_result = await run_atom_ranking(tenant_id, market_codes, pool)
        logger.info(
            "t5_ranking_pipeline_done", tenant_id=tenant_id,
            research=research_result, ranking=ranking_result,
        )
    except Exception:
        logger.warning("t5_ranking_pipeline_failed", tenant_id=tenant_id, exc_info=True)


# AA-469 Việc 1 — "already atomized" is DERIVED (no new column/migration), same precedent
# as api/routers/admin_atoms.py's own owner_scope-agnostic atomized_at/atom_count subquery
# (that file's GET /admin/atoms/summary, ~line 271) — this is the tenant-scoped equivalent,
# scoped to owner_scope = a specific tenant_id rather than admin's platform-wide view.
# Chosen over an explicit column because it costs no migration, matches an established
# pattern in this codebase, and the source of truth (acp_contract.tour_atoms) already has
# everything needed — a column would just be a cache of this same query. NOT is_empty_marker/
# deleted rows don't count as "atomized" for the tenant-facing badge (mirrors admin_atoms.py).
_ATOMIZED_SUBQUERY = """(
    SELECT tour_id, owner_scope, MAX(created_at) AS atomized_at,
           COUNT(*) FILTER (WHERE NOT is_empty_marker AND NOT deleted) AS atom_count
    FROM acp_contract.tour_atoms
    GROUP BY tour_id, owner_scope
)"""


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

    conditions = ["pt.tenant_id = $1"]
    params = [tenant_id]

    if min_quality is not None:
        params.append(min_quality)
        conditions.append(f"pt.quality_score >= ${len(params)}")

    where = "WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        total = await conn.fetchval(f"""
            SELECT COUNT(*)
            FROM gold_aa_internal.published_tours pt
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            {where}
        """, *params)
        params_paged = params + [page_size, offset]
        rows = await conn.fetch(f"""
            SELECT pt.id, pt.tour_id, pt.aa_name, pt.aa_subtitle, pt.aa_summary,
                   pt.seo_title, pt.quality_score, pt.published_at,
                   rt.country
            FROM gold_aa_internal.published_tours pt
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            {where}
            ORDER BY pt.published_at DESC
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
    duration_min: Optional[int] = Query(None, ge=1),
    duration_max: Optional[int] = Query(None),
    sort: str = Query("newest"),
):
    """Browse AA shared pool (published_tours from aa_internal).
    All active tenants can read the pool — RLS bypassed via aa_internal filter.
    """
    tenant_id = tenant["sub"]
    pool = request.app.state.pool
    offset = (page - 1) * page_size

    # AA-441 (bug #6, AA-438-00-SUMMARY #8): was missing the master_status/deleted_at gate that
    # acp_contract.v_trip_registry already applies (migrations 078/083/090) — a tour an admin
    # trashes/deactivates in Master Content stayed fully visible and rewritable to every tenant
    # here. Same condition v_trip_registry uses: master_status='active' AND deleted_at IS NULL.
    conditions = [
        "pt.tenant_id = '00000000-0000-0000-0000-000000000001'::uuid",
        "pt.master_status = 'active'",
        "pt.deleted_at IS NULL",
    ]
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
    if duration_min is not None:
        params.append(duration_min)
        conditions.append(
            f"CAST(NULLIF(REGEXP_REPLACE(COALESCE(rt.duration,''),'[^0-9]','','g'),'') AS INTEGER) >= ${len(params)}"
        )
    if duration_max is not None:
        params.append(duration_max)
        conditions.append(
            f"CAST(NULLIF(REGEXP_REPLACE(COALESCE(rt.duration,''),'[^0-9]','','g'),'') AS INTEGER) <= ${len(params)}"
        )

    order_by = "pt.published_at DESC" if sort == "newest" else "pt.quality_score DESC, pt.published_at DESC"
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
            ORDER BY {order_by}
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
        """, *params_paged)

        # Countries for filter dropdown — same master_status/deleted_at gate as the main listing
        # above, so a trashed/deactivated tour's country doesn't show as a filterable option.
        countries = await conn.fetch("""
            SELECT DISTINCT rt.country
            FROM gold_aa_internal.published_tours pt
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE pt.tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
              AND pt.master_status = 'active'
              AND pt.deleted_at IS NULL
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
            SELECT pt.id, pt.tour_id, pt.aa_name, pt.aa_subtitle,
                   pt.aa_summary, pt.aa_description, pt.aa_highlights,
                   pt.aa_itineraries, pt.seo_title, pt.seo_meta,
                   pt.seo_keywords_used,
                   rt.country, rt.duration
            FROM gold_aa_internal.published_tours pt
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE pt.id = $1::uuid
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
        "subtitle":    pt.get("aa_subtitle") or "",
        "summary":     pt.get("aa_summary") or "",
        "description": pt.get("aa_description") or "",
        "highlights":  pt.get("aa_highlights") or "",
        "itineraries": pt.get("aa_itineraries") or "",
        "seo_title":   pt.get("seo_title") or "",    # fixed: was "aa_seo_title"
        "seo_meta":    pt.get("seo_meta") or "",     # fixed: was "aa_seo_meta"
        "country":     pt.get("country") or "",       # now from raw_tours JOIN
        "duration":    pt.get("duration") or "",      # now from raw_tours JOIN
    }

    # Fetch brand rules for this tenant
    # AA-425 fix: `br_row = await pool.acquire().__aenter__()` used to sit right before the
    # `async with pool.acquire() as _conn2` below -- it acquired a SECOND connection from the
    # pool and called __aenter__() directly without ever pairing it with __aexit__(), leaking
    # one pooled connection on every single tenant rewrite (br_row itself was never even used
    # afterward -- dead code). Pool is min_size=2/max_size=10 (api/main.py) -- found live during
    # AA-425 verification: after ~8 real rewrite calls in one session the pool was exhausted
    # enough that THIS query started timing out, silently falling into the except below
    # (brand_rules = {} minus system_prompt/style_guide/forbidden_words) -- the LLM then had no
    # brand voice guidance at all and reliably drifted into generic marketing adjectives that
    # happen to be on graph.py's own forbidden-word list, escalating every rewrite to
    # review_queue. Removed the leaked acquire; only the real query below remains.
    brand_rules = {}
    try:
        async with pool.acquire() as _conn2:
            _br = await _conn2.fetchrow("""
                SELECT system_prompt, style_guide, forbidden_words
                FROM shared.tenant_brand_rules
                WHERE tenant_id = $1::uuid AND is_active = true
                ORDER BY version DESC LIMIT 1
            """, tenant_id)
        if _br:
            # AA-425 fix (found via hash-diff forensic comparison against a direct-call harness
            # using the exact same tenant/tour): asyncpg has no jsonb codec registered on this
            # app's connections (same gap AA-314 already found/fixed elsewhere, api/routers/
            # v1_tours.py's own src_highlights handling) -- forbidden_words arrives as a raw
            # JSON-encoded STRING, not a parsed list. `list(_br["forbidden_words"] or [])` was
            # calling list() on that STRING, splitting it into individual characters
            # (['[', '"', 'l', 'u', 'x', ...]) instead of parsing it -- every tenant rewrite's
            # system prompt carried a garbled "FORBIDDEN WORDS: [, ", l, u, x, ..." instruction
            # instead of the tenant's real word list. Confirmed via SHA-256 hash comparison: the
            # user_prompt and tour_dict hashes matched byte-for-byte between this endpoint and a
            # direct _rewrite_tour() call using identical inputs, but brand_rules.forbidden_words
            # diverged at exactly this line.
            import json as _json2
            _fw_raw = _br["forbidden_words"]
            if isinstance(_fw_raw, str):
                _fw_raw = _json2.loads(_fw_raw) if _fw_raw else []
            brand_rules = {
                "system_prompt":    _br["system_prompt"] or "",
                "style_guide":      _br["style_guide"] or "",
                "forbidden_words":  list(_fw_raw or []),
                "rewrite_language": body.rewrite_language,
            }
    except Exception:
        brand_rules = {"rewrite_language": body.rewrite_language}

    # Run LLM rewrite in background (don't block response)
    async def _do_rewrite_and_save():
        # AA-445-02 — DFS mở rộng T2 (docs/claude_audit/AA-445-01-dfs-distinctiveness-step0-audit
        # .md Q2a): T1/T2 never called process_seo(), so `seo` reached the shared
        # _rewrite_tour()/validate_node graph as {} — structurally, not by a tier flag. Mirrors
        # admin_pipeline.py's A1 pattern (lines ~458-488): reuse an existing seo_context row for
        # this tour_id if one exists (free — AA-439-05 confirmed most tenant-rewritten tours were
        # originally A1-generated and already have one), else call process_seo() on a miss
        # (~$0.18/tour, AA-439-05 §7). Best-effort — a SEO fetch failure must not block the
        # rewrite itself, same as A1's own try/except around this block.
        seo_data: dict = {}
        try:
            async with pool.acquire() as _conn_seo:
                _existing = await _conn_seo.fetchrow("""
                    SELECT top_keywords, keyword_ideas, people_also_ask
                    FROM silver_aa_internal.seo_context
                    WHERE tour_id = $1::uuid
                    ORDER BY fetched_at DESC LIMIT 1
                """, pt["tour_id"])
            if _existing:
                import json as _json_seo
                _tk = _existing["top_keywords"]
                seo_data = {
                    "top_keywords": (_json_seo.loads(_tk) if isinstance(_tk, str) else _tk) or [],
                }
                seo_data["keywords"] = {"top_keywords": seo_data["top_keywords"]}
            else:
                from services.seo_intelligence.handler import process_seo
                from services.seo_intelligence.seed_builder import build_seed
                seed = build_seed(tour_dict.get("country"), None, tour_dict.get("name")) or tour_dict.get("name", "")
                if seed:
                    _seo_result = await process_seo(
                        tour_id=pt["tour_id"], destination=seed, seed=seed,
                        tenant_id=tenant_id, seo_mode="dataforseo",
                    )
                    seo_data = _seo_result.get("data", {})
                    if "keywords" in seo_data and "top_keywords" not in seo_data:
                        seo_data["top_keywords"] = seo_data["keywords"].get("top_keywords", [])
                    elif "top_keywords" in seo_data and "keywords" not in seo_data:
                        seo_data["keywords"] = {"top_keywords": seo_data["top_keywords"]}
                    seo_data.setdefault("top_keywords", [])
        except Exception as _seo_err:
            import structlog as _sl_seo
            _sl_seo.get_logger().warning("t2_seo_step_failed", tour_id=pt["tour_id"], error=str(_seo_err))

        try:
            result = await _do_rewrite(
                tour_dict, idx=0, total=1,
                brand_rules=brand_rules,
                seo=seo_data,
                is_tenant_rewrite=True,  # skips name-match check in validate_node
            )
            if result.get("status") == "success" and result.get("generated"):
                # AA-425 T3 — QA gate (grounding + structural), self-repair up to
                # TENANT_QA_MAX_REPAIRS rounds. source_texts is T2's OWN input (the
                # pre-rewrite published_tours content) — the grounding baseline a
                # tenant rewrite must not introduce new numbers/measurements beyond.
                from services.acp_produce.tenant_pipeline import run_t3_qa_gate
                source_texts = [str(v) for v in tour_dict.values() if v]
                qa = await run_t3_qa_gate(
                    tour_dict, source_texts, result, brand_rules,
                    seo_data=seo_data,  # AA-445-02 — repair-round rewrites also carry seo_data
                )
                result = qa["result"]  # possibly a later repair round's output

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
                rewrite_score = float(result.get("quality_score") or 0)
                # AA-436: status is now purely score-based, same formula for a real T3 pass
                # and an auto-pass — T3 no longer forces needs_review on its own (see
                # qa_auto_passed below for the separate signal that a QA-gate failure
                # happened). ADR-2026-038 §0.1 (amend §10.3): escalate-and-stop broke the
                # single-job T2->T3->T5 chain and made the tenant fix wording themselves —
                # both rejected 22/08.
                if rewrite_score >= 7.0:
                    new_status = "ai_generated"   # ready for tenant to review
                elif rewrite_score > 0:
                    new_status = "needs_review"   # LLM finished but low quality
                else:
                    new_status = "needs_review"   # hitl / score=0 — needs human
                # Never write 0.0 — fall back to source published_tours quality_score
                async with pool.acquire() as _conn_qs:
                    source_score = await _conn_qs.fetchval(
                        "SELECT quality_score FROM gold_aa_internal.published_tours WHERE id = $1::uuid",
                        published_tour_id
                    )
                final_score = rewrite_score if rewrite_score else float(source_score or 0)
                # qa_status keeps its migration-107 meaning unchanged (the real QA verdict,
                # 'escalated' still means the gate did NOT actually clear) — qa_auto_passed
                # (migration 109) is the new, separate tenant-facing badge flag: true means
                # this version reached the pool despite qa_status='escalated'.
                qa_status = "passed" if qa["passed"] else "escalated"
                qa_auto_passed = not qa["passed"]
                async with pool.acquire() as _conn3:
                    await _conn3.execute("""
                        UPDATE gold_aa_internal.tenant_tour_versions
                        SET rewritten_content = $1::jsonb,
                            status = $2,
                            quality_score = $3,
                            qa_status = $4,
                            qa_repair_count = $5,
                            qa_checked_at = now(),
                            qa_auto_passed = $6
                        WHERE id = $7::uuid
                    """,
                        _j3.dumps(rewritten), new_status, final_score,
                        qa_status, qa["attempts"], qa_auto_passed, version_id)
                import structlog as _sl2
                _sl2.get_logger().info("tenant_rewrite_done",
                    version_id=str(version_id), score=final_score, status=new_status,
                    qa_status=qa_status, qa_attempts=qa["attempts"],
                    qa_auto_passed=qa_auto_passed)

                if not qa["passed"]:
                    # AA-436: T3 no longer escalate-BLOCKS — still write the review_queue
                    # row exactly as AA-425 did (escalate_t3_failure() itself unchanged), so
                    # A4 (AA-437, separate issue) can see it — the tour still reaches the
                    # tenant's pool (T4) either way.
                    from services.acp_produce.tenant_pipeline import escalate_t3_failure
                    await escalate_t3_failure(
                        pool, tenant_id, pt["tour_id"], str(version_id),
                        qa["structural_issues"], qa["grounding_issues"],
                    )

                # AA-469 Việc 1: T5 (atomize) NO LONGER runs here. AA-436 had it running
                # unconditionally right after T4 (real pass or QA-auto-passed alike, no
                # gate) — T4 (this UPDATE, "save to My Catalog") is the real stopping
                # point of this background chain now. T5 is a separate, tenant-triggered
                # action: POST /v1/tours/versions/{version_id}/atomize, below — invoked
                # from My Catalog whenever the tenant is ready (immediately after this, or
                # days/weeks later). See docs/claude_audit/
                # AA-469-viec1-step0-t4-t5-split-investigation.md for the removed bug.
        except Exception as _e:
            import structlog as _sl
            _sl.get_logger().error("tenant_rewrite_failed", error=str(_e))
            # Mark as needs_review so polling detects completion even on error
            try:
                async with pool.acquire() as _conn_err:
                    await _conn_err.execute("""
                        UPDATE gold_aa_internal.tenant_tour_versions
                        SET status = 'needs_review'
                        WHERE id = $1::uuid AND status = 'pending'
                    """, version_id)
            except Exception:
                pass

    _rewrite_task = _asyncio.create_task(_do_rewrite_and_save())
    _background_tasks.add(_rewrite_task)
    _rewrite_task.add_done_callback(_background_tasks.discard)

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
                   ttv.rewritten_content, ttv.qa_auto_passed,
                   pt.id AS published_tour_id, pt.tour_id, pt.aa_name, pt.quality_score AS aa_quality,
                   rt.country, rt.duration,
                   ta.atomized_at, COALESCE(ta.atom_count, 0) AS atom_count
            FROM gold_aa_internal.tenant_tour_versions ttv
            JOIN gold_aa_internal.published_tours pt ON pt.id = ttv.published_tour_id
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            LEFT JOIN {_ATOMIZED_SUBQUERY} ta
                ON ta.tour_id = pt.tour_id AND ta.owner_scope = ttv.tenant_id::text
            {where}
            ORDER BY ttv.created_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
        """, *params_paged)

    return {
        "data": [dict(r) for r in rows],
        "pagination": {"page": page, "page_size": page_size,
                       "total": total, "pages": -(-total // page_size)},
    }


@router.get("/{tour_id}/full")
async def get_tour_full(
    tour_id: str,
    request: Request,
    x_admin_secret: Optional[str] = Header(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
):
    """Full before/after data for catalog review panel."""
    import os
    ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
    is_admin = bool(ADMIN_SECRET and x_admin_secret == ADMIN_SECRET)
    if is_admin:
        tenant_id = "00000000-0000-0000-0000-000000000001"
    elif credentials:
        try:
            payload = verify_jwt(credentials.credentials)
            tenant_id = payload["sub"]
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        pt = await conn.fetchrow("""
            SELECT * FROM gold_aa_internal.published_tours
            WHERE id = $1::uuid AND tenant_id = $2::uuid
        """, tour_id, tenant_id)
        if not pt:
            raise HTTPException(status_code=404, detail="Tour not found")

        raw = await conn.fetchrow("""
            SELECT * FROM silver_aa_internal.raw_tours
            WHERE tour_id = $1::uuid
        """, pt["tour_id"])

        gen = await conn.fetchrow("""
            SELECT * FROM silver_aa_internal.generated_content
            WHERE tour_id = $1::uuid
            ORDER BY version_num DESC LIMIT 1
        """, pt["tour_id"])

        qs = await conn.fetchrow("""
            SELECT * FROM silver_aa_internal.quality_scores
            WHERE generated_content_id = $1::uuid
            ORDER BY evaluated_at DESC LIMIT 1
        """, gen["id"] if gen else None
        ) if gen else None

        sc = await conn.fetchrow("""
            SELECT top_keywords, keyword_search, keyword_ideas, fetched_at
            FROM silver_aa_internal.seo_context
            WHERE tour_id = $1::uuid
            ORDER BY fetched_at DESC LIMIT 1
        """, pt["tour_id"])

    def safe(row):
        from uuid import UUID
        from decimal import Decimal
        if not row: return {}
        d = dict(row)
        for k, v in d.items():
            if isinstance(v, UUID):
                d[k] = str(v)
            elif isinstance(v, Decimal):
                d[k] = float(v)
            elif hasattr(v, 'isoformat'):
                d[k] = v.isoformat()
        return d

    return {
        "published": safe(pt),
        "raw": safe(raw),
        "generated": safe(gen),
        "quality": safe(qs),
        "seo": safe(sc),
    }


class TourEditRequest(_BM):
    field: str
    value: str
    approved_by: Optional[str] = "content_team"


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
        row = await conn.fetchrow(f"""
            SELECT ttv.*, pt.tour_id, pt.aa_name, pt.aa_subtitle, pt.aa_summary,
                   pt.aa_description, pt.aa_highlights, pt.aa_itineraries,
                   pt.seo_title AS aa_seo_title, pt.seo_meta AS aa_seo_meta,
                   pt.quality_score AS aa_quality_score,
                   rt.country, rt.duration, rt.price_raw,
                   ta.atomized_at, COALESCE(ta.atom_count, 0) AS atom_count
            FROM gold_aa_internal.tenant_tour_versions ttv
            JOIN gold_aa_internal.published_tours pt ON pt.id = ttv.published_tour_id
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            LEFT JOIN {_ATOMIZED_SUBQUERY} ta
                ON ta.tour_id = pt.tour_id AND ta.owner_scope = ttv.tenant_id::text
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


# ── AA-469 Việc 1 — standalone T5 (Atomize) trigger ──────────────────────────
# Decoupled from the T2->T3->T4 background chain (trigger_rewrite() above no longer
# calls run_t5_atomize() itself — see the comment left at that removed call site).
# Tenant invokes this explicitly from My Catalog whenever ready: right after T4, or
# days/weeks later. run_t5_atomize() (services/acp_produce/tenant_pipeline.py) is
# parameter-pure — STEP0 confirmed it takes `rewritten: dict` + `tour_id` + `country`
# directly and never queries the DB itself — so this endpoint is exactly the small
# adapter STEP0 flagged as still needed: reconstruct those 3 values from `version_id`
# (the only thing the tenant/frontend has to hand) since nothing previously re-read
# them back out of tenant_tour_versions.
@router.post("/versions/{version_id}/atomize")
async def atomize_version(
    version_id: str,
    request: Request,
    tenant=Depends(get_tenant),
):
    """Trigger T5 (atomize) for one already-rewritten tenant tour version.

    Idempotent, not just "handled sensibly": run_t5_atomize() itself keys its skip
    check off (tour_id, owner_scope)'s most recent source_hash — calling this twice
    on unchanged content is a no-op (`{"status": "skipped", "atom_count": 0}`), no
    duplicate atoms, no duplicate LLM call. A second call after the tenant requests
    a NEW version (different rewritten_content -> different hash) legitimately
    re-atomizes, same as it always would have.
    """
    tenant_id = tenant["sub"]
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT ttv.status, ttv.rewritten_content, pt.tour_id, rt.country
            FROM gold_aa_internal.tenant_tour_versions ttv
            JOIN gold_aa_internal.published_tours pt ON pt.id = ttv.published_tour_id
            LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE ttv.id = $1::uuid AND ttv.tenant_id = $2::uuid
        """, version_id, tenant_id)

    if not row:
        raise HTTPException(status_code=404, detail="Version not found")

    # Only a version whose rewrite actually finished can be atomized — 'pending' is
    # still generating (or died before ever writing real content, see the except
    # block in trigger_rewrite()) and 'rejected' is content the tenant asked to
    # replace. 'ai_generated'/'needs_review' (incl. qa_auto_passed=true)/'approved'
    # are all fair game — a QA-auto-passed version is the tenant's call to atomize
    # or not (STEP0's open product question), not blocked here.
    if row["status"] not in ("ai_generated", "needs_review", "approved"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot atomize a version with status '{row['status']}' — "
                "wait for the rewrite to finish, or request a new version first."
            ),
        )

    import json as _json
    rc = row["rewritten_content"]
    rewritten = (_json.loads(rc) if isinstance(rc, str) else rc) or {}
    # Defense-in-depth vs. the 'needs_review'-via-exception path (trigger_rewrite()'s
    # except block can set status='needs_review' while rewritten_content is still the
    # INITIAL placeholder, status="generating", written before T2 ever ran) — the real
    # T4 write always sets this inner status to "done".
    if rewritten.get("status") != "done":
        raise HTTPException(
            status_code=409,
            detail="This version has no completed rewrite content to atomize yet",
        )

    from services.acp_produce.tenant_pipeline import run_t5_atomize
    result = await run_t5_atomize(
        tenant_id, row["tour_id"], rewritten, pool,
        country=row["country"] or "", version_id=version_id,
    )

    # AA-509 — Segment: run right after T5, whenever it actually read/wrote anything (not on a
    # pure "skipped" no-op re-atomize — existing Segments stay correct untouched then). Placed
    # BEFORE the `status == "failed"` 502 below: a per-day run where SOME days fail still commits
    # the successful days' atoms (tenant_pipeline.py's own docstring), so Segments should still
    # pick those up. Best-effort, same pattern as escalate_t5_atomize_failure() just below — a
    # Segment rebuild failure must not hide (or block) the real T5 result from the tenant.
    if result.get("status") != "skipped":
        try:
            from services.acp_contract.segment_matching import run_segment_matching
            await run_segment_matching(tenant_id, pool)
        except Exception:
            logger.warning("t5_segment_matching_failed", tenant_id=tenant_id, exc_info=True)

        # AA-515 — ranking (research loop + rank-sum), fired in the BACKGROUND, not awaited.
        # Real DataForSEO + Bedrock calls per NEW canonical_place can run well past the ~29s
        # API Gateway timeout this repo has already documented for T8/T9 (CLAUDE.md's own
        # AA-452 LIVE STATE entry) — atomize_version()'s own response must not block on it, the
        # way T5's own atomize call already does. Strong-ref pattern (module-level
        # _background_tasks + add_done_callback) is this file's own established one (AA-425,
        # see its comment at the top of this file), same shape AA-466 also used elsewhere
        # (services/acp_content_writing/service.py::run_write_background()).
        import asyncio as _asyncio_ranking
        _ranking_task = _asyncio_ranking.create_task(_run_ranking_pipeline(tenant_id, pool))
        _background_tasks.add(_ranking_task)
        _ranking_task.add_done_callback(_background_tasks.discard)

    if result.get("status") == "failed":
        # AA-469 Việc 5 — the gap this comment used to flag ("Việc 5's future job") is closed:
        # persist the same error to silver_aa_internal.review_queue (A4's existing review-log
        # already reads this table/join key, no new endpoint needed — see
        # escalate_t5_atomize_failure()'s own docstring) BEFORE returning the 502 to the tenant.
        # Best-effort: a failure to persist the escalation must not hide the real atomize error
        # from the tenant, who still needs their own 502 either way.
        error_msg = result.get("error") or "Atomize failed"
        try:
            from services.acp_produce.tenant_pipeline import escalate_t5_atomize_failure
            await escalate_t5_atomize_failure(pool, tenant_id, row["tour_id"], version_id, error_msg)
        except Exception:
            logger.warning("t5_escalate_failed_not_persisted", version_id=version_id, exc_info=True)
        raise HTTPException(status_code=502, detail=error_msg)

    import datetime as _dt
    return {
        "version_id": version_id, "tour_id": row["tour_id"],
        # UI feedback only — the derived join (_ATOMIZED_SUBQUERY) is the source of
        # truth on next fetch; "skipped" (unchanged content) still means atoms already
        # exist from a prior call, so this is accurate either way.
        "atomized_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        **result,
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
