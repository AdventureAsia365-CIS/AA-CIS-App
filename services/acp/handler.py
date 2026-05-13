"""
ACP S1 integration: manifest.json upload + EventBridge publish.
Called by export handler when a batch completes.
"""
import json
import os
import structlog
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
            "Source": "aa-cis.pipeline",
            "DetailType": "acp.s1.completed",
            "Detail": json.dumps(detail),
            "EventBusName": EVENTBRIDGE_BUS,
        }]
    )
    if resp.get("FailedEntryCount", 0):
        logger.error("eventbridge_put_failed", run_id=run_id, response=str(resp))
    else:
        logger.info("eventbridge_s1_published", run_id=run_id, country=country,
                    tour_count=tour_count, quality_score_avg=quality_score_avg)
