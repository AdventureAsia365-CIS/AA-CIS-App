"""
api/routers/admin_produce.py — AA-405: manual N7 Produce -> N8 Deliver/Learn trigger.

STEP 0 recon (docs/implementation-notes/AA-405.md) confirmed: `run_slot_production()`
(slot_runner.py) had zero real callers outside tests; `acp_shared.acp_v2_slots` had never
been populated by any live route (`preview-slotgrid`'s own docstring says it never
persists); the whole N8 packet lifecycle (`packets.py`) also had zero real callers. This
router is the first live wiring of N6 persist (`allocate_month_from_db` ->
`create_weekly_produce_run` -> `persist_slot_grid`) + N7 run (`run_slot_production` per due
slot) + N8 packet assemble (`create_packet`/`assemble_packet`/`maybe_mark_packet_ready`),
plus a Gate C approve endpoint wired to the existing `trust_ramp.confirm_ramp_transition()`
(AA-365) — no new gate logic invented here.

Async design (confirmed live, 15/08/2026): the browser -> Vercel `/api/admin` proxy ->
API Gateway (owq9as3wjl) -> ECS path has a hard 29s integration timeout on API Gateway
that cannot be raised. `run_slot_production()` makes several real Bedrock calls per piece
(research/outline/draft/adapt/FAQ + 9 gates, +up to 3 repair rounds each a real Sonnet
call) x up to 3 pieces/slot — easily over 29s for even one slot. `allocate_month_from_db`/
`create_weekly_produce_run`/`persist_slot_grid` are DB+in-memory only, no LLM calls, and
genuinely fast. So `POST /admin/produce/run` does the fast N6 part synchronously and
returns a `run_id` immediately (202), then runs the slow per-slot production loop as a
FastAPI `BackgroundTask` — same shape as AA-223's `pipeline_jobs` 202+poll pattern, reusing
`acp_shared.acp_v2_runs.status` (allocated/producing/completed/failed) as the job-status
field instead of a new table, since that field already exists and was otherwise dead
(nothing in this codebase ever advanced it past `producing` before this).
"""
from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel

from api.routers.admin import verify_admin_secret
from services.acp_planning.allocator import (
    allocate_month_from_db,
    create_weekly_produce_run,
    fetch_due_slots,
    mark_slot_status,
    persist_slot_grid,
)
from services.acp_planning.models import QuarterPlanNotApprovedError, Slot
from services.acp_planning.runway import runway_map
from services.acp_planning.tenant_config import TenantNotFoundError, fetch_tenant_planning_config
from services.acp_produce.packets import (
    PublishModeBlockedError,
    assemble_packet,
    create_packet,
    maybe_mark_packet_ready,
)
from services.acp_produce.trust_ramp import BofuVetoBlockedError, confirm_ramp_transition

# services.acp_produce.slot_runner is deliberately NOT imported at module level here — it chains
# to pipeline.py -> rule_adapter.py -> api.services.acp_post_processor, and importing anything
# under api.* triggers api/__init__.py's `from .main import app`, which imports THIS router,
# which would try to import slot_runner again while it's still mid-import (partially initialized)
# -> ImportError. This router is the first place under api.routers.* to import slot_runner at
# all, which is why this cycle never surfaced before. Deferred to the one call site instead
# (see _produce_slots_background below) — the cycle only exists at import time, not at call time.

logger = structlog.get_logger()
router = APIRouter(prefix="/admin/produce", tags=["admin-produce"])


class RunRequest(BaseModel):
    tenant_id: str
    year: int
    week: int  # 1-4, SlotGrid week-of-month numbering — matches acp_v2_runs/acp_v2_slots schema
    month: Optional[int] = None  # defaults to the current calendar month if omitted


async def _mark_run_status(pool, run_id: str, status: str) -> None:
    completed_clause = ", completed_at = now()" if status in ("completed", "failed") else ""
    await pool.execute(
        f"UPDATE acp_shared.acp_v2_runs SET status = $1{completed_clause} WHERE run_id = $2",
        status, run_id,
    )


async def _get_or_create_packet(conn, tenant_id: str, year: int, week: int) -> str:
    """create_packet() has no ON CONFLICT — a packet for (tenant_id, year, week) may already
    exist from a prior run against the same week, so select-first rather than let the
    UNIQUE constraint (migration 094) raise."""
    existing = await conn.fetchval(
        "SELECT packet_id FROM acp_deliver.packets WHERE tenant_id = $1 AND year = $2 AND week = $3",
        tenant_id, year, week,
    )
    if existing:
        return str(existing)
    return await create_packet(conn, tenant_id, year, week)


async def _produce_slots_background(
    pool, due_slots: list[Slot], tenant_id: str, year: int, week: int, run_id: str, market: str,
) -> None:
    """The slow part — real per-slot production (multiple Bedrock calls per piece), run outside
    the request/response cycle since API Gateway's 29s integration timeout can't survive it (see
    module docstring). Advances acp_v2_runs.status to 'completed'/'failed' when done.

    Per-slot failure handling (Nghiep, 15/08, live-verify finding): a slot is only marked
    'produced' (mark_slot_status) once run_slot_production() actually returns — an unexpected
    exception for one slot is logged and the slot is left 'due' so a re-trigger of this run/week
    picks it up again, instead of either (a) silently marking a slot produced when it didn't
    finish, or (b) letting one slot's exception abort every other due slot in the batch (matches
    this codebase's existing L6 "hold visible, never silent, never abort the batch" convention —
    see pipeline.py/gates.py). The run's overall status is only 'failed' if every due slot failed;
    'completed' if at least one slot was actually attempted to completion (whether its pieces
    passed or held)."""
    from services.acp_produce.slot_runner import run_slot_production  # see module-level comment

    passed_piece_ids: list[str] = []
    slot_failures = 0
    try:
        async with pool.acquire() as conn:
            for slot in due_slots:
                try:
                    pieces = await run_slot_production(conn, pool, tenant_id, slot, run_id, market)
                except Exception as exc:
                    slot_failures += 1
                    logger.error(
                        "produce_run_slot_failed", run_id=run_id, slot_id=slot.slot_id, error=str(exc),
                    )
                    continue  # left 'due' — not marked produced, eligible for retry

                await mark_slot_status(pool, slot.slot_id, "produced")
                passed_piece_ids.extend(p.piece_id for p in pieces if p.status == "passed")
                logger.info(
                    "produce_run_slot_done", run_id=run_id, slot_id=slot.slot_id,
                    piece_count=len(pieces), passed=sum(1 for p in pieces if p.status == "passed"),
                )

            if passed_piece_ids:
                packet_id = await _get_or_create_packet(conn, tenant_id, year, week)
                await assemble_packet(conn, packet_id, passed_piece_ids)
                became_ready = await maybe_mark_packet_ready(conn, packet_id)
                logger.info(
                    "produce_run_packet_assembled", run_id=run_id, packet_id=packet_id,
                    piece_count=len(passed_piece_ids), became_ready=became_ready,
                )

        final_status = "failed" if due_slots and slot_failures == len(due_slots) else "completed"
        await _mark_run_status(pool, run_id, final_status)
    except Exception as exc:
        # Catastrophic failure outside the per-slot loop (e.g. connection lost, packet assemble
        # crashed) — the whole run is failed, not just one slot.
        logger.error("produce_run_failed", run_id=run_id, tenant_id=tenant_id, error=str(exc))
        await _mark_run_status(pool, run_id, "failed")


@router.post("/run", status_code=202)
async def trigger_produce_run(
    body: RunRequest, request: Request, background_tasks: BackgroundTasks,
    x_admin_secret: str = Header(None),
):
    """Kicks off the real N6 persist -> N7 produce -> N8 assemble chain for one tenant/week.
    The fast part (allocate/create-run/persist-slots) runs synchronously and is reflected in
    the response; the slow per-slot LLM production loop runs as a BackgroundTask — poll
    GET /admin/produce/run/{run_id} for the result."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    try:
        tenant_uuid = UUID(body.tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid tenant_id: {body.tenant_id!r}")

    try:
        config = await fetch_tenant_planning_config(tenant_uuid, pool)
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail=f"Unknown tenant_id: {body.tenant_id}")

    month = body.month or date.today().month
    runway = await runway_map(tenant_uuid, body.year, config.markets, pool)

    try:
        grid = await allocate_month_from_db(
            tenant_uuid, body.year, month, config.channels, config.capacity_posts_per_week,
            runway, config.markets[0], pool,
        )
    except QuarterPlanNotApprovedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    tenant_id_str = str(tenant_uuid)
    run_id = await create_weekly_produce_run(pool, tenant_id_str, body.year, body.week)
    await persist_slot_grid(pool, run_id, tenant_id_str, body.week, grid)
    await _mark_run_status(pool, run_id, "producing")

    due_slots = await fetch_due_slots(pool, run_id)

    background_tasks.add_task(
        _produce_slots_background,
        pool, due_slots, tenant_id_str, body.year, body.week, run_id, config.markets[0],
    )

    logger.info(
        "produce_run_triggered", run_id=run_id, tenant_id=tenant_id_str,
        year=body.year, week=body.week, due_slot_count=len(due_slots),
    )

    return {
        "run_id": run_id,
        "tenant_id": tenant_id_str,
        "year": body.year,
        "week": body.week,
        "due_slot_count": len(due_slots),
        "status": "producing",
    }


@router.get("/run/{run_id}")
async def get_produce_run(run_id: str, request: Request, x_admin_secret: str = Header(None)):
    """Poll target — returns current status plus a slots/pieces/packet summary. Pieces and
    packets are matched to the run the same way the reset script's own STEP 0 recon confirmed:
    pieces carry run_id directly; packets do not (migration 094), so the packet is looked up by
    (tenant_id, year, week) instead."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    run_row = await pool.fetchrow(
        """
        SELECT run_id::text, tenant_id, year, week, status, created_at, completed_at
        FROM acp_shared.acp_v2_runs WHERE run_id = $1::uuid
        """,
        run_id,
    )
    if run_row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    slots = await pool.fetch(
        "SELECT slot_id, channel, kind, status FROM acp_shared.acp_v2_slots WHERE run_id = $1::uuid ORDER BY slot_id",
        run_id,
    )
    pieces = await pool.fetch(
        """
        SELECT piece_id, channel, status, held_reason, repair_count
        FROM acp_deliver.pieces WHERE run_id = $1::uuid ORDER BY piece_id
        """,
        run_id,
    )
    packet_row = await pool.fetchrow(
        "SELECT packet_id::text, status, publish_mode FROM acp_deliver.packets "
        "WHERE tenant_id = $1 AND year = $2 AND week = $3",
        run_row["tenant_id"], run_row["year"], run_row["week"],
    )

    return {
        "run_id": run_row["run_id"],
        "tenant_id": run_row["tenant_id"],
        "year": run_row["year"],
        "week": run_row["week"],
        "status": run_row["status"],
        "created_at": run_row["created_at"].isoformat() if run_row["created_at"] else None,
        "completed_at": run_row["completed_at"].isoformat() if run_row["completed_at"] else None,
        "slots": [dict(s) for s in slots],
        "pieces": [dict(p) for p in pieces],
        "packet": dict(packet_row) if packet_row else None,
    }


@router.get("/packets")
async def list_pending_packets(request: Request, x_admin_secret: str = Header(None)):
    """Gate C review queue — packets with status='ready', not yet delivered. Read-only; the
    approve action below calls the real trust_ramp.confirm_ramp_transition() (AA-365), no gate
    logic is reimplemented here."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    rows = await pool.fetch(
        """
        SELECT p.packet_id::text, p.tenant_id, p.year, p.week, p.status, p.publish_mode,
               (SELECT count(*) FROM acp_deliver.pieces pc WHERE pc.packet_id = p.packet_id) AS piece_count
        FROM acp_deliver.packets p
        WHERE p.status = 'ready'
        ORDER BY p.created_at DESC
        """
    )
    return [dict(r) for r in rows]


class GateCApproveRequest(BaseModel):
    mode: str  # 'propose_only' | 'approve_to_publish' | 'veto_window_auto'
    actor: str


@router.post("/packets/{packet_id}/gate-c/approve")
async def approve_gate_c(
    packet_id: str, body: GateCApproveRequest, request: Request, x_admin_secret: str = Header(None),
):
    """Approves a ramp transition for `packet_id`. Thin wrapper over
    trust_ramp.confirm_ramp_transition() — that function already writes the decision-log entry
    (acp_shared.audit_log) whether it succeeds or is blocked."""
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    packet_row = await pool.fetchrow(
        "SELECT tenant_id FROM acp_deliver.packets WHERE packet_id = $1::uuid", packet_id,
    )
    if packet_row is None:
        raise HTTPException(status_code=404, detail=f"Packet {packet_id} not found")

    async with pool.acquire() as conn:
        try:
            await confirm_ramp_transition(
                conn, packet_id=packet_id, tenant_id=packet_row["tenant_id"],
                mode=body.mode, actor=body.actor,
            )
        except BofuVetoBlockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PublishModeBlockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return {"packet_id": packet_id, "mode": body.mode, "status": "transitioned"}


__all__ = ["router"]
