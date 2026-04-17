"""
DLQ Classifier — route failed messages từ Dead Letter Queues
Phân loại lỗi → retry / alert / discard
"""
import json
import os
import boto3
import structlog

logger = structlog.get_logger()
sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-west-1"))
sns = boto3.client("sns", region_name=os.environ.get("AWS_REGION", "us-west-1"))

# Error classification
RETRYABLE_ERRORS = [
    "ThrottlingException",
    "ServiceUnavailable",
    "TooManyRequestsException",
    "ProvisionedThroughputExceededException",
    "Lambda.TooManyRequestsException",
    "RequestTimeout",
]

FATAL_ERRORS = [
    "ValidationError",
    "InvalidParameterException",
    "ResourceNotFoundException",
]

QUEUE_MAP = {
    "ingestion": os.environ.get("INGESTION_QUEUE_URL", ""),
    "seo":       os.environ.get("SEO_QUEUE_URL", ""),
    "content":   os.environ.get("CONTENT_GEN_QUEUE_URL", ""),
    "validation":os.environ.get("VALIDATION_QUEUE_URL", ""),
    "export":    os.environ.get("EXPORT_QUEUE_URL", ""),
}

def classify_error(error_msg: str) -> str:
    """Return: retryable / fatal / unknown"""
    for err in RETRYABLE_ERRORS:
        if err.lower() in error_msg.lower():
            return "retryable"
    for err in FATAL_ERRORS:
        if err.lower() in error_msg.lower():
            return "fatal"
    return "unknown"

def get_retry_count(message: dict) -> int:
    attrs = message.get("messageAttributes", {})
    return int(attrs.get("RetryCount", {}).get("stringValue", "0"))

def should_retry(error_class: str, retry_count: int) -> bool:
    return error_class == "retryable" and retry_count < 3

def requeue_message(queue_url: str, body: dict, retry_count: int):
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(body),
        MessageAttributes={
            "RetryCount": {
                "StringValue": str(retry_count + 1),
                "DataType":    "Number",
            }
        },
        DelaySeconds=min(30 * (retry_count + 1), 900),  # exponential: 30/60/90s
    )
    logger.info("requeued", queue_url=queue_url, retry=retry_count + 1)

def send_alert(message: dict, error_class: str, source_queue: str):
    alert_topic = os.environ.get("ALERT_TOPIC_ARN")
    if not alert_topic:
        return
    sns.publish(
        TopicArn=alert_topic,
        Subject=f"AA-CIS DLQ Alert — {error_class} error in {source_queue}",
        Message=json.dumps({
            "error_class":   error_class,
            "source_queue":  source_queue,
            "message_body":  message,
        }, indent=2),
    )
    logger.warning("alert_sent", error_class=error_class, source_queue=source_queue)

def lambda_handler(event: dict, context) -> dict:
    results = []

    for record in event.get("Records", []):
        try:
            body         = json.loads(record.get("body", "{}"))
            error_msg    = str(body.get("error", ""))
            source_queue = body.get("source_queue", "unknown")
            retry_count  = get_retry_count(record)

            error_class = classify_error(error_msg)
            logger.info("dlq_received",
                        source=source_queue,
                        error_class=error_class,
                        retry_count=retry_count,
                        error=error_msg[:100])

            if should_retry(error_class, retry_count):
                queue_url = QUEUE_MAP.get(source_queue)
                if queue_url:
                    requeue_message(queue_url, body, retry_count)
                    results.append({
                        "action": "requeued",
                        "source": source_queue,
                        "retry":  retry_count + 1,
                    })
                else:
                    logger.error("unknown_queue", source_queue=source_queue)
                    results.append({"action": "discarded", "reason": "unknown_queue"})

            elif error_class == "fatal" or retry_count >= 3:
                send_alert(body, error_class, source_queue)
                results.append({
                    "action": "alerted",
                    "source": source_queue,
                    "error_class": error_class,
                })

            else:
                logger.warning("discarded", source=source_queue, error=error_msg[:100])
                results.append({"action": "discarded", "source": source_queue})

        except Exception as e:
            logger.error("dlq_classifier_failed", error=str(e))
            results.append({"action": "failed", "error": str(e)})

    return {"processed": len(results), "results": results}
