"""
EventBridge → Lambda → POST /v1/acp/s4/blog/runs
Triggered by acp.hitl.approved event after Gate 2 approval.
env: ALB_INTERNAL_URL, INTERNAL_API_KEY, DATABASE_URL (optional — for idempotency)
"""
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_ALB_URL = os.environ.get("ALB_INTERNAL_URL", "")
_API_KEY = os.environ.get("INTERNAL_API_KEY", "")

# Idempotency helpers — inlined to avoid Lambda layer dependency on services/
_DB_URL = os.environ.get("DATABASE_URL", "")


def _is_already_processed(event_id: str, run_id: str) -> bool:
    """Returns True if this EventBridge event was already forwarded to S4."""
    if not _DB_URL or not event_id:
        return False
    try:
        from urllib.parse import urlparse
        import psycopg2
        parts = urlparse(_DB_URL)
        with psycopg2.connect(
            host=parts.hostname, port=parts.port or 5432,
            user=parts.username, password=parts.password,
            dbname=parts.path.lstrip("/"), sslmode="require",
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM acp_shared.acp_stage_runs WHERE event_id = %s LIMIT 1",
                    (event_id,),
                )
                return cur.fetchone() is not None
    except Exception as e:
        logger.warning("idempotency check failed (allowing): %s", e)
        return False


def _mark_received(event_id: str, run_id: str) -> None:
    if not _DB_URL:
        return
    try:
        from urllib.parse import urlparse
        import psycopg2
        parts = urlparse(_DB_URL)
        with psycopg2.connect(
            host=parts.hostname, port=parts.port or 5432,
            user=parts.username, password=parts.password,
            dbname=parts.path.lstrip("/"), sslmode="require",
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO acp_shared.acp_stage_runs
                        (run_id, stage, event_id, event_received_at, status)
                    VALUES (%s, 's4_trigger', %s, NOW(), 'processing')
                    ON CONFLICT (run_id, stage) DO UPDATE
                        SET event_id          = EXCLUDED.event_id,
                            event_received_at = EXCLUDED.event_received_at,
                            status            = 'processing',
                            updated_at        = NOW()
                    """,
                    (run_id, event_id),
                )
            conn.commit()
    except Exception as e:
        logger.warning("mark_event_received failed: %s", e)


def handler(event, context):
    logger.info("s4_trigger event: %s", json.dumps(event))

    event_id = event.get("id")  # EventBridge envelope ID
    detail = event.get("detail", {})
    run_id = detail.get("run_id")
    tenant_id = detail.get("tenant_id")

    if not run_id or not tenant_id:
        logger.error("s4_trigger missing run_id or tenant_id in detail=%s", detail)
        return {"statusCode": 400, "body": "Missing run_id or tenant_id"}

    if _is_already_processed(event_id, run_id):
        logger.info("s4_trigger duplicate event_id=%s run_id=%s, skipping", event_id, run_id)
        return {"statusCode": 200, "body": "duplicate_skipped"}

    _mark_received(event_id, run_id)

    payload = json.dumps({
        "run_id": run_id,
        "tenant_id": tenant_id,
        "trigger_source": "eventbridge_hitl_approved",
    }).encode()

    req = urllib.request.Request(
        f"{_ALB_URL}/v1/acp/s4/blog/runs",
        data=payload,
        headers={"Content-Type": "application/json", "X-Internal-Key": _API_KEY},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            logger.info("s4_trigger success run_id=%s: %s", run_id, body[:200])
            return {"statusCode": 200, "body": body}
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()[:300]
        logger.error("s4_trigger http_error=%s body=%s", exc.code, err)
        return {"statusCode": exc.code, "body": err}
    except Exception as exc:
        logger.error("s4_trigger exception: %s", exc)
        raise  # Let Lambda retry
