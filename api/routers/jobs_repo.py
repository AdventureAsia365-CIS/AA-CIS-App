"""AA-223 / ADR-2026-016 — pipeline_jobs repo (async run-tour job lifecycle).

Thin asyncpg helpers over shared.pipeline_jobs. Each function opens/closes its
own asyncpg.connect(os.environ["DATABASE_URL"]) — the SAME pattern as
admin_pipeline._execute_run_tour (NOT the app pool) so behaviour is uniform with
the existing background executor.

Lifecycle: queued -> running -> succeeded | failed | interrupted.
PK + result_version_id + pipeline_run_id are all UUID (see migration 071).
pipeline_run_id is always NULL in this phase — kept for a later wiring.
"""

import json
import os

import asyncpg


async def create_job(request: dict, tenant: str | None) -> str:
    """Insert a queued job, return str(id)."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        job_id = await conn.fetchval(
            "INSERT INTO shared.pipeline_jobs (job_type, status, request, tenant) "
            "VALUES ('run_tour', 'queued', $1::jsonb, $2) RETURNING id",
            json.dumps(request),
            tenant,
        )
        return str(job_id)
    finally:
        await conn.close()


async def mark_running(job_id: str) -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            "UPDATE shared.pipeline_jobs "
            "SET status='running', started_at=now(), heartbeat_at=now() "
            "WHERE id=$1::uuid",
            job_id,
        )
    finally:
        await conn.close()


async def mark_succeeded(job_id: str, version_id: str | None, pipeline_run_id: str | None) -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            "UPDATE shared.pipeline_jobs "
            "SET status='succeeded', result_version_id=$2::uuid, pipeline_run_id=$3::uuid, "
            "    finished_at=now(), heartbeat_at=now() "
            "WHERE id=$1::uuid",
            job_id,
            version_id,
            pipeline_run_id,
        )
    finally:
        await conn.close()


async def mark_failed(job_id: str, error: str) -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            "UPDATE shared.pipeline_jobs "
            "SET status='failed', error=$2, finished_at=now(), heartbeat_at=now() "
            "WHERE id=$1::uuid",
            job_id,
            error,
        )
    finally:
        await conn.close()


async def get_job(job_id: str) -> dict | None:
    """Return a JSON-safe dict (UUID->str, timestamp->isoformat) or None."""
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        row = await conn.fetchrow(
            "SELECT id, job_type, status, result_version_id, pipeline_run_id, error, "
            "       created_at, started_at, finished_at, heartbeat_at "
            "FROM shared.pipeline_jobs WHERE id=$1::uuid",
            job_id,
        )
        if row is None:
            return None

        def _ts(v):
            return v.isoformat() if v is not None else None

        def _uid(v):
            return str(v) if v is not None else None

        return {
            "id":                _uid(row["id"]),
            "job_type":          row["job_type"],
            "status":            row["status"],
            "result_version_id": _uid(row["result_version_id"]),
            "pipeline_run_id":   _uid(row["pipeline_run_id"]),
            "error":             row["error"],
            "created_at":        _ts(row["created_at"]),
            "started_at":        _ts(row["started_at"]),
            "finished_at":       _ts(row["finished_at"]),
            "heartbeat_at":      _ts(row["heartbeat_at"]),
        }
    finally:
        await conn.close()


async def find_active_duplicate(request: dict) -> str | None:
    """Job-tier idempotency guard: an in-flight job for the same
    (tour_id, model_tier, batch_id) triple. request->> returns text, so compare
    against text params directly. IS NOT DISTINCT FROM makes NULL batch_id match.
    Returns str(id) of the newest active match, or None.
    """
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        dup_id = await conn.fetchval(
            "SELECT id FROM shared.pipeline_jobs "
            "WHERE status IN ('queued', 'running') "
            "  AND request->>'tour_id'    = $1 "
            "  AND request->>'model_tier' = $2 "
            "  AND request->>'batch_id'   IS NOT DISTINCT FROM $3 "
            "ORDER BY created_at DESC LIMIT 1",
            request.get("tour_id"),
            request.get("model_tier"),
            request.get("batch_id"),
        )
        return str(dup_id) if dup_id is not None else None
    finally:
        await conn.close()


async def sweep_interrupted() -> int:
    """Mark orphaned running jobs (stale/absent heartbeat) as interrupted.
    Called once at startup to recover jobs left dangling by an ECS restart.
    Returns the number of rows affected.
    """
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        result = await conn.execute(
            "UPDATE shared.pipeline_jobs "
            "SET status='interrupted', finished_at=now() "
            "WHERE status='running' "
            "  AND (heartbeat_at IS NULL OR heartbeat_at < now() - interval '5 minutes')",
        )
        # asyncpg returns e.g. "UPDATE 3" — parse the trailing count.
        return int(result.split()[-1]) if result else 0
    finally:
        await conn.close()
