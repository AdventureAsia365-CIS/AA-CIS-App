import asyncio
import asyncpg
import json
import os
import structlog
from shared.secrets import get_database_url
from shared.repository.published_catalog_repository import PublishedCatalogRepository

logger = structlog.get_logger()


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
            "aa_highlights":        json.dumps(row.get("aa_highlights") or []),
            "aa_itineraries":       row.get("aa_itineraries"),
            "mobile_card_text":     row.get("mobile_card_text"),
            "seo_title":            row.get("seo_title"),
            "seo_meta":             row.get("seo_meta"),
            "seo_keywords_used": json.dumps(row.get("seo_keywords_used") or []),
            "og_tags":              json.dumps(row.get("og_tags") or {}),
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

        # 4. Update tours_passed to exact published count (always, not just at end)
        if batch_id:
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
                  AND pipeline_status != 'published'
            """, batch_id)

            if pending == 0:
                await conn.execute("""
                    UPDATE shared.pipeline_runs
                    SET status = 'completed', completed_at = NOW()
                    WHERE batch_id = $1::uuid AND status = 'ingesting'
                """, batch_id)
                logger.info("batch_completed", batch_id=str(batch_id))

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
