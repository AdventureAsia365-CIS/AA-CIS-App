import asyncio
import asyncpg
import json
import os
import structlog
from shared.validators.rules import validate_content

logger = structlog.get_logger()

async def process_validation(version_id: str) -> dict:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    tenant_slug = os.environ.get("TENANT_SLUG", "aa_internal")
    try:
        row = await conn.fetchrow(
            f"SELECT * FROM silver_{tenant_slug}.generated_content WHERE id = $1::uuid",
            version_id
        )
        if not row:
            raise ValueError(f"Version not found: {version_id}")

        content = {
            "name":       row["aa_name"],
            "subtitle":   row["aa_subtitle"],
            "summary":    row["aa_summary"],
            "highlights": row["aa_highlights"] or [],
            "seo_title":  row["seo_title"],
            "seo_meta":   row["seo_meta"],
            "trip_type":  "cultural",
        }

        result = validate_content(content)
        score  = result["score"]

        retry_count = row.get("retry_count", 0) or 0
        if score >= 7.0:
            new_status = "approved"
            route      = "export"
        elif retry_count < 2:
            new_status = "pending"
            route      = "regenerate"
        else:
            new_status = "pending"
            route      = "hitl"

        await conn.execute(f"""
            UPDATE silver_{tenant_slug}.generated_content
            SET status = $2::content_status_enum
            WHERE id = $1::uuid
        """,
            version_id,
            new_status,
        )

        logger.info("validation_complete",
                    version_id=version_id, score=score, route=route)

        return {
            "version_id":   version_id,
            "score":        score,
            "route":        route,
            "failed_rules": result["issues"],
        }
    finally:
        await conn.close()


def lambda_handler(event: dict, context) -> dict:
    # Pattern 1: SF direct invoke — version_id inside content_result.Payload
    if "content_result" in event:
        payload = event["content_result"].get("Payload", {})
        version_id = payload.get("version_id")
        if not version_id:
            logger.warning("no_version_id_in_content_result", keys=str(event.keys()))
            return {"processed": 0, "error": "missing version_id"}
        try:
            result = asyncio.run(process_validation(version_id))
            return result
        except Exception as e:
            logger.error("validation_failed", error=str(e))
            return {"status": "failed", "error": str(e)}

    # Pattern 2: SQS trigger (Phase 2)
    elif "Records" in event:
        results = []
        for record in event["Records"]:
            try:
                body       = json.loads(record["body"])
                version_id = body.get("version_id")
                if not version_id:
                    logger.warning("missing_version_id")
                    continue
                result = asyncio.run(process_validation(version_id))
                results.append(result)
            except Exception as e:
                logger.error("validation_failed", error=str(e))
                results.append({"status": "failed", "error": str(e)})
        return {"processed": len(results), "results": results}

    else:
        logger.warning("unknown_event_format", keys=str(event.keys()))
        return {"processed": 0, "error": "unknown event format"}
