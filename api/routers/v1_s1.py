"""
/acp/s1 — S1 Configured Rewrite Engine endpoints (admin-facing).

Route order (specific before parameterized):
  GET  /tours                         → list approved tours
  POST /run                           → create run + trigger SF per tour
  GET  /runs                          → list all runs with counts
  GET  /run/{run_id}/stream           → SSE progress stream
  GET  /tours/{raw_tour_id}/versions  → version history for a tour
  PATCH /versions/{version_id}/activate → activate a specific version

Table: acp_shared.acp_runs  (PK=run_id, acpcore v0.4.0 schema)
Table: silver_aa_internal.tour_content_versions  (PK=id, FK→run_id + tour_id)

Auth: Single-header tenant auth (AA-181) — X-API-Key (tenant) or X-Admin-Secret (AA internal).
"""
import asyncio
import json
import os
import structlog

from datetime import date
from typing import Optional
from uuid import UUID

import boto3 as _boto3
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.routers.auth import verify_tenant_api_key as _get_tenant

logger = structlog.get_logger()
router = APIRouter(tags=["S1 Rewrite"])

_TERMINAL_STATUSES = {"published", "failed", "rejected"}
_SSE_POLL_INTERVAL = 2    # seconds between DB polls
_SSE_HEARTBEAT_S = 15     # seconds between SSE heartbeat comments
_SSE_TIMEOUT_S = 1800     # 30 minutes max stream duration


# ── Pydantic models ───────────────────────────────────────────────────────────

class RunConfig(BaseModel):
    model_id:           str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    seo_mode:           str = "informational"
    brand_identity_id:  Optional[str] = None
    language:           str = "EN-US"


class CreateRunRequest(BaseModel):
    tour_ids:   list[str]
    run_config: RunConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail=f"Invalid UUID for {field}: {value!r}")


def _row_to_tour(r) -> dict:
    return {
        "id":            str(r["tour_id"]),
        "tour_code":     r.get("sku") or r.get("tour_id_external") or "",
        "aa_name":       r.get("src_name") or "",
        "country":       r.get("country") or "",
        "supplier":      r.get("provider") or "",
        "review_status": r.get("review_status") or "",
        "updated_at":    r["ingest_at"].isoformat() if r.get("ingest_at") else None,
    }


# ── GET /tours ────────────────────────────────────────────────────────────────

@router.get("/tours")
async def list_approved_tours(
    request:          Request,
    tenant=Depends(_get_tenant),
    country: Optional[str] = None,
    supplier: Optional[str] = None,
    upload_date_from: Optional[date] = None,
    upload_date_to:   Optional[date] = None,
):
    """List raw_tours where review_status='approved' with optional filters."""
    pool = request.app.state.pool

    conditions = ["review_status = 'approved'"]
    params: list = []
    idx = 1

    if country:
        conditions.append(f"LOWER(country) = LOWER(${idx})")
        params.append(country)
        idx += 1

    if supplier:
        conditions.append(f"LOWER(provider) LIKE LOWER(${idx})")
        params.append(f"%{supplier}%")
        idx += 1

    if upload_date_from:
        conditions.append(f"ingest_at >= ${idx}")
        params.append(upload_date_from)
        idx += 1

    if upload_date_to:
        conditions.append(f"ingest_at < ${idx} + INTERVAL '1 day'")
        params.append(upload_date_to)
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT tour_id, sku, tour_id_external, src_name, country,
                   provider, review_status, ingest_at
            FROM silver_aa_internal.raw_tours
            WHERE {where}
            ORDER BY ingest_at DESC
            LIMIT 500
        """, *params)

    return {"data": [_row_to_tour(r) for r in rows], "total": len(rows)}


# ── POST /run ─────────────────────────────────────────────────────────────────

@router.post("/run")
async def create_run(
    body:    CreateRunRequest,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """
    Create an acp_run, one tour_content_versions row per tour, trigger SF per tour.
    Returns run_id, tour_count, started_count, failed_count.
    """
    if not body.tour_ids:
        raise HTTPException(status_code=422, detail="tour_ids must not be empty")

    validated_ids = [_safe_uuid(tid, "tour_ids") for tid in body.tour_ids]
    pool = request.app.state.pool
    run_config_dict = body.run_config.model_dump()

    async with pool.acquire() as conn:
        # Validate all tour_ids exist and are approved
        approved = await conn.fetch("""
            SELECT tour_id FROM silver_aa_internal.raw_tours
            WHERE tour_id = ANY($1::uuid[]) AND review_status = 'approved'
        """, validated_ids)
        approved_set = {str(r["tour_id"]) for r in approved}
        invalid = [tid for tid in validated_ids if tid not in approved_set]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Tours not found or not approved: {invalid}",
            )

        # Create acp_runs row
        run_row = await conn.fetchrow(
            """
            INSERT INTO acp_shared.acp_runs
                (tenant_id, country, status, tour_count, run_config)
            VALUES ($1, $2, 'running', $3, $4)
            RETURNING run_id
            """,
            str(tenant.get("sub", "")),
            run_config_dict.get("language", ""),
            len(validated_ids),
            json.dumps(run_config_dict),
        )
        run_id = str(run_row["run_id"])

        # Insert tour_content_versions rows
        for tour_id in validated_ids:
            await conn.execute("""
                INSERT INTO silver_aa_internal.tour_content_versions
                    (raw_tour_id, acp_run_id, run_config, status, is_active)
                VALUES ($1::uuid, $2::uuid, $3, 'draft', FALSE)
            """, tour_id, run_id, json.dumps(run_config_dict))

    # Trigger Step Functions per tour (outside DB transaction — failures are non-fatal)
    sf_arn = os.environ.get("STEP_FUNCTIONS_ARN", "")
    started, failed = 0, 0

    if not sf_arn:
        logger.warning("s1_sf_arn_missing", run_id=run_id)
        started = len(validated_ids)
    else:
        sfn = _boto3.client("stepfunctions", region_name=os.environ.get("AWS_REGION", "us-west-1"))
        for tour_id in validated_ids:
            try:
                sfn.start_execution(
                    stateMachineArn=sf_arn,
                    name=f"s1-{run_id[:8]}-{tour_id[:8]}",
                    input=json.dumps({
                        "tour_id":    tour_id,
                        "run_id":     run_id,
                        "run_config": run_config_dict,
                    }),
                )
                started += 1
            except Exception as sf_err:
                logger.error("s1_sf_start_failed", tour_id=tour_id, run_id=run_id, error=str(sf_err))
                async with pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE silver_aa_internal.tour_content_versions
                        SET status='failed', failure_codes=$1, updated_at=NOW()
                        WHERE raw_tour_id=$2::uuid AND acp_run_id=$3::uuid
                    """, json.dumps([{"code": "SF_TRIGGER_FAILED", "detail": str(sf_err)}]),
                        tour_id, run_id)
                failed += 1

    logger.info("s1_run_created", run_id=run_id, total=len(validated_ids),
                started=started, failed=failed)
    return {
        "run_id":        run_id,
        "tour_count":    len(validated_ids),
        "started_count": started,
        "failed_count":  failed,
    }


# ── GET /runs ─────────────────────────────────────────────────────────────────

@router.get("/runs")
async def list_runs(
    request: Request,
    tenant=Depends(_get_tenant),
):
    """List acp_runs with per-run tour_content_versions counts."""
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                r.run_id,
                r.run_config,
                r.status,
                r.created_at,
                r.tour_count,
                COUNT(v.id)                                                     AS total_versions,
                COUNT(v.id) FILTER (WHERE v.status = 'published')              AS done_count,
                COUNT(v.id) FILTER (WHERE v.status = 'failed')                 AS failed_count
            FROM acp_shared.acp_runs r
            LEFT JOIN silver_aa_internal.tour_content_versions v
                ON v.acp_run_id = r.run_id
            GROUP BY r.run_id, r.run_config, r.status, r.created_at, r.tour_count
            ORDER BY r.created_at DESC
            LIMIT 20
        """)

    return {
        "data": [
            {
                "run_id":     str(r["run_id"]),
                "run_config": (r["run_config"] if isinstance(r["run_config"], dict)
                               else json.loads(r["run_config"] or "{}")),
                "status":     r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "total_tours":  r["tour_count"],
                "done_count":   r["done_count"],
                "failed_count": r["failed_count"],
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ── GET /run/{run_id}/stream ──────────────────────────────────────────────────

async def _sse_generator(pool, run_id: str):
    """Async generator yielding SSE events for a run. Polls every 2s."""
    seen_statuses: dict[str, str] = {}
    start = asyncio.get_event_loop().time()
    last_heartbeat = start

    while True:
        now = asyncio.get_event_loop().time()

        if now - start > _SSE_TIMEOUT_S:
            yield f'data: {json.dumps({"event": "timeout", "run_id": run_id})}\n\n'
            return

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, raw_tour_id, status, quality_score, failure_codes
                    FROM silver_aa_internal.tour_content_versions
                    WHERE acp_run_id = $1::uuid
                """, run_id)
        except Exception as e:
            logger.error("s1_sse_poll_error", run_id=run_id, error=str(e))
            await asyncio.sleep(_SSE_POLL_INTERVAL)
            continue

        if not rows:
            await asyncio.sleep(_SSE_POLL_INTERVAL)
            continue

        # Emit only changed statuses
        for row in rows:
            tour_key = str(row["raw_tour_id"])
            new_status = row["status"]
            if seen_statuses.get(tour_key) != new_status:
                seen_statuses[tour_key] = new_status
                score = float(row["quality_score"]) if row["quality_score"] is not None else None
                codes = row["failure_codes"]
                error = codes[0].get("detail") if codes else None
                event = {
                    "tour_id":       tour_key,
                    "status":        new_status,
                    "quality_score": score,
                    "error":         error,
                }
                yield f"data: {json.dumps(event)}\n\n"

        all_terminal = all(r["status"] in _TERMINAL_STATUSES for r in rows)
        if all_terminal:
            done = sum(1 for r in rows if r["status"] == "published")
            failed = sum(1 for r in rows if r["status"] == "failed")
            summary = {
                "event":   "complete",
                "run_id":  run_id,
                "total":   len(rows),
                "done":    done,
                "failed":  failed,
            }
            yield f"data: {json.dumps(summary)}\n\n"
            return

        # Heartbeat
        if now - last_heartbeat >= _SSE_HEARTBEAT_S:
            yield ": heartbeat\n\n"
            last_heartbeat = now

        await asyncio.sleep(_SSE_POLL_INTERVAL)


@router.get("/run/{run_id}/stream")
async def stream_run(
    run_id:  str,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """SSE stream of per-tour progress for a run."""
    _safe_uuid(run_id, "run_id")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM acp_shared.acp_runs WHERE run_id = $1::uuid", run_id
        )
    if not exists:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return StreamingResponse(
        _sse_generator(pool, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── GET /tours/{raw_tour_id}/versions ─────────────────────────────────────────

@router.get("/tours/{raw_tour_id}/versions")
async def list_tour_versions(
    raw_tour_id: str,
    request:     Request,
    tenant=Depends(_get_tenant),
):
    """Return all content versions for a raw_tour, newest first."""
    _safe_uuid(raw_tour_id, "raw_tour_id")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        # 404 if raw_tour doesn't exist
        tour_exists = await conn.fetchval(
            "SELECT 1 FROM silver_aa_internal.raw_tours WHERE tour_id = $1::uuid",
            raw_tour_id,
        )
        if not tour_exists:
            raise HTTPException(status_code=404, detail=f"Tour {raw_tour_id} not found")

        rows = await conn.fetch("""
            SELECT id, raw_tour_id, acp_run_id, run_config, content,
                   quality_score, status, is_active, failure_codes,
                   created_at, updated_at
            FROM silver_aa_internal.tour_content_versions
            WHERE raw_tour_id = $1::uuid
            ORDER BY created_at DESC
        """, raw_tour_id)

    return {
        "raw_tour_id": raw_tour_id,
        "versions": [
            {
                "id":            str(r["id"]),
                "acp_run_id":    str(r["acp_run_id"]),
                "run_config":    (r["run_config"] if isinstance(r["run_config"], dict)
                                  else json.loads(r["run_config"] or "{}")),
                "content":       r["content"] if isinstance(r["content"], dict) else json.loads(r["content"] or "{}"),
                "quality_score": float(r["quality_score"]) if r["quality_score"] is not None else None,
                "status":        r["status"],
                "is_active":     r["is_active"],
                "failure_codes": r["failure_codes"] or [],
                "created_at":    r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at":    r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ── GET /tours/{raw_tour_id}/versions/compare ─────────────────────────────────

@router.get("/tours/{raw_tour_id}/versions/compare")
async def compare_tour_versions(
    raw_tour_id: str,
    v1:          str,
    v2:          str,
    request:     Request,
    tenant=Depends(_get_tenant),
):
    """
    Compare 2 tour_content_versions for the same raw_tour.
    GET /v1/tours/{raw_tour_id}/versions/compare?v1={version_id}&v2={version_id}
    PRD v1.2 AA-63.
    """
    _safe_uuid(raw_tour_id, "raw_tour_id")
    _safe_uuid(v1, "v1")
    _safe_uuid(v2, "v2")
    if v1 == v2:
        raise HTTPException(status_code=422, detail="v1 and v2 must be different version IDs")

    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text, acp_run_id::text, run_config, content,
                   quality_score, status, is_active, failure_codes,
                   created_at, updated_at
            FROM silver_aa_internal.tour_content_versions
            WHERE raw_tour_id = $1::uuid
              AND id = ANY($2::uuid[])
            """,
            raw_tour_id, [v1, v2],
        )

    if len(rows) < 2:
        missing = ({v1, v2} - {r["id"] for r in rows})
        raise HTTPException(
            status_code=404,
            detail=f"Version(s) not found for this tour: {missing}",
        )

    def _ser(row) -> dict:
        rc = row["run_config"]
        content = row["content"]
        return {
            "version_id":    row["id"],
            "acp_run_id":    row["acp_run_id"],
            "run_config":    (rc if isinstance(rc, dict) else json.loads(rc or "{}")),
            "quality_score": float(row["quality_score"]) if row["quality_score"] is not None else None,
            "status":        row["status"],
            "is_active":     row["is_active"],
            "failure_codes": list(row["failure_codes"]) if row["failure_codes"] else [],
            "preview_text":  (
                content if isinstance(content, dict) else json.loads(content or "{}")
            ).get("aa_summary", "")[:300],
            "created_at":    row["created_at"].isoformat() if row["created_at"] else None,
        }

    v_map = {r["id"]: _ser(r) for r in rows}
    s1, s2 = v_map[v1], v_map[v2]

    score_delta = None
    if s1["quality_score"] is not None and s2["quality_score"] is not None:
        score_delta = round(s2["quality_score"] - s1["quality_score"], 2)

    fc1 = set(s1["failure_codes"])
    fc2 = set(s2["failure_codes"])
    model1 = s1["run_config"].get("model_id") or s1["run_config"].get("model")
    model2 = s2["run_config"].get("model_id") or s2["run_config"].get("model")

    return {
        "raw_tour_id": raw_tour_id,
        "v1": s1,
        "v2": s2,
        "diff": {
            "score_delta":              score_delta,
            "failure_codes_only_in_v1": sorted(fc1 - fc2),
            "failure_codes_only_in_v2": sorted(fc2 - fc1),
            "failure_codes_fixed":      sorted(fc1 - fc2),
            "failure_codes_new":        sorted(fc2 - fc1),
            "model_changed":            model1 != model2 if model1 and model2 else None,
            "model_v1":                 model1,
            "model_v2":                 model2,
        },
    }


# ── PATCH /versions/{version_id}/activate ────────────────────────────────────

@router.patch("/versions/{version_id}/activate")
async def activate_version(
    version_id: str,
    request:    Request,
    tenant=Depends(_get_tenant),
):
    """
    Activate a specific content version.
    Deactivates all other versions for the same raw_tour in one transaction.
    """
    _safe_uuid(version_id, "version_id")
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                SELECT id, raw_tour_id FROM silver_aa_internal.tour_content_versions
                WHERE id = $1::uuid
            """, version_id)
            if not row:
                raise HTTPException(status_code=404, detail=f"Version {version_id} not found")

            raw_tour_id = str(row["raw_tour_id"])

            # Deactivate all versions for this tour
            await conn.execute("""
                UPDATE silver_aa_internal.tour_content_versions
                SET is_active = FALSE, updated_at = NOW()
                WHERE raw_tour_id = $1::uuid
            """, raw_tour_id)

            # Activate + publish the target version
            await conn.execute("""
                UPDATE silver_aa_internal.tour_content_versions
                SET is_active = TRUE, status = 'published', updated_at = NOW()
                WHERE id = $1::uuid
            """, version_id)

    logger.info("s1_version_activated", version_id=version_id, raw_tour_id=raw_tour_id)
    return {"version_id": version_id, "raw_tour_id": raw_tour_id, "activated": True}
