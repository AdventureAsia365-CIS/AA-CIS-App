"""
AA-298 Nhóm 5 — N7 produce_slot sweeper.

Catches what services/acp_produce/reliability.py::run_produce_slot() cannot:
a slot whose process died before any except/finally ran at all (hard kill,
ECS Fargate Spot reclaim mid-instruction, OOM). Those slots sit in
acp_shared.acp_stage_checkpoints with status='running' forever unless
something else notices. This Lambda scans for exactly that and marks them
failed + alarms — it does not retry them itself (retry/resume is the
caller's job, using acp_shared.stage_checkpoint.get_incomplete_items() on the
next run of the same run_id, same as S4.2/AA-107 already does).

SLA_HOURS default (1.0) is a DOCUMENTED PLACEHOLDER, not measured production
data — the full N7 slot pipeline (C1/C2 DFS -> brief -> E1-E5 -> F1-F9,
see docs/implementation-notes/AA-298.md) hasn't run in production yet, so
there is no real timing distribution to set this from. Override via the
SWEEPER_SLA_HOURS env var once real data exists; do not treat 1.0 as
authoritative.

Env vars:
  RDS_SECRET_ID          — Secrets Manager secret ID (default: aa-cis/dev/rds)
  AWS_REGION              — AWS region (default: us-west-1)
  SWEEPER_SLA_HOURS        — hours a slot may sit 'running' before being swept (default: 1.0)
  SWEEPER_ALERT_SNS_ARN    — optional; SNS topic ARN for sweep alerts
"""
import json
import logging
import os
import time
from urllib.parse import urlparse

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

RDS_SECRET_ID = os.environ.get("RDS_SECRET_ID", "aa-cis/dev/rds")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-1")
SWEEPER_SLA_HOURS = float(os.environ.get("SWEEPER_SLA_HOURS", "1.0"))
SWEEPER_ALERT_SNS_ARN = os.environ.get("SWEEPER_ALERT_SNS_ARN", "")

PRODUCE_SLOT_ITEM_TYPE = "produce_slot"


def _get_dsn() -> str:
    client = boto3.client("secretsmanager", region_name=AWS_REGION)
    return client.get_secret_value(SecretId=RDS_SECRET_ID)["SecretString"]


async def _sweep_async(dsn: str, sla_hours: float) -> list[dict]:
    import asyncpg

    p = urlparse(dsn)
    conn = await asyncpg.connect(
        host=p.hostname, port=p.port or 5432, user=p.username, password=p.password,
        database=p.path.lstrip("/"), ssl="require",
    )
    try:
        stuck = await conn.fetch(
            """
            SELECT id, run_id, item_id, created_at, updated_at
            FROM acp_shared.acp_stage_checkpoints
            WHERE item_type = $1
              AND status = 'running'
              AND updated_at < NOW() - ($2 || ' hours')::interval
            """,
            PRODUCE_SLOT_ITEM_TYPE, str(sla_hours),
        )
        swept = []
        for row in stuck:
            await conn.execute(
                """
                UPDATE acp_shared.acp_stage_checkpoints
                SET status = 'failed',
                    error_msg = $1,
                    updated_at = NOW()
                WHERE id = $2
                """,
                f"swept: stuck in 'running' past SLA ({sla_hours}h, last update {row['updated_at']})",
                row["id"],
            )
            swept.append({
                "run_id": str(row["run_id"]), "slot_id": row["item_id"],
                "stuck_since": row["updated_at"].isoformat(),
            })
        return swept
    finally:
        await conn.close()


def _publish_alert(swept: list[dict]) -> None:
    if not SWEEPER_ALERT_SNS_ARN:
        logger.warning("[SWEEPER] SWEEPER_ALERT_SNS_ARN not set — skipping SNS alert")
        return
    sns = boto3.client("sns", region_name=AWS_REGION)
    msg = {
        "sweeper": "aa-cis-acp-n7-produce-slot",
        "swept_count": len(swept),
        "slots": swept,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    sns.publish(
        TopicArn=SWEEPER_ALERT_SNS_ARN,
        Subject=f"[AA-CIS] N7 produce_slot sweeper: {len(swept)} stuck slot(s) marked failed",
        Message=json.dumps(msg, indent=2),
    )
    logger.info(f"[SWEEPER] Alert published to SNS topic: {SWEEPER_ALERT_SNS_ARN}")


def handler(event, context):
    import asyncio

    dsn = _get_dsn()
    try:
        swept = asyncio.run(_sweep_async(dsn, SWEEPER_SLA_HOURS))
    except Exception as exc:
        logger.error(f"[SWEEPER] sweep failed: {exc}", exc_info=True)
        return {"status": "ERROR", "error": str(exc)}

    if swept:
        logger.warning(f"[SWEEPER] swept {len(swept)} stuck slot(s): {swept}")
        _publish_alert(swept)
    else:
        logger.info("[SWEEPER] no stuck slots found")

    return {"status": "OK", "swept_count": len(swept), "swept": swept}
