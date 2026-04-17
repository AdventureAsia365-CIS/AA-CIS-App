import boto3
import asyncio
import asyncpg
import os
import tempfile
import structlog

from .excel_parser import ExcelParser
from shared.repository.raw_tour_repository import RawTourRepository

logger = structlog.get_logger()
s3 = boto3.client("s3")

async def process_file(s3_bucket: str, s3_key: str, source_id: str):
    """Download Excel từ S3, parse, insert vào bronze.raw_tours."""

    # Download file về /tmp
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        s3.download_fileobj(s3_bucket, s3_key, tmp)
        tmp_path = tmp.name

    logger.info("file_downloaded", s3_key=s3_key, tmp_path=tmp_path)

    # Parse Excel
    parser = ExcelParser(tmp_path, source_file=s3_key)
    records = parser.parse()
    logger.info("excel_parsed", total_rows=len(records))

    if not records:
        logger.warning("no_valid_rows", s3_key=s3_key)
        return {"status": "skipped", "rows": 0}

    # Gán source_id cho tất cả records
    for r in records:
        r["source_id"] = source_id

    # Insert vào DB
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        repo = RawTourRepository(conn)
        ids = await repo.insert_batch(records)
        logger.info("inserted", count=len(ids), source_id=source_id)
        return {"status": "done", "rows": len(ids), "ids": ids}
    finally:
        await conn.close()

def lambda_handler(event: dict, context) -> dict:
    """AWS Lambda entry point — triggered by S3 upload."""
    records = event.get("Records", [])
    results = []

    for record in records:
        s3_bucket = record["s3"]["bucket"]["name"]
        s3_key = record["s3"]["object"]["key"]

        # Chỉ xử lý file trong raw-inbox/
        if not s3_key.startswith("raw-inbox/"):
            logger.info("skipped_non_inbox", s3_key=s3_key)
            continue

        if not s3_key.endswith((".xlsx", ".xls")):
            logger.info("skipped_non_excel", s3_key=s3_key)
            continue

        logger.info("processing", s3_bucket=s3_bucket, s3_key=s3_key)

        # source_id sẽ được tạo khi insert raw_sources (TODO S1 step 2)
        source_id = None
        result = asyncio.run(process_file(s3_bucket, s3_key, source_id))
        results.append({"s3_key": s3_key, **result})

    return {"processed": len(results), "results": results}
