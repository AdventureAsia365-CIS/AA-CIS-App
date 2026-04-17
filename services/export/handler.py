import asyncio
import asyncpg
import json
import os
import structlog

from shared.repository.published_catalog_repository import PublishedCatalogRepository

logger = structlog.get_logger()

async def process_export(version_id: str) -> dict:
    """
    Copy approved silver.published_tour_versions → gold.published_catalog
    """
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        # Fetch approved version
        row = await conn.fetchrow("""
            SELECT ptv.*, rt.country, rt.duration
            FROM silver.published_tour_versions ptv
            JOIN bronze.raw_tours rt ON rt.id = ptv.raw_tour_id
            WHERE ptv.id = $1
              AND ptv.hitl_status = 'approved'
              AND ptv.publish_ready = TRUE
        """, version_id)

        if not row:
            raise ValueError(f"Version not approved or not found: {version_id}")

        row = dict(row)

        # Generate slug
        slug = PublishedCatalogRepository.generate_slug(
            row.get("name", ""), row.get("country")
        )

        # Upsert into gold.published_catalog
        repo = PublishedCatalogRepository(conn)
        catalog_id = await repo.upsert({
            "published_version_id": str(row["id"]),
            "raw_tour_id":          str(row["raw_tour_id"]),
            "name":                 row.get("name"),
            "subtitle":             row.get("subtitle"),
            "country":              row.get("country"),
            "trip_type":            row.get("trip_type"),
            "duration":             row.get("duration"),
            "seo_title":            row.get("seo_title"),
            "seo_meta":             row.get("seo_meta"),
            "quality_score":        row.get("quality_score"),
            "status":               "draft",
            "slug":                 slug,
            "published_by":         "pipeline",
        })

        logger.info("export_done", catalog_id=catalog_id, slug=slug,
                    version_id=version_id)

        return {
            "status":     "exported",
            "catalog_id": catalog_id,
            "slug":       slug,
            "version_id": version_id,
        }

    finally:
        await conn.close()

def lambda_handler(event: dict, context) -> dict:
    results = []
    for record in event.get("Records", []):
        try:
            body       = json.loads(record["body"])
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
