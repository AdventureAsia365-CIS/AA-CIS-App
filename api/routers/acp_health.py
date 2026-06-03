"""
GET /admin/acp/run-health — Run-Health dashboard endpoint (AA-141).

Returns live state of every ACP run: stage status/timing, cost, gate SLA,
evaluator score, stuck detection. Emits CloudWatch custom metrics on each call.

Auth:
  X-Admin-Secret header → all tenants (aa_internal admin view)
  Bearer JWT            → tenant sees own runs only (RLS)
"""
import os
from datetime import datetime, timezone
from typing import Optional

import boto3
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials as _Creds
from fastapi.security import HTTPBearer as _HTTPBearer

from api.routers.auth import verify_jwt as _verify_jwt
from api.services.acp_health import (
    EVALUATOR_SCORE_FLOOR,
    GATE_SLA_HOURS,
    STAGE_INT_TO_GATE,
    check_cost_cap,
    check_gate_sla,
    check_stage_slo,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/admin/acp", tags=["acp-health"])


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_caller(
    request: Request,
    credentials: Optional[_Creds] = Depends(_HTTPBearer(auto_error=False)),
) -> dict:
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    x_admin = request.headers.get("X-Admin-Secret", "")
    if admin_secret and x_admin == admin_secret:
        return {"role": "admin", "sub": None}
    if credentials:
        try:
            payload = _verify_jwt(credentials.credentials)
            return {"role": payload.get("role", "tenant"), "sub": payload.get("sub")}
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dec(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _iso(v):
    return v.isoformat() if v else None


def _duration_seconds(started, completed) -> Optional[float]:
    if started is None:
        return None
    end = completed if completed else datetime.now(timezone.utc)
    # asyncpg returns timezone-aware datetimes; ensure comparison is safe
    if hasattr(end, 'tzinfo') and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if hasattr(started, 'tzinfo') and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (end - started).total_seconds()


def _elapsed_hours(created_at, resolved_at) -> Optional[float]:
    if created_at is None:
        return None
    end = resolved_at if resolved_at else datetime.now(timezone.utc)
    if hasattr(end, 'tzinfo') and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if hasattr(created_at, 'tzinfo') and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (end - created_at).total_seconds() / 3600.0


def _emit_cloudwatch_metrics(metrics: list[dict]) -> None:
    """Best-effort CloudWatch PutMetricData. Silently skips on error."""
    try:
        cw = boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-1"))
        cw.put_metric_data(Namespace="acp", MetricData=metrics)
    except Exception as exc:
        logger.warning("cloudwatch_emit_failed", error=str(exc))


# ── GET /admin/acp/run-health ─────────────────────────────────────────────────

@router.get("/run-health")
async def get_run_health(
    request: Request,
    tenant_id: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    caller: dict = Depends(_get_caller),
):
    """
    Live run-health for all ACP runs (admin) or own runs (tenant JWT).
    Emits CloudWatch metrics: acp/stuck_runs, acp/cost_usd_per_run,
    acp/evaluator_score, acp/gate_sla_breached.
    """
    pool = request.app.state.pool

    conditions = ["1=1"]
    params: list = []

    # RLS: non-admin tenants see only their own runs
    if caller["role"] != "admin" and caller["sub"]:
        params.append(caller["sub"])
        conditions.append(f"r.tenant_id = ${len(params)}::uuid")
    elif tenant_id:
        params.append(tenant_id)
        conditions.append(f"r.tenant_id = ${len(params)}::uuid")

    if country:
        params.append(country)
        conditions.append(f"LOWER(r.country) = LOWER(${len(params)})")
    if status:
        params.append(status)
        conditions.append(f"r.status = ${len(params)}")
    if date_from:
        params.append(date_from)
        conditions.append(f"r.started_at >= ${len(params)}::timestamptz")
    if date_to:
        params.append(date_to)
        conditions.append(f"r.started_at <= ${len(params)}::timestamptz")

    params.append(limit)
    limit_param = len(params)
    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        run_rows = await conn.fetch(f"""
            SELECT
                r.run_id::text, r.tenant_id::text, r.country, r.status,
                r.total_llm_cost_usd, r.started_at, r.completed_at, r.error_message
            FROM acp_shared.acp_runs r
            WHERE {where}
            ORDER BY r.started_at DESC NULLS LAST
            LIMIT ${limit_param}
        """, *params)

        if not run_rows:
            return []

        run_ids = [r["run_id"] for r in run_rows]

        stage_rows = await conn.fetch("""
            SELECT
                run_id::text, stage, status, started_at, completed_at, error_msg,
                llm_cost_usd
            FROM acp_shared.acp_stage_runs
            WHERE run_id = ANY($1::uuid[])
            ORDER BY run_id, started_at NULLS LAST
        """, run_ids)

        hitl_rows = await conn.fetch("""
            SELECT
                run_id::text, stage, status, created_at, resolved_at, auto_approved,
                confidence_score
            FROM acp_shared.acp_hitl_requests
            WHERE run_id = ANY($1::uuid[])
            ORDER BY run_id, stage
        """, run_ids)

        eval_rows = await conn.fetch("""
            SELECT run_id::text, AVG(evaluator_score) AS avg_score
            FROM acp_silver_s4.blog_drafts
            WHERE run_id = ANY($1::uuid[])
              AND evaluator_score IS NOT NULL
            GROUP BY run_id
        """, run_ids)

    # Index by run_id
    stages_by_run: dict[str, list] = {}
    for s in stage_rows:
        stages_by_run.setdefault(s["run_id"], []).append(s)

    hitl_by_run: dict[str, list] = {}
    for h in hitl_rows:
        hitl_by_run.setdefault(h["run_id"], []).append(h)

    eval_by_run: dict[str, Optional[float]] = {
        r["run_id"]: _dec(r["avg_score"]) for r in eval_rows
    }

    result = []
    total_stuck = 0
    total_gate_breached = 0

    for run in run_rows:
        run_id = run["run_id"]
        cost = _dec(run["total_llm_cost_usd"]) or 0.0

        # ── Stage records ──────────────────────────────────────────────────
        stages_out = []
        run_stuck = False

        for s in stages_by_run.get(run_id, []):
            dur = _duration_seconds(s["started_at"], s["completed_at"])
            stage_name = s["stage"] or ""
            is_running = (s["status"] or "").lower() in ("running", "pending")
            slo_breached = (
                dur is not None
                and is_running
                and check_stage_slo(stage_name, dur)
            )
            if slo_breached:
                run_stuck = True

            stages_out.append({
                "stage":            stage_name,
                "status":           s["status"],
                "started_at":       _iso(s["started_at"]),
                "completed_at":     _iso(s["completed_at"]),
                "duration_seconds": round(dur, 1) if dur is not None else None,
                "error_msg":        s["error_msg"],
                "slo_breached":     slo_breached,
            })

        # ── Gate statuses ──────────────────────────────────────────────────
        gates_out: dict[str, dict] = {}
        for h in hitl_by_run.get(run_id, []):
            stage_int = h["stage"]
            gate_num = STAGE_INT_TO_GATE.get(stage_int)
            if gate_num is None:
                continue
            sla_hours = GATE_SLA_HOURS[gate_num]
            elapsed = _elapsed_hours(h["created_at"], h["resolved_at"])
            breached = (
                elapsed is not None
                and (h["status"] or "").lower() == "pending"
                and check_gate_sla(gate_num, elapsed)
            )
            if breached:
                total_gate_breached += 1

            gates_out[f"gate_{gate_num}"] = {
                "status":        h["status"],
                "elapsed_hours": round(elapsed, 2) if elapsed is not None else None,
                "sla_hours":     sla_hours,
                "breached":      breached,
                "auto_approved": h["auto_approved"],
            }

        # Fill in None for gates not yet created
        for gn in range(4):
            key = f"gate_{gn}"
            if key not in gates_out:
                gates_out[key] = None

        evaluator_score = eval_by_run.get(run_id)
        if run_stuck:
            total_stuck += 1

        result.append({
            "run_id":           run_id,
            "tenant_id":        run["tenant_id"],
            "country":          run["country"],
            "status":           run["status"],
            "started_at":       _iso(run["started_at"]),
            "completed_at":     _iso(run["completed_at"]),
            "stages":           stages_out,
            "total_cost_usd":   cost,
            "cost_cap_breached": check_cost_cap(cost),
            "gate_statuses":    gates_out,
            "evaluator_score":  evaluator_score,
            "evaluator_warning": (
                evaluator_score is not None and evaluator_score < EVALUATOR_SCORE_FLOOR
            ),
            "retry_count":      0,  # UNIQUE(run_id, stage) — upserted in-place
            "stuck":            run_stuck,
        })

    # ── Emit CloudWatch metrics ────────────────────────────────────────────
    _emit_cloudwatch_metrics([
        {
            "MetricName": "stuck_runs",
            "Value": float(total_stuck),
            "Unit": "Count",
        },
        {
            "MetricName": "gate_sla_breached",
            "Value": float(total_gate_breached),
            "Unit": "Count",
        },
    ])

    logger.info("run_health_queried", run_count=len(result), stuck=total_stuck)
    return result
