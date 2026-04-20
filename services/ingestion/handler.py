import boto3
import asyncio
import asyncpg
import os
import tempfile
import structlog

from .excel_parser import ExcelParser
from shared.repository.raw_tour_repository import RawTourRepository
from shared.repository.raw_source_repository import RawSourceRepository

logger = structlog.get_logger()
s3 = boto3.client("s3")

async def process_file(s3_bucket: str, s3_key: str):
    """Download Excel từ S3, parse, insert bronze.raw_sources → bronze.raw_tours."""

    # Download về /tmp
    filename = s3_key.split("/")[-1]
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        s3.download_fileobj(s3_bucket, s3_key, tmp)
        tmp_path = tmp.name

    logger.info("file_downloaded", s3_key=s3_key)

    # Parse Excel
    parser = ExcelParser(tmp_path, source_file=s3_key)
    records = parser.parse()
    logger.info("excel_parsed", total_rows=len(records))

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    tenant_slug = "aa_internal"  # Phase 1: single tenant
    source_repo = RawSourceRepository(conn, tenant_slug)
    tour_repo = RawTourRepository(conn, tenant_slug)

    try:
        # 1. Insert raw_source → lấy source_id
        source_id = await source_repo.insert({
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
            "original_filename": filename,
            "supplier_name": _extract_supplier(s3_key),
            "row_count": len(records),
            "status": "processing",
        })
        logger.info("source_created", source_id=source_id)

        if not records:
            await source_repo.update_status(source_id, "skipped", row_count=0)
            return {"status": "skipped", "rows": 0, "source_id": source_id}

        # 2. Gán source_id → insert raw_tours
        for r in records:
            r["source_id"] = source_id

        ids = await tour_repo.insert_batch(records)
        await source_repo.update_status(source_id, "done", row_count=len(ids))
        logger.info("inserted", count=len(ids), source_id=source_id)

        return {"status": "done", "rows": len(ids), "source_id": source_id}

    except Exception as e:
        if "source_id" in dir():
            await source_repo.update_status(source_id, "failed", error=str(e))
        logger.error("processing_failed", error=str(e))
        raise
    finally:
        await conn.close()

def _extract_supplier(s3_key: str) -> str | None:
    """Extract supplier name từ path: raw-inbox/SupplierName/file.xlsx."""
    parts = s3_key.split("/")
    return parts[1] if len(parts) >= 3 else None

def lambda_handler(event: dict, context) -> dict:
    """AWS Lambda entry point — triggered by S3 upload."""
    records = event.get("Records", [])
    results = []

    for record in records:
        s3_bucket = record["s3"]["bucket"]["name"]
        s3_key = record["s3"]["object"]["key"]

        if not s3_key.startswith("raw-inbox/"):
            logger.info("skipped_non_inbox", s3_key=s3_key)
            continue

        if not s3_key.endswith((".xlsx", ".xls")):
            logger.info("skipped_non_excel", s3_key=s3_key)
            continue

        logger.info("processing", s3_bucket=s3_bucket, s3_key=s3_key)

        try:
            result = asyncio.run(process_file(s3_bucket, s3_key))
            results.append({"s3_key": s3_key, **result})
        except Exception as e:
            results.append({"s3_key": s3_key, "status": "failed", "error": str(e)})

    return {"processed": len(results), "results": results}
