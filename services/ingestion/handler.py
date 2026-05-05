import boto3
import asyncio
import asyncpg
import json
import os
import tempfile
import uuid
import hashlib
import structlog

from .excel_parser import ExcelParser
from shared.repository.raw_tour_repository import RawTourRepository
from shared.repository.raw_source_repository import RawSourceRepository
from shared.secrets import get_database_url

logger = structlog.get_logger()
s3  = boto3.client("s3")
sfn = boto3.client("stepfunctions")


def compute_file_hash(file_bytes: bytes) -> str:
    """SHA256 hash of raw file — dedup key."""
    return hashlib.sha256(file_bytes).hexdigest()


async def process_file(s3_bucket: str, s3_key: str, seo_mode: str = "standard") -> dict:
    """Download Excel từ S3, parse, insert bronze.raw_sources → bronze.raw_tours."""

    # Download về /tmp
    filename = s3_key.split("/")[-1]
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        s3.download_fileobj(s3_bucket, s3_key, tmp)
        tmp_path = tmp.name

    # Read file bytes for hash computation
    with open(tmp_path, "rb") as fh:
        file_bytes = fh.read()
    file_hash = compute_file_hash(file_bytes)
    logger.info("file_downloaded", s3_key=s3_key, file_hash=file_hash[:12], seo_mode=seo_mode)

    # TD-2: Dedup check — skip if same file already processed
    conn_check = await asyncpg.connect(get_database_url())
    try:
        existing = await conn_check.fetchrow(
            "SELECT id, filename FROM silver_aa_internal.raw_sources WHERE file_hash = $1",
            file_hash,
        )
        if existing:
            logger.info(
                "dedup_skip",
                file_hash=file_hash[:12],
                existing_id=str(existing["id"]),
                existing_filename=existing["filename"],
            )
            return {
                "status": "skipped_duplicate",
                "file_hash": file_hash[:12],
                "existing_source_id": str(existing["id"]),
            }
    finally:
        await conn_check.close()

    # Parse Excel
    parser = ExcelParser(tmp_path, source_file=s3_key)
    records = parser.parse()
    logger.info("excel_parsed", total_rows=len(records))

    conn = await asyncpg.connect(get_database_url())
    tenant_slug = "aa_internal"  # Phase 1: single tenant
    tenant_uuid = "00000000-0000-0000-0000-000000000001"

    source_repo = RawSourceRepository(conn, tenant_slug)
    tour_repo   = RawTourRepository(conn, tenant_uuid)

    try:
        # 1. Insert raw_source → lấy source_id
        batch_id_new = str(uuid.uuid4())

        # Insert pipeline_runs first (raw_sources.batch_id FK → pipeline_runs)
        await conn.execute("""
            INSERT INTO shared.pipeline_runs
                (batch_id, tenant_id, s3_source_path, status, tours_total)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5)
            ON CONFLICT (batch_id) DO NOTHING
        """,
            batch_id_new,
            "00000000-0000-0000-0000-000000000001",
            s3_key,
            "ingesting",
            len(records),
        )

        # Get file size from S3 object
        try:
            s3_meta = s3.head_object(Bucket=s3_bucket, Key=s3_key)
            file_size_kb = round(s3_meta["ContentLength"] / 1024, 1)
        except Exception:
            file_size_kb = None

        source_id = await source_repo.insert({
            "tenant_id":    "00000000-0000-0000-0000-000000000001",
            "batch_id":     batch_id_new,
            "filename":     filename,
            "s3_path":      s3_key,
            "row_count":    len(records),
            "file_hash":    file_hash,
            "file_size_kb": file_size_kb,
        })
        logger.info("source_created", source_id=source_id)

        if not records:
            await source_repo.update_status(source_id, "skipped", row_count=0)
            return {"status": "skipped", "rows": 0, "source_id": str(source_id)}

        # 2. Gán source_id → insert raw_tours
        for r in records:
            r["source_id"] = source_id
            r["batch_id"] = batch_id_new

        ids = await tour_repo.insert_batch(records)
        await source_repo.update_status(source_id, "done", row_count=len(ids))
        logger.info("inserted", count=len(ids), source_id=source_id)

        # 3. Trigger Step Functions pipeline (S11 Phase 4)
        batch_id = batch_id_new
        sfn_arn  = os.environ.get("STEP_FUNCTIONS_ARN")

        if sfn_arn:
            _start_pipeline(
                sfn_arn=sfn_arn,
                batch_id=batch_id,
                tour_ids=[str(i) for i in ids],
                tenant_id=tenant_slug,
                s3_key=s3_key,
                seo_mode=seo_mode,
            )
        else:
            logger.warning("sfn_not_configured", msg="STEP_FUNCTIONS_ARN not set — skipping pipeline trigger")

        return {
            "status":    "done",
            "rows":      len(ids),
            "source_id": batch_id,
            "sfn_triggered": bool(sfn_arn),
        }

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


def _start_pipeline(
    sfn_arn: str,
    batch_id: str,
    tour_ids: list[str],
    tenant_id: str,
    s3_key: str,
    seo_mode: str = "standard",
) -> None:
    """
    Start Step Functions execution with per-tour input.

    Step Functions Map state expects $.tours = list of tour objects.
    Each tour object: {tour_id, batch_id, tenant_id, retry_count, validation_feedback}
    """
    tours_input = [
        {
            "tour_id":             tid,
            "batch_id":            batch_id,
            "tenant_id":           tenant_id,
            "retry_count":         0,
            "validation_feedback": [],
            "seo_mode":            seo_mode,
        }
        for tid in tour_ids
    ]

    execution_name = f"batch-{batch_id[:8]}-{uuid.uuid4().hex[:8]}"

    payload = {
        "batch_id":  batch_id,
        "s3_key":    s3_key,
        "tenant_id": tenant_id,
        "seo_mode":  seo_mode,
        "tours":     tours_input,
    }

    response = sfn.start_execution(
        stateMachineArn=sfn_arn,
        name=execution_name,
        input=json.dumps(payload),
    )

    logger.info(
        "sfn_started",
        execution_arn=response["executionArn"],
        batch_id=batch_id,
        tour_count=len(tour_ids),
    )


def lambda_handler(event: dict, context) -> dict:
    """AWS Lambda entry point — triggered by S3 PutObject on Bronze bucket raw-inbox/."""
    records = event.get("Records", [])
    results = []

    for record in records:
        s3_bucket = record["s3"]["bucket"]["name"]
        s3_key    = record["s3"]["object"]["key"]

        if not s3_key.startswith("raw-inbox/"):
            logger.info("skipped_non_inbox", s3_key=s3_key)
            continue

        if not s3_key.endswith((".xlsx", ".xls")):
            logger.info("skipped_non_excel", s3_key=s3_key)
            continue

        logger.info("processing", s3_bucket=s3_bucket, s3_key=s3_key)

        try:
            # Read seo_mode from S3 object metadata (set by upload-url endpoint)
            seo_mode = "standard"
            try:
                meta = s3.head_object(Bucket=s3_bucket, Key=s3_key)
                seo_mode = meta.get("Metadata", {}).get("seo-mode", "standard")
            except Exception:
                pass
            result = asyncio.run(process_file(s3_bucket, s3_key, seo_mode=seo_mode))
            results.append({"s3_key": s3_key, **result})
        except Exception as e:
            logger.error("lambda_record_failed", s3_key=s3_key, error=str(e))
            results.append({"s3_key": s3_key, "status": "failed", "error": str(e)})

    return {"processed": len(results), "results": results}
