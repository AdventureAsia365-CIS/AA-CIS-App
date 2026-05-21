"""
EventBridge → Lambda → POST /v1/acp/s4/blog/runs
Triggered by acp.s3.completed event after Gate 2 approval.
env: ALB_INTERNAL_URL, INTERNAL_API_KEY
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


def handler(event, context):
    logger.info("s4_trigger event: %s", json.dumps(event))

    detail = event.get("detail", {})
    run_id = detail.get("run_id")
    tenant_id = detail.get("tenant_id")

    if not run_id or not tenant_id:
        logger.error("s4_trigger missing run_id or tenant_id in detail=%s", detail)
        return {"statusCode": 400, "body": "Missing run_id or tenant_id"}

    payload = json.dumps({
        "run_id": run_id,
        "tenant_id": tenant_id,
        "trigger_source": "eventbridge_s3_completed",
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
