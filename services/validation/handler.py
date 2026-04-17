import asyncio
import asyncpg
import boto3
import json
import os
import structlog

from shared.validators.rules import validate_content

logger = structlog.get_logger()
sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-west-1"))

async def process_validation(version_id: str) -> dict:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        row = await conn.fetchrow(
            "SELECT * FROM silver.published_tour_versions WHERE id = $1", version_id
        )
        if not row:
            raise ValueError(f"Version not found: {version_id}")

        content = {
            "name":       row["name"],
            "subtitle":   row["subtitle"],
            "summary":    row["summary"],
            "highlights": row["highlights"] or [],
            "seo_title":  row["seo_title"],
            "seo_meta":   row["seo_meta"],
            "trip_type":  row["trip_type"],
        }

        result = validate_content(content)
        score  = result["score"]

        # Determine hitl_status
        retry_count  = row.get("retry_count", 0) or 0
        if score >= 7.0:
            hitl_status   = "approved"
            publish_ready = True
            route         = "export"
        elif retry_count < 2:
            hitl_status   = "revision_requested"
            publish_ready = False
            route         = "regenerate"
        else:
            hitl_status   = "pending"
            publish_ready = False
            route         = "hitl"

        # Update DB
        await conn.execute("""
            UPDATE silver.published_tour_versions SET
                audit_status        = $2,
                audit_failure_codes = $3,
                audit_issues        = $4,
                quality_score       = $5,
                publish_ready       = $6,
                hitl_status         = $7,
                updated_at          = NOW()
            WHERE id = $1
        """,
            version_id,
            result["audit_status"],
            result["issues"][:5],   # top 5 failure codes
            "; ".join(result["issues"]),
            score,
            publish_ready,
            hitl_status,
        )

        logger.info("validation_complete",
                    version_id=version_id, score=score,
                    route=route, failed=result["failed"])

        return {
            "version_id":   version_id,
            "score":        score,
            "audit_status": result["audit_status"],
            "route":        route,
            "issues":       result["issues"],
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

            result = asyncio.run(process_validation(version_id))
            results.append(result)

        except Exception as e:
            logger.error("validation_failed", error=str(e))
            results.append({"status": "failed", "error": str(e)})

    return {"processed": len(results), "results": results}
