"""
AA-143 Synthetic Canary — Wave 0: S0→S1 smoke test.

Seeded fixture tour bypasses XLSX S0 upload (Wave 0 scope).
Asserts: S1 run created, completes, cost < $5, no forbidden words in output.

Env vars:
  API_BASE_URL          — e.g. http://internal-alb.us-west-1.elb.amazonaws.com
  ADMIN_SECRET          — X-Admin-Secret header value
  CANARY_ALERT_SNS_ARN  — optional; SNS topic ARN for failure alerts
  CANARY_TENANT_ID      — tenant UUID (default: aa_internal)
  RDS_SECRET_ID         — Secrets Manager secret ID (default: aa-cis/dev/rds)
  AWS_REGION            — AWS region (default: us-west-1)
"""
import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

API_BASE_URL = os.environ["API_BASE_URL"].rstrip("/")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
CANARY_ALERT_SNS_ARN = os.environ.get("CANARY_ALERT_SNS_ARN", "")
CANARY_TENANT_ID = os.environ.get(
    "CANARY_TENANT_ID", "00000000-0000-0000-0000-000000000001"
)
RDS_SECRET_ID = os.environ.get("RDS_SECRET_ID", "aa-cis/dev/rds")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-1")

FORBIDDEN_WORDS = ["cheap", "budget", "deal", "discount", "affordable"]
MAX_COST_USD = 5.0
POLL_TIMEOUT_S = 300
POLL_INTERVAL_S = 10
TERMINAL_RUN_STATUSES = {"completed", "published", "failed", "error", "cancelled"}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_dsn() -> str:
    client = boto3.client("secretsmanager", region_name=AWS_REGION)
    secret = client.get_secret_value(SecretId=RDS_SECRET_ID)
    return secret["SecretString"]


async def _connect(dsn: str):
    import asyncpg
    p = urlparse(dsn)
    return await asyncpg.connect(
        host=p.hostname,
        port=p.port or 5432,
        user=p.username,
        password=p.password,
        database=p.path.lstrip("/"),
        ssl="require",
    )


async def _seed_canary_tour_async(dsn: str, fixture: dict) -> str:
    """
    Seed fixture tour into raw_tours with review_status=approved.
    Creates a minimal pipeline_runs row first (required FK).
    Returns tour_id (str).
    """
    conn = await _connect(dsn)
    try:
        tour = fixture["tours"][0]

        # Clean up any previous canary fixture rows
        await conn.execute(
            "DELETE FROM silver_aa_internal.raw_tours WHERE src_name LIKE '%Canary Fixture%'"
        )

        # pipeline_runs row is required FK for raw_tours.batch_id
        batch_row = await conn.fetchrow(
            """
            INSERT INTO shared.pipeline_runs (tenant_id, batch_name, status, tours_total)
            VALUES ($1::uuid, 'canary-fixture', 'running', 1)
            RETURNING batch_id
            """,
            CANARY_TENANT_ID,
        )
        batch_id = str(batch_row["batch_id"])

        row = await conn.fetchrow(
            """
            INSERT INTO silver_aa_internal.raw_tours
                (tenant_id, batch_id, src_name, country, duration, price_raw, provider,
                 src_subtitle, src_summary, src_highlights, src_itineraries,
                 group_size, sku, review_status, pipeline_status)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12, $13,
                    'approved', 'ingested')
            RETURNING tour_id::text
            """,
            CANARY_TENANT_ID,
            batch_id,
            tour["src_name"],
            tour["country"],
            tour.get("duration"),
            tour.get("price_raw"),
            tour.get("provider"),
            tour.get("src_subtitle"),
            tour.get("src_summary"),
            json.dumps(tour.get("src_highlights", [])),
            tour.get("src_itineraries"),
            tour.get("group_size"),
            tour.get("sku"),
        )
        return str(row["tour_id"])
    finally:
        await conn.close()


async def _poll_run_async(dsn: str, run_id: str) -> dict:
    """Poll acp_runs until terminal status or timeout."""
    conn = await _connect(dsn)
    try:
        deadline = time.monotonic() + POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            row = await conn.fetchrow(
                """
                SELECT status, total_llm_cost_usd, error_message
                FROM acp_shared.acp_runs
                WHERE run_id = $1::uuid
                """,
                run_id,
            )
            if not row:
                raise ValueError(f"run_id {run_id} not found in acp_shared.acp_runs")
            if row["status"] in TERMINAL_RUN_STATUSES:
                return dict(row)
            logger.info(f"[CANARY] run_id={run_id} status={row['status']} — polling…")
            await asyncio.sleep(POLL_INTERVAL_S)
        return {"status": "timeout", "total_llm_cost_usd": None, "error_message": "poll timeout"}
    finally:
        await conn.close()


async def _fetch_stage_runs_async(dsn: str, run_id: str) -> list:
    """Fetch acp_stage_runs for a run. Returns list of dicts."""
    conn = await _connect(dsn)
    try:
        # completed_at exists only after migration 057; fall back gracefully
        try:
            rows = await conn.fetch(
                """
                SELECT stage, llm_cost_usd, tokens_input, tokens_output,
                       started_at, completed_at, error_msg
                FROM acp_shared.acp_stage_runs
                WHERE run_id = $1::uuid
                """,
                run_id,
            )
        except Exception:
            rows = await conn.fetch(
                """
                SELECT stage, llm_cost_usd, tokens_input, tokens_output
                FROM acp_shared.acp_stage_runs
                WHERE run_id = $1::uuid
                """,
                run_id,
            )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _fetch_content_sample_async(dsn: str, run_id: str) -> str:
    """Fetch combined text from first 5 tour_content_versions for forbidden-word check."""
    conn = await _connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT content::text AS content_text
            FROM silver_aa_internal.tour_content_versions
            WHERE acp_run_id = $1::uuid
            LIMIT 5
            """,
            run_id,
        )
        return " ".join(r["content_text"] or "" for r in rows).lower()
    finally:
        await conn.close()


# ── API helper ────────────────────────────────────────────────────────────────

def _api_call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{API_BASE_URL}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-Admin-Secret": ADMIN_SECRET,
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {"detail": e.read().decode(errors="replace")}


# ── Alert helper ──────────────────────────────────────────────────────────────

def _publish_alert(errors: list, run_id: str | None) -> None:
    if not CANARY_ALERT_SNS_ARN:
        logger.warning("[CANARY] CANARY_ALERT_SNS_ARN not set — skipping SNS alert")
        return
    sns = boto3.client("sns", region_name=AWS_REGION)
    msg = {
        "canary": "aa-cis-acp-s0-s1",
        "run_id": run_id,
        "errors": errors,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    sns.publish(
        TopicArn=CANARY_ALERT_SNS_ARN,
        Subject="[AA-CIS CANARY FAILED] ACP S0→S1",
        Message=json.dumps(msg, indent=2),
    )
    logger.info(f"[CANARY] Alert published to SNS topic: {CANARY_ALERT_SNS_ARN}")


# ── Main handler ──────────────────────────────────────────────────────────────

def handler(event, context):
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "canary_fixture.json")
    with open(fixture_path) as fh:
        fixture = json.load(fh)

    errors: list[str] = []
    run_id: str | None = None
    dsn = _get_dsn()

    # ── Step 1: Seed canary tour (S0 bypass — direct DB insert) ──────────────
    try:
        tour_id = asyncio.run(_seed_canary_tour_async(dsn, fixture))
        logger.info(f"[CANARY] S0 seed OK — tour_id={tour_id}")
    except Exception as exc:
        errors.append(f"S0 seed failed: {exc}")
        logger.error(f"[CANARY] {errors[-1]}", exc_info=True)
        _publish_alert(errors, run_id)
        return {"status": "FAILED", "errors": errors}

    # ── Step 2: Create S1 run via API ────────────────────────────────────────
    status_code, resp = _api_call(
        "POST",
        "/acp/s1/run",
        {
            "tour_ids": [tour_id],
            "run_config": {
                "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                "seo_mode": "informational",
                "language": "EN-US",
            },
        },
    )
    if status_code != 200:
        errors.append(f"S1 /run returned HTTP {status_code}: {resp}")
        logger.error(f"[CANARY] {errors[-1]}")
        _publish_alert(errors, run_id)
        return {"status": "FAILED", "errors": errors}

    run_id = resp.get("run_id")
    started_count = resp.get("started_count", 0)
    logger.info(f"[CANARY] S1 run created — run_id={run_id}, started={started_count}")

    if not run_id:
        errors.append("S1 /run response missing run_id")
        _publish_alert(errors, run_id)
        return {"status": "FAILED", "errors": errors}

    # ── Step 3: Poll until S1 run reaches terminal status ────────────────────
    try:
        run_result = asyncio.run(_poll_run_async(dsn, run_id))
    except Exception as exc:
        errors.append(f"Poll failed: {exc}")
        logger.error(f"[CANARY] {errors[-1]}", exc_info=True)
        _publish_alert(errors, run_id)
        return {"status": "FAILED", "errors": errors, "run_id": run_id}

    final_status = run_result.get("status", "unknown")
    logger.info(f"[CANARY] run_id={run_id} final_status={final_status}")

    if final_status not in ("completed", "published"):
        errors.append(
            f"S1 run ended with status={final_status!r}"
            f" — {run_result.get('error_message') or 'no error detail'}"
        )

    # ── Step 4: Assert cost ───────────────────────────────────────────────────
    raw_cost = run_result.get("total_llm_cost_usd")
    cost_usd = float(raw_cost) if raw_cost is not None else None
    if cost_usd is None:
        logger.warning("[CANARY] total_llm_cost_usd is NULL — migration 055 may not be applied")
    elif cost_usd >= MAX_COST_USD:
        errors.append(f"Cost too high: ${cost_usd:.4f} >= limit ${MAX_COST_USD}")

    # ── Step 5: Assert acp_stage_runs (requires migration 057) ───────────────
    try:
        stage_runs = asyncio.run(_fetch_stage_runs_async(dsn, run_id))
        s1_stage = next((s for s in stage_runs if s.get("stage") == "s1"), None)
        if s1_stage:
            completed_at = s1_stage.get("completed_at")
            if completed_at is None:
                errors.append("acp_stage_runs: S1 stage completed_at is NULL (stuck?)")
            else:
                logger.info(f"[CANARY] S1 stage completed_at={completed_at}")
        else:
            logger.warning("[CANARY] No s1 row in acp_stage_runs — cost tracking may not be active")
    except Exception as exc:
        logger.warning(f"[CANARY] stage_runs fetch failed (migration 055/057 not applied?): {exc}")

    # ── Step 6: Check for forbidden words in S1 output ───────────────────────
    try:
        content_text = asyncio.run(_fetch_content_sample_async(dsn, run_id))
        found_words = [w for w in FORBIDDEN_WORDS if w in content_text]
        if found_words:
            errors.append(f"Forbidden words in S1 output: {found_words}")
        else:
            logger.info("[CANARY] Forbidden-word check: PASS")
    except Exception as exc:
        logger.warning(f"[CANARY] Forbidden-word check failed: {exc}")

    # ── Result ────────────────────────────────────────────────────────────────
    if errors:
        logger.error(f"[CANARY] FAILED — {len(errors)} error(s): {errors}")
        _publish_alert(errors, run_id)
        return {"status": "FAILED", "errors": errors, "run_id": run_id}

    logger.info(f"[CANARY] PASSED — run_id={run_id}, cost=${cost_usd}, stage=S1")
    return {
        "status": "PASSED",
        "run_id": run_id,
        "cost_usd": cost_usd,
        "stage": "S1",
    }
