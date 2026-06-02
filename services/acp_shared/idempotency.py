"""
EventBridge consumer idempotency helpers.

Usage in every EventBridge consumer handler:

    from services.acp_shared.idempotency import is_event_already_processed, mark_event_received

    def handler(event, context):
        event_id = event.get("id")        # EventBridge envelope field
        run_id   = event["detail"]["run_id"]
        stage    = "s4_trigger"           # unique name per consumer

        if is_event_already_processed(event_id, run_id, stage):
            log.info("duplicate event %s, skipping", event_id)
            return {"statusCode": 200, "body": "duplicate_skipped"}

        mark_event_received(event_id, run_id, stage)
        # ... rest of handler
"""
import logging
import os
from urllib.parse import urlparse

log = logging.getLogger(__name__)


def _connect(db_url: str):
    import psycopg2
    parts = urlparse(db_url)
    return psycopg2.connect(
        host=parts.hostname,
        port=parts.port or 5432,
        user=parts.username,
        password=parts.password,
        dbname=parts.path.lstrip("/"),
        sslmode="require",
    )


def is_event_already_processed(event_id: str, run_id: str, stage: str,
                                db_url: str = None) -> bool:
    """
    Returns True if event_id already exists in acp_stage_runs.
    Never raises — returns False (allow processing) on any error so a DB
    outage does not permanently block the pipeline.
    """
    url = db_url or os.environ.get("DATABASE_URL")
    if not url or not event_id:
        return False
    try:
        with _connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM acp_shared.acp_stage_runs WHERE event_id = %s LIMIT 1",
                    (event_id,),
                )
                return cur.fetchone() is not None
    except Exception as e:
        log.warning("idempotency check failed (allowing): %s", e)
        return False


def mark_event_received(event_id: str, run_id: str, stage: str,
                        db_url: str = None) -> None:
    """
    UPSERT an acp_stage_runs row with the EventBridge event_id.
    Call immediately after the idempotency check passes.
    """
    url = db_url or os.environ.get("DATABASE_URL")
    if not url:
        return
    try:
        with _connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO acp_shared.acp_stage_runs
                        (run_id, stage, event_id, event_received_at, status)
                    VALUES (%s, %s, %s, NOW(), 'processing')
                    ON CONFLICT (run_id, stage) DO UPDATE
                        SET event_id           = EXCLUDED.event_id,
                            event_received_at  = EXCLUDED.event_received_at,
                            status             = 'processing',
                            updated_at         = NOW()
                    """,
                    (run_id, stage, event_id),
                )
            conn.commit()
    except Exception as e:
        log.warning("mark_event_received failed: %s", e)
