import os
import json
import urllib.request
import urllib.error

def lambda_handler(event, context):
    """
    ContentGeneration Lambda — gọi POST /v1/pipeline/run-tour per tour.
    Input từ SF: {tour_id, batch_id, tenant_id, retry_count, validation_feedback}
    """
    api_url = os.environ["API_BASE_URL"]
    endpoint = f"{api_url}/v1/pipeline/run-tour"
    payload = {
        "tour_id":             event.get("tour_id"),
        "batch_id":            event.get("batch_id"),
        "tenant_id":           event.get("tenant_id"),
        "retry_count":         event.get("retry_count", 0),
        "validation_feedback": event.get("validation_feedback", []),
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=840) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return {
                "tour_id":       event.get("tour_id"),
                "batch_id":      event.get("batch_id"),
                "version_id":    result.get("version_id"),
                "status":        result.get("status", "done"),
                "quality_score": result.get("quality_score"),
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise Exception(f"API error {e.code}: {body}")
    except Exception as e:
        raise Exception(f"ContentGen failed: {str(e)}")
