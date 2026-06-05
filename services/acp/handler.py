"""
ACP S1 integration: manifest.json upload + EventBridge publish.
Called by export handler when a batch completes.
"""
import asyncio
import json
import os
import structlog
from services.acp_shared.event_constants import ACPEventSource, ACPEventDetailType
from datetime import datetime, timezone

logger = structlog.get_logger()

EVENTBRIDGE_BUS = os.environ.get("ACP_EVENTBRIDGE_BUS", "aa-cis-dev-acp-events")
ACP_GOLD_BUCKET = os.environ.get("ACP_GOLD_BUCKET", "acp-gold-867490540162")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-1")


def upload_manifest(
    run_id: str,
    country: str,
    tenant_id: str,
    tours: list,
    quality_score_avg: float,
) -> str:
    """Upload manifest.json to ACP Gold S3. Returns s3_key."""
    import boto3
    s3_key = f"aa-internal/{country}/{run_id}/s1/manifest.json"
    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "country": country,
        "tenant_id": tenant_id,
        "stage": "s1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "tour_count": len(tours),
            "quality_score_avg": round(quality_score_avg, 2),
        },
        "tours": tours,
    }
    s3 = boto3.client("s3", region_name=AWS_REGION)
    s3.put_object(
        Bucket=ACP_GOLD_BUCKET,
        Key=s3_key,
        Body=json.dumps(manifest, indent=2),
        ContentType="application/json",
    )
    logger.info("manifest_uploaded", s3_key=s3_key, tour_count=len(tours))
    return s3_key


def publish_s1_completed(
    run_id: str,
    country: str,
    tenant_id: str,
    manifest_s3_key: str,
    tour_count: int,
    quality_score_avg: float,
) -> None:
    """Publish acp.s1.completed event to EventBridge."""
    import boto3
    eb = boto3.client("events", region_name=AWS_REGION)
    detail = {
        "run_id": run_id,
        "country": country,
        "tenant_id": tenant_id,
        "manifest_s3_key": manifest_s3_key,
        "tour_count": tour_count,
        "quality_score_avg": round(quality_score_avg, 2),
    }
    resp = eb.put_events(
        Entries=[{
            "Source": ACPEventSource.S1,
            "DetailType": ACPEventDetailType.S1_COMPLETED,
            "Detail": json.dumps(detail),
            "EventBusName": EVENTBRIDGE_BUS,
        }]
    )
    if resp.get("FailedEntryCount", 0):
        logger.error("eventbridge_put_failed", run_id=run_id, response=str(resp))
    else:
        logger.info("eventbridge_s1_published", run_id=run_id, country=country,
                    tour_count=tour_count, quality_score_avg=quality_score_avg)


# ── S0 EventBridge publish with retry ─────────────────────────────────────────

def publish_s0_completed(run_id: str, payload: dict) -> None:
    """Publish acp.s0.completed event to EventBridge (synchronous base)."""
    import boto3
    eb = boto3.client("events", region_name=AWS_REGION)
    detail = {"run_id": run_id, **payload}
    resp = eb.put_events(Entries=[{
        "Source": ACPEventSource.S0,
        "DetailType": ACPEventDetailType.S0_COMPLETED,
        "Detail": json.dumps(detail),
        "EventBusName": EVENTBRIDGE_BUS,
    }])
    if resp.get("FailedEntryCount", 0):
        raise RuntimeError(f"EventBridge FailedEntryCount>0: {resp}")
    logger.info("eventbridge_s0_published", run_id=run_id)


async def publish_s0_completed_with_retry(
    run_id: str,
    payload: dict,
    max_retries: int = 3,
) -> bool:
    """Publish acp.s0.completed with exponential backoff (1s, 2s, 4s).
    On exhaustion: marks acp_shared.acp_runs status='failed' and re-raises.
    """
    for attempt in range(max_retries):
        try:
            publish_s0_completed(run_id, payload)
            return True
        except Exception as exc:
            if attempt == max_retries - 1:
                logger.error("eventbridge_s0_exhausted", run_id=run_id,
                             attempts=max_retries, error=str(exc))
                await _update_run_failed(
                    run_id,
                    f"S0 publish failed after {max_retries} retries: {exc}",
                )
                raise
            delay = 2 ** attempt  # 1s, 2s, 4s
            logger.warning("eventbridge_s0_retry", run_id=run_id,
                           attempt=attempt + 1, delay=delay, error=str(exc))
            await asyncio.sleep(delay)
    return False  # unreachable — loop always returns or raises


async def _update_run_failed(run_id: str, error_message: str) -> None:
    """Update acp_shared.acp_runs status to 'failed'. Fire-and-forget safe — never raises."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.warning("update_run_failed_no_db_url", run_id=run_id)
        return
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url)
        await conn.execute(
            "UPDATE acp_shared.acp_runs SET status='failed', error_message=$2 "
            "WHERE run_id=$1::uuid",
            run_id, error_message[:500],
        )
        await conn.close()
        logger.info("run_marked_failed", run_id=run_id)
    except Exception as db_err:
        logger.error("update_run_failed_db_error", run_id=run_id, error=str(db_err))
