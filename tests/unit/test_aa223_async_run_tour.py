"""AA-223 — async run-tour (202 + job poll). ADR-2026-016.

Covers the job-lifecycle repo (jobs_repo) and the new admin_pipeline endpoints
WITHOUT touching the DB or Bedrock:
  * jobs_repo: asyncpg.connect is patched to a fake AsyncMock conn.
  * _run_tour_job: _run_tour_safe + mark_* are patched — pins all 4 branches
    (success / soft-fail / hard-fail-None / exception).
  * endpoints: verify_admin_secret patched no-op, coroutines called directly.

_run_tour_safe SWALLOWS the final failure and returns None (retries exhausted),
so result is None ⇒ mark_failed; a returned dict ⇒ mark_succeeded (version_id may
be None for a soft-fail). These tests pin exactly that contract.
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.routers import admin_pipeline, jobs_repo

FAKE_UUID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _db_url(monkeypatch):
    # jobs_repo reads os.environ["DATABASE_URL"] before the (patched) connect.
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")


def _fake_conn():
    """AsyncMock conn — fetchval/execute/fetchrow/close are all awaitable."""
    return AsyncMock()


def _req(**over):
    base = dict(tour_id=FAKE_UUID, batch_id="b-1", tenant_id="aa_internal", model_tier="haiku")
    base.update(over)
    return admin_pipeline.TourRunRequest(**base)


# ── jobs_repo: create_job / find_active_duplicate / sweep ──────────────────────

@pytest.mark.asyncio
async def test_create_job_roundtrip():
    conn = _fake_conn()
    conn.fetchval.return_value = uuid.UUID(FAKE_UUID)
    with patch("api.routers.jobs_repo.asyncpg.connect", AsyncMock(return_value=conn)):
        jid = await jobs_repo.create_job({"tour_id": FAKE_UUID}, "aa_internal")
    assert jid == FAKE_UUID
    sql = conn.fetchval.call_args.args[0]
    assert "INSERT INTO shared.pipeline_jobs" in sql
    assert "'queued'" in sql
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_active_duplicate_match():
    conn = _fake_conn()
    conn.fetchval.return_value = uuid.UUID(FAKE_UUID)
    with patch("api.routers.jobs_repo.asyncpg.connect", AsyncMock(return_value=conn)):
        res = await jobs_repo.find_active_duplicate(
            {"tour_id": FAKE_UUID, "model_tier": "haiku", "batch_id": "b-1"}
        )
    assert res == FAKE_UUID
    # the 3 JSONB text keys are passed as params in order
    assert conn.fetchval.call_args.args[1:] == (FAKE_UUID, "haiku", "b-1")


@pytest.mark.asyncio
async def test_find_active_duplicate_none():
    conn = _fake_conn()
    conn.fetchval.return_value = None
    with patch("api.routers.jobs_repo.asyncpg.connect", AsyncMock(return_value=conn)):
        res = await jobs_repo.find_active_duplicate(
            {"tour_id": FAKE_UUID, "model_tier": "sonnet", "batch_id": "b-2"}
        )
    assert res is None


@pytest.mark.asyncio
async def test_sweep_interrupted_parses_count():
    conn = _fake_conn()
    conn.execute.return_value = "UPDATE 3"
    with patch("api.routers.jobs_repo.asyncpg.connect", AsyncMock(return_value=conn)):
        n = await jobs_repo.sweep_interrupted()
    assert n == 3


@pytest.mark.asyncio
async def test_mark_interrupted_writes_status_and_reason():
    """AA-295: single-job interrupt marker (used from the CancelledError handlers below),
    complementary to the bulk sweep_interrupted() above — same status value, immediate
    instead of once-per-boot/heartbeat-staleness-gated."""
    conn = _fake_conn()
    with patch("api.routers.jobs_repo.asyncpg.connect", AsyncMock(return_value=conn)):
        await jobs_repo.mark_interrupted("job-9", "cancelled (deploy/shutdown)")
    sql = conn.execute.call_args.args[0]
    assert "status='interrupted'" in sql
    assert "error=$2" in sql
    assert conn.execute.call_args.args[1:] == ("job-9", "cancelled (deploy/shutdown)")
    conn.close.assert_awaited_once()


# ── _run_tour_job: 4 branches ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_tour_job_success():
    req = _req()
    with patch("api.routers.admin_pipeline._run_tour_safe",
               AsyncMock(return_value={"version_id": FAKE_UUID})), \
         patch("api.routers.jobs_repo.mark_running", AsyncMock()) as mr, \
         patch("api.routers.jobs_repo.mark_succeeded", AsyncMock()) as ms, \
         patch("api.routers.jobs_repo.mark_failed", AsyncMock()) as mf:
        await admin_pipeline._run_tour_job("job-1", req)
    mr.assert_awaited_once_with("job-1")
    ms.assert_awaited_once_with("job-1", FAKE_UUID, None)
    mf.assert_not_called()


@pytest.mark.asyncio
async def test_run_tour_job_soft_fail():
    """Dict returned but version_id None → succeeded with result_version_id NULL."""
    req = _req()
    with patch("api.routers.admin_pipeline._run_tour_safe",
               AsyncMock(return_value={"version_id": None})), \
         patch("api.routers.jobs_repo.mark_running", AsyncMock()), \
         patch("api.routers.jobs_repo.mark_succeeded", AsyncMock()) as ms, \
         patch("api.routers.jobs_repo.mark_failed", AsyncMock()) as mf:
        await admin_pipeline._run_tour_job("job-2", req)
    ms.assert_awaited_once_with("job-2", None, None)
    mf.assert_not_called()


@pytest.mark.asyncio
async def test_run_tour_job_hard_fail_none():
    """_run_tour_safe swallowed final failure → returned None → mark_failed."""
    req = _req()
    with patch("api.routers.admin_pipeline._run_tour_safe", AsyncMock(return_value=None)), \
         patch("api.routers.jobs_repo.mark_running", AsyncMock()), \
         patch("api.routers.jobs_repo.mark_succeeded", AsyncMock()) as ms, \
         patch("api.routers.jobs_repo.mark_failed", AsyncMock()) as mf:
        await admin_pipeline._run_tour_job("job-3", req)
    mf.assert_awaited_once()
    assert mf.call_args.args[0] == "job-3"
    ms.assert_not_called()


@pytest.mark.asyncio
async def test_run_tour_job_exception():
    req = _req()
    with patch("api.routers.admin_pipeline._run_tour_safe",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("api.routers.jobs_repo.mark_running", AsyncMock()), \
         patch("api.routers.jobs_repo.mark_succeeded", AsyncMock()) as ms, \
         patch("api.routers.jobs_repo.mark_failed", AsyncMock()) as mf:
        await admin_pipeline._run_tour_job("job-4", req)
    mf.assert_awaited_once()
    assert "RuntimeError" in mf.call_args.args[1]
    ms.assert_not_called()


# ── endpoints: POST /run-tour-async + GET /jobs/{id} ───────────────────────────

@pytest.mark.asyncio
async def test_run_tour_async_endpoint_202():
    req = _req()
    with patch("api.routers.admin_pipeline.verify_admin_secret"), \
         patch("api.routers.jobs_repo.find_active_duplicate", AsyncMock(return_value=None)), \
         patch("api.routers.jobs_repo.create_job", AsyncMock(return_value="job-uuid")) as cj, \
         patch("api.routers.admin_pipeline._run_tour_job", MagicMock()), \
         patch("api.routers.admin_pipeline.asyncio.create_task", MagicMock()) as ct:
        resp = await admin_pipeline.run_tour_async(req, x_admin_secret="secret")
    assert resp.status_code == 202
    body = json.loads(resp.body)
    assert body["job_id"] == "job-uuid"
    assert body["status"] == "queued"
    assert body["poll_url"] == "/admin/jobs/job-uuid"
    cj.assert_awaited_once()
    ct.assert_called_once()  # background job spawned


@pytest.mark.asyncio
async def test_run_tour_async_dedup():
    req = _req()
    with patch("api.routers.admin_pipeline.verify_admin_secret"), \
         patch("api.routers.jobs_repo.find_active_duplicate", AsyncMock(return_value="existing-uuid")), \
         patch("api.routers.jobs_repo.create_job", AsyncMock()) as cj, \
         patch("api.routers.admin_pipeline._run_tour_job", MagicMock()), \
         patch("api.routers.admin_pipeline.asyncio.create_task", MagicMock()) as ct:
        resp = await admin_pipeline.run_tour_async(req, x_admin_secret="secret")
    assert resp.status_code == 202
    body = json.loads(resp.body)
    assert body["job_id"] == "existing-uuid"
    assert body["dedup"] is True
    cj.assert_not_called()   # no new job
    ct.assert_not_called()   # no background spawn


@pytest.mark.asyncio
async def test_get_job_404():
    with patch("api.routers.admin_pipeline.verify_admin_secret"), \
         patch("api.routers.jobs_repo.get_job", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as ei:
            await admin_pipeline.get_run_tour_job("missing", x_admin_secret="secret")
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_get_job_200():
    job = {"id": FAKE_UUID, "status": "succeeded", "result_version_id": None}
    with patch("api.routers.admin_pipeline.verify_admin_secret"), \
         patch("api.routers.jobs_repo.get_job", AsyncMock(return_value=job)):
        res = await admin_pipeline.get_run_tour_job(FAKE_UUID, x_admin_secret="secret")
    assert res == job


# ── AA-250 B2: current_stage (migration 076) ────────────────────────────────────

@pytest.mark.asyncio
async def test_update_stage_writes_stage_and_heartbeat():
    conn = _fake_conn()
    with patch("api.routers.jobs_repo.asyncpg.connect", AsyncMock(return_value=conn)):
        await jobs_repo.update_stage(FAKE_UUID, "brand_audit")
    sql = conn.execute.call_args.args[0]
    assert "current_stage=$2" in sql
    assert "heartbeat_at=now()" in sql
    assert conn.execute.call_args.args[1:] == (FAKE_UUID, "brand_audit")
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_job_selects_and_returns_current_stage():
    conn = _fake_conn()
    conn.fetchrow.return_value = {
        "id": uuid.UUID(FAKE_UUID), "job_type": "run_tour", "status": "running",
        "result_version_id": None, "pipeline_run_id": None, "error": None,
        "current_stage": "llm_judge",
        "created_at": None, "started_at": None, "finished_at": None, "heartbeat_at": None,
    }
    with patch("api.routers.jobs_repo.asyncpg.connect", AsyncMock(return_value=conn)):
        job = await jobs_repo.get_job(FAKE_UUID)
    sql = conn.fetchrow.call_args.args[0]
    assert "current_stage" in sql
    assert job["current_stage"] == "llm_judge"


@pytest.mark.asyncio
async def test_get_job_current_stage_null_before_first_stage_report():
    """A job that hasn't streamed a node yet (queued, or created pre-migration-076)."""
    conn = _fake_conn()
    conn.fetchrow.return_value = {
        "id": uuid.UUID(FAKE_UUID), "job_type": "run_tour", "status": "queued",
        "result_version_id": None, "pipeline_run_id": None, "error": None,
        "current_stage": None,
        "created_at": None, "started_at": None, "finished_at": None, "heartbeat_at": None,
    }
    with patch("api.routers.jobs_repo.asyncpg.connect", AsyncMock(return_value=conn)):
        job = await jobs_repo.get_job(FAKE_UUID)
    assert job["current_stage"] is None


@pytest.mark.asyncio
async def test_run_tour_job_passes_job_id_to_run_tour_safe():
    """AA-250 B2 wiring guard: _run_tour_job must thread job_id through so
    _execute_run_tour can build the on_stage callback (jobs_repo.update_stage)."""
    req = _req()
    with patch("api.routers.admin_pipeline._run_tour_safe",
               AsyncMock(return_value={"version_id": FAKE_UUID})) as rts, \
         patch("api.routers.jobs_repo.mark_running", AsyncMock()), \
         patch("api.routers.jobs_repo.mark_succeeded", AsyncMock()), \
         patch("api.routers.jobs_repo.mark_failed", AsyncMock()):
        await admin_pipeline._run_tour_job("job-5", req)
    rts.assert_awaited_once_with(req, job_id="job-5")


# ── AA-295: explicit CancelledError handling (rolling-deploy shutdown) ─────────

@pytest.mark.asyncio
async def test_run_tour_job_cancelled_marks_interrupted_and_reraises():
    """A rolling-deploy SIGTERM (or any task.cancel()) mid-run must NOT be silently
    swallowed by the outer `except Exception` — it has to hit mark_interrupted and
    still propagate, or the caller/asyncio loses correct cancellation semantics."""
    req = _req()
    with patch("api.routers.admin_pipeline._run_tour_safe",
               AsyncMock(side_effect=asyncio.CancelledError())), \
         patch("api.routers.jobs_repo.mark_running", AsyncMock()) as mr, \
         patch("api.routers.jobs_repo.mark_interrupted", AsyncMock()) as mi, \
         patch("api.routers.jobs_repo.mark_succeeded", AsyncMock()) as ms, \
         patch("api.routers.jobs_repo.mark_failed", AsyncMock()) as mf:
        with pytest.raises(asyncio.CancelledError):
            await admin_pipeline._run_tour_job("job-6", req)
    mr.assert_awaited_once_with("job-6")
    mi.assert_awaited_once()
    assert mi.call_args.args[0] == "job-6"
    ms.assert_not_called()
    mf.assert_not_called()


@pytest.mark.asyncio
async def test_run_tour_job_mark_running_inside_try_still_succeeds():
    """Regression guard: moving mark_running() inside the try (to catch its own
    CancelledError too) must not change the normal success path's behavior."""
    req = _req()
    with patch("api.routers.admin_pipeline._run_tour_safe",
               AsyncMock(return_value={"version_id": FAKE_UUID})), \
         patch("api.routers.jobs_repo.mark_running", AsyncMock()) as mr, \
         patch("api.routers.jobs_repo.mark_succeeded", AsyncMock()) as ms, \
         patch("api.routers.jobs_repo.mark_interrupted", AsyncMock()) as mi, \
         patch("api.routers.jobs_repo.mark_failed", AsyncMock()) as mf:
        await admin_pipeline._run_tour_job("job-7", req)
    mr.assert_awaited_once_with("job-7")
    ms.assert_awaited_once_with("job-7", FAKE_UUID, None)
    mi.assert_not_called()
    mf.assert_not_called()


# ── AA-295: same fix, _revalidate_job (AA-234's job wrapper) ───────────────────

@pytest.mark.asyncio
async def test_revalidate_job_success():
    """No pre-existing unit test called _revalidate_job directly (only _revalidate_tour,
    in test_aa293_revalidate_jsonb_codec.py) — this is also the regression guard for
    mark_running() now living inside the try."""
    result = {"revalidate_passed": True}
    with patch("api.routers.admin_pipeline._revalidate_tour", AsyncMock(return_value=result)), \
         patch("api.routers.jobs_repo.mark_running", AsyncMock()) as mr, \
         patch("api.routers.jobs_repo.mark_succeeded", AsyncMock()) as ms, \
         patch("api.routers.jobs_repo.mark_interrupted", AsyncMock()) as mi, \
         patch("api.routers.jobs_repo.mark_failed", AsyncMock()) as mf:
        await admin_pipeline._revalidate_job("job-8", "content-1")
    mr.assert_awaited_once_with("job-8")
    ms.assert_awaited_once_with("job-8", "content-1", None)
    mi.assert_not_called()
    mf.assert_not_called()


@pytest.mark.asyncio
async def test_revalidate_job_cancelled_marks_interrupted_and_reraises():
    with patch("api.routers.admin_pipeline._revalidate_tour",
               AsyncMock(side_effect=asyncio.CancelledError())), \
         patch("api.routers.jobs_repo.mark_running", AsyncMock()) as mr, \
         patch("api.routers.jobs_repo.mark_interrupted", AsyncMock()) as mi, \
         patch("api.routers.jobs_repo.mark_succeeded", AsyncMock()) as ms, \
         patch("api.routers.jobs_repo.mark_failed", AsyncMock()) as mf:
        with pytest.raises(asyncio.CancelledError):
            await admin_pipeline._revalidate_job("job-9", "content-2")
    mr.assert_awaited_once_with("job-9")
    mi.assert_awaited_once()
    assert mi.call_args.args[0] == "job-9"
    ms.assert_not_called()
    mf.assert_not_called()
