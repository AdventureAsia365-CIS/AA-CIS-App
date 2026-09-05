import asyncio
import asyncpg
import json
import os
import structlog
from shared.secrets import get_database_url
from shared.repository.published_catalog_repository import PublishedCatalogRepository

logger = structlog.get_logger()

# AA-526 — strong refs for the A3-triggered atomize background task, same GC-safety pattern
# api/routers/v1_tours.py::trigger_rewrite() / v1_content_writing.py::write() already use — a
# bare asyncio.create_task() with no reference can be garbage-collected mid-flight. Module-level
# here (not per-call) for the same reason those 2 call sites keep theirs at module level.
_background_tasks: set = set()


class _SingleConnAsPool:
    """AA-526 — process_export() (and this class's other user, _run_a3_atomize_background()
    below) each own exactly ONE asyncpg.Connection, Lambda-handler style — no asyncpg.Pool in
    scope the way every other real caller of services.acp_produce.tenant_pipeline.run_t5_atomize()
    has (T5's tenant-facing endpoint, api/routers/v1_tours.py, always runs inside a FastAPI
    request with request.app.state.pool). run_t5_atomize()/atom_extraction.py are reused
    UNCHANGED (AA-526's own instruction) rather than reworked to accept a bare Connection — this
    thin adapter exposes the one `.acquire()` async-context-manager shape they call, yielding the
    SAME connection every time. Safe here specifically because every real call path into
    run_t5_atomize() (_atomize_whole_tour_legacy/_atomize_per_day) acquires-and-releases
    sequentially, never concurrently (that module's own docstring: "Days are read SEQUENTIALLY,
    not concurrently") — a real pool with >1 physical connection is never required."""

    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


async def _run_a3_atomize_background(tour_id: str, rewritten: dict, country: str, version_id: str) -> None:
    """AA-526 — the actual A3 atomize call, launched fire-and-forget from process_export() so a
    slow multi-day LLM atomize run (services.acp_produce.tenant_pipeline.run_t5_atomize(), up to
    one invoke_claude() call per itinerary day) never adds latency to — or risks an API Gateway
    504 on — the admin action that triggers publish (api/routers/admin_pipeline.py /
    v1_pipeline.py, both `await process_export(...)` directly in their own request handler).
    Opens its OWN connection (process_export()'s own `conn` is closed in its `finally` block
    before this task would otherwise still be running) — completely independent lifecycle,
    mirroring how services/acp_content_writing/service.py::run_write_background() is launched
    with its own already-open pool rather than reusing the request's.

    owner_scope="platform" (not a tenant UUID) — atoms produced here are a shared backend
    resource, per AA-525/526's architecture decision (Nghiệp, 04/09/2026): tenants never create
    or see atoms directly anymore, curation moves to AA-admin (AA-527)."""
    conn = await asyncpg.connect(get_database_url(), ssl="require")
    try:
        from services.acp_produce.tenant_pipeline import run_t5_atomize
        pool = _SingleConnAsPool(conn)
        result = await run_t5_atomize(
            "platform", tour_id, rewritten, pool,
            country=country, version_id=version_id,
        )
        logger.info("a3_atomize_done", tour_id=tour_id, result=result)

        # AA-526 — Segment-matching is DELIBERATELY NOT run here. STEP0 initially assumed (per
        # the issue's own text) that it was purely owner_scope-agnostic and safe to run once,
        # globally, right after atomize — checking the actual schema disproved that:
        # acp_contract.atom_segment.tenant_id is `UUID NOT NULL REFERENCES shared.tenants
        # (tenant_id)` (migration 129), a REAL FK — calling run_segment_matching("platform", ...)
        # would fail that FK/UUID cast outright, and even if it didn't, services/acp_contract/
        # atom_ranking.py::run_atom_ranking() reads Segments scoped `WHERE asg.tenant_id =
        # $1::uuid` for the CALLING tenant specifically — a Segment row tagged "platform" would
        # be invisible to every real tenant's own ranking read regardless. Confirmed with Nghiệp
        # (05/09/2026): atoms are shared platform-wide, but Segment/Route/Subject stay
        # PER-TENANT products built from them once a tenant actually picks/rewrites a tour — not
        # a single global Segment set. See docs/implementation-notes/AA-526.md for the full
        # finding and where Segment-matching's real trigger point ended up instead.
    except Exception as exc:
        # Best-effort, same precedent as this file's own ACP-S1 manifest fanout (process_export()
        # below) — atomize failing must never be mistaken for the publish itself having failed;
        # A3 (gold_aa_internal.published_tours + pipeline_status='published') is already committed
        # by the time this task is launched.
        logger.error("a3_atomize_failed", tour_id=tour_id, error=str(exc))
    finally:
        await conn.close()

# AA-476: terminal raw_tours.pipeline_status values that mean "this tour will never publish,
# stop waiting on it" — anything else is still in flight. Before this fix the completion check
# only recognized 'published', so a rejected/failed tour (which never got any pipeline_status
# update at all — see mark_tour_rejected below) kept its batch's pipeline_runs.status stuck at
# 'ingesting' forever even after every other tour in the batch finished.
_TERMINAL_TOUR_STATUSES = ("published", "hitl_rejected", "failed")


async def sync_batch_completion(conn, batch_id, silver: str = "silver_aa_internal") -> tuple[int, bool]:
    """Recompute tours_passed + flip pipeline_runs.status to 'completed' once every tour in
    the batch has reached a terminal outcome. Returns (pending_count, just_completed).
    Shared by process_export() (tour → published) and mark_tour_rejected() (tour → rejected) —
    this is the ONE place pipeline_runs.status ever advances, deliberately not duplicated.

    AA-483: the status flip used to be a separate SELECT COUNT(*) (this function) followed by a
    conditional UPDATE gated on that count in Python — two round-trips with a gap between them,
    no lock. Now a SINGLE atomic UPDATE ... WHERE NOT EXISTS(...) does the check-and-flip in one
    statement: Postgres evaluates the WHERE clause (including the NOT EXISTS subquery) and
    performs the UPDATE under one MVCC snapshot with the target row locked, so two concurrent
    callers for the same batch can no longer both read "still pending" moments before the other
    commits the tour that would have made it complete — whichever call's UPDATE actually runs
    second re-evaluates WHERE against the first one's already-committed result and correctly
    no-ops. `just_completed` (True only for whichever single call's UPDATE actually matched a
    row) is now the sole trigger for process_export()'s one-time ACP-S1 manifest/EventBridge
    fanout — using the old `pending == 0` read for that decision had the identical race (two
    concurrent calls could each independently observe pending == 0 and both fire the fanout);
    `pending` itself is kept only as an informational/logging count, no longer a completion
    signal for any caller."""
    await conn.execute("""
        UPDATE shared.pipeline_runs
        SET tours_passed = (
            SELECT COUNT(*) FROM silver_aa_internal.raw_tours
            WHERE batch_id = $1::uuid AND pipeline_status = 'published'
        )
        WHERE batch_id = $1::uuid
    """, batch_id)

    pending = await conn.fetchval(f"""
        SELECT COUNT(*) FROM {silver}.raw_tours
        WHERE batch_id = $1::uuid
          AND pipeline_status NOT IN {_TERMINAL_TOUR_STATUSES}
    """, batch_id)

    flipped = await conn.fetchval(f"""
        UPDATE shared.pipeline_runs
        SET status = 'completed', completed_at = NOW()
        WHERE batch_id = $1::uuid
          AND status = 'ingesting'
          AND NOT EXISTS (
              SELECT 1 FROM {silver}.raw_tours
              WHERE batch_id = $1::uuid
                AND pipeline_status NOT IN {_TERMINAL_TOUR_STATUSES}
          )
        RETURNING 1
    """, batch_id)
    just_completed = flipped is not None

    if just_completed:
        logger.info("batch_completed", batch_id=str(batch_id))

    return pending, just_completed


async def mark_tour_rejected(conn, tour_id: str) -> None:
    """AA-476: reject_review() (api/routers/v1_pipeline.py) used to only flip
    review_queue.review_status + generated_content.status — raw_tours.pipeline_status was
    never touched, so a rejected tour stayed 'ingested' indefinitely and sync_batch_completion
    counted it as still-pending forever, even once every other tour in the batch was done."""
    row = await conn.fetchrow("""
        UPDATE silver_aa_internal.raw_tours
        SET pipeline_status = 'hitl_rejected'
        WHERE tour_id = $1::uuid
        RETURNING batch_id
    """, tour_id)
    if row and row["batch_id"]:
        await sync_batch_completion(conn, row["batch_id"])


async def process_export(version_id: str) -> dict:
    conn = await asyncpg.connect(get_database_url())
    tenant_slug = os.environ.get("TENANT_SLUG", "aa_internal")
    silver = f"silver_{tenant_slug}"
    try:
        # 1. Fetch generated content + tour info
        row = await conn.fetchrow(f"""
            SELECT gc.*, rt.country, rt.duration, rt.batch_id,
                   qs.id            AS quality_score_id,
                   qs.score_overall AS quality_score
            FROM {silver}.generated_content gc
            JOIN {silver}.raw_tours rt ON rt.tour_id = gc.tour_id
            LEFT JOIN {silver}.quality_scores qs ON qs.generated_content_id = gc.id
            WHERE gc.id = $1::uuid
              AND gc.status = 'approved'
        """, version_id)

        if not row:
            raise ValueError(f"Version not approved or not found: {version_id}")

        row = dict(row)
        batch_id = row["batch_id"]
        tour_id = row["tour_id"]

        # 2. Insert into published catalog (gold)
        repo = PublishedCatalogRepository(conn, tenant_slug)
        catalog_id = await repo.insert({
            "tour_id":              tour_id,
            "generated_content_id": row["id"],
            "tenant_id":            row["tenant_id"],
            "aa_name":              row.get("aa_name"),
            "aa_subtitle":          row.get("aa_subtitle"),
            "aa_summary":           row.get("aa_summary"),
            "aa_description":       row.get("aa_description"),
            # AA-314: gc.aa_highlights/seo_keywords_used/og_tags come back from asyncpg as
            # already-JSON-encoded str (no jsonb codec registered anywhere in this app — see
            # AA-293/AA-314 audit). json.dumps()'ing them again here double-encoded all three
            # columns for every export (47/48 published_tours rows, confirmed live). Pass the
            # existing JSON string straight through — PublishedCatalogRepository.insert() does
            # not re-serialize either, it hands the value to asyncpg's default jsonb codec as-is.
            "aa_highlights":        row.get("aa_highlights") or "[]",
            "aa_itineraries":       row.get("aa_itineraries"),
            "mobile_card_text":     row.get("mobile_card_text"),
            "seo_title":            row.get("seo_title"),
            "seo_meta":             row.get("seo_meta"),
            "seo_keywords_used":    row.get("seo_keywords_used") or "[]",
            "og_tags":              row.get("og_tags") or "{}",
            "quality_score":        row.get("quality_score"),
            "quality_score_id": (
                str(row["quality_score_id"]) if row.get("quality_score_id") else None
            ),
            "s3_gold_path":         None,
            "approved_by":          "pipeline",
        })
        logger.info("export_done", catalog_id=catalog_id, version_id=version_id)

        # 3. Mark tour as exported
        await conn.execute(f"""
            UPDATE {silver}.raw_tours
            SET pipeline_status = 'published'
            WHERE tour_id = $1::uuid
        """, tour_id)

        # 3b. AA-526 — this tour has now genuinely entered A3 (Master Content Pool, real QA
        # already passed via the gate at the top of this function, gc.status = 'approved') — the
        # correct, deliberate trigger point for atomize per the 04/09/2026 architecture decision
        # (was previously tied to tenant-rewritten-tour content, api/routers/v1_tours.py's now-
        # removed atomize_version() endpoint; see docs/implementation-notes/AA-526.md). Launched
        # fire-and-forget (own connection, own lifecycle — see _run_a3_atomize_background()'s own
        # docstring for why) so a slow multi-day atomize run never adds latency to this function's
        # own caller (an admin approve/publish action, awaited synchronously).
        _atomize_task = asyncio.create_task(_run_a3_atomize_background(
            tour_id=str(tour_id),
            rewritten={
                "name": row.get("aa_name"), "summary": row.get("aa_summary"),
                "highlights": row.get("aa_highlights"), "itineraries": row.get("aa_itineraries"),
            },
            country=row.get("country") or "",
            version_id=str(row["id"]),  # generated_content.id — this tour's real content version
        ))
        _background_tasks.add(_atomize_task)
        _atomize_task.add_done_callback(_background_tasks.discard)

        # 4. Update tours_passed to exact published count (always, not just at end)
        if batch_id:
            _pending, just_completed = await sync_batch_completion(conn, batch_id, silver)

            # AA-483: just_completed (the atomic UPDATE's own result), not a separately-read
            # pending count — see sync_batch_completion()'s docstring for why the old
            # `pending == 0` check here could double-fire this fanout under real concurrency.
            if just_completed:
                # ACP-S1: manifest.json + EventBridge on batch completion
                try:
                    from services.acp.handler import upload_manifest, publish_s1_completed
                    from api.services.run_context_db import write_run_context_stage
                    from collections import Counter

                    tour_rows = await conn.fetch("""
                        SELECT pt.tour_id, pt.aa_name, pt.quality_score, rt.country,
                               pt.seo_keywords_used
                        FROM gold_aa_internal.published_tours pt
                        JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
                        WHERE rt.batch_id = $1::uuid
                    """, batch_id)

                    country_counts = Counter(r["country"] for r in tour_rows if r["country"])
                    country = country_counts.most_common(1)[0][0] if country_counts else "unknown"

                    tour_list = [
                        {
                            "tour_id":       str(r["tour_id"]),
                            "aa_name":       r["aa_name"],
                            "quality_score": float(r["quality_score"] or 0),
                            "country":       r["country"],
                        }
                        for r in tour_rows
                    ]
                    tc = len(tour_list)
                    qs_avg = sum(t["quality_score"] for t in tour_list) / tc if tc else 0.0

                    tenant_row = await conn.fetchrow(
                        "SELECT tenant_id FROM shared.pipeline_runs WHERE batch_id = $1::uuid",
                        batch_id,
                    )
                    tenant_id_str = (
                        str(tenant_row["tenant_id"]) if tenant_row
                        else "00000000-0000-0000-0000-000000000001"
                    )
                    run_id = str(batch_id)

                    manifest_key = upload_manifest(
                        run_id, country, tenant_id_str, tour_list, qs_avg
                    )

                    # Deduplicate keywords used across all tours in this batch.
                    # Elements may be plain strings or dicts with "keyword" key.
                    all_kws: list = []
                    seen_kws: set = set()
                    for r in tour_rows:
                        raw = r["seo_keywords_used"]
                        if isinstance(raw, str):
                            try:
                                raw = json.loads(raw)
                            except (ValueError, TypeError):
                                raw = []
                        for item in (raw or []):
                            kw = item.get("keyword") if isinstance(item, dict) else str(item)
                            if kw and kw not in seen_kws:
                                seen_kws.add(kw)
                                all_kws.append(kw)

                    # Write acp_runs + acp_run_context atomically.
                    # publish_s1_completed is called ONLY after successful commit.
                    async with conn.transaction():
                        await conn.execute("""
                            INSERT INTO shared.acp_runs
                                (batch_id, country, tenant_id, manifest_s3_key,
                                 tour_count, quality_score_avg, status, completed_at)
                            VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6, 's1_done', NOW())
                            ON CONFLICT (batch_id) DO UPDATE SET
                                status            = 's1_done',
                                manifest_s3_key   = EXCLUDED.manifest_s3_key,
                                tour_count        = EXCLUDED.tour_count,
                                quality_score_avg = EXCLUDED.quality_score_avg,
                                completed_at      = NOW()
                        """, batch_id, country, tenant_id_str, manifest_key, tc, round(qs_avg, 2))

                        tour_ids = [str(r["tour_id"]) for r in tour_rows]
                        await write_run_context_stage(conn, run_id, "s1", {
                            "s1_keywords_used": all_kws,
                            "s1_tour_ids": tour_ids,
                        })

                    publish_s1_completed(run_id, country, tenant_id_str, manifest_key, tc, qs_avg)

                except Exception as _acp_err:
                    logger.error("acp_s1_publish_failed",
                                 batch_id=str(batch_id), error=str(_acp_err))

        return {
            "status":     "exported",
            "catalog_id": catalog_id,
            "version_id": version_id,
        }
    finally:
        await conn.close()


def lambda_handler(event: dict, context) -> dict:
    # Pattern 1: SF direct invoke — version_id inside validation_result.Payload
    if "validation_result" in event:
        payload = event["validation_result"].get("Payload", {})
        version_id = payload.get("version_id")
        if not version_id:
            logger.warning("no_version_id_in_validation_result", keys=str(event.keys()))
            return {"status": "failed", "error": "missing version_id"}
        try:
            result = asyncio.run(process_export(version_id))
            return result
        except Exception as e:
            logger.error("export_failed", error=str(e))
            return {"status": "failed", "error": str(e)}

    # Pattern 2: SQS trigger (Phase 2)
    elif "Records" in event:
        results = []
        for record in event["Records"]:
            try:
                body = json.loads(record["body"])
                version_id = body.get("version_id")
                if not version_id:
                    logger.warning("missing_version_id")
                    continue
                result = asyncio.run(process_export(version_id))
                results.append(result)
            except Exception as e:
                logger.error("export_failed", error=str(e))
                results.append({"status": "failed", "error": str(e)})
        return {"processed": len(results), "results": results}

    else:
        logger.warning("unknown_event_format", keys=str(event.keys()))
        return {"status": "failed", "error": "unknown event format"}
