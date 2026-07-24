"""
services.acp_produce.reliability — sync-on-failure checkpoint wrapper for N7
slot production (AA-298 Nhóm 5).

The full N7 work function (C1/C2 DFS -> C3 brief -> apply_output_rules ->
E1-E5 generation -> F1-F9 gates -> checkpoint) is not assembled yet — that is
a separate, larger piece of work (see docs/implementation-notes/AA-298.md,
"ngoài scope"). What this module delivers now is the RELIABILITY WRAPPER
around whatever that work function ends up being: every exit path writes a
terminal checkpoint status, including asyncio.CancelledError (the AA-295
lesson this repo already learned the hard way once — see
api/routers/admin_pipeline.py's own CancelledError handling and
api/routers/jobs_repo.py's comment on it). A slot can never "disappear"
without a row saying what happened to it.

Checkpoint storage: services/acp_shared/stage_checkpoint.py (AA-107, real,
already in production for S4.2) — reused as-is, no new table. item_type is
free-text per existing convention (S4.2 social uses "social_tour"); N7 slots
use "produce_slot". run_id must already exist in acp_shared.acp_runs (FK) —
this module does not create runs, same as stage_checkpoint.py's existing
callers don't.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

import asyncpg
import structlog

from services.acp_shared.stage_checkpoint import (
    checkpoint_complete, checkpoint_failed, checkpoint_start,
)

logger = structlog.get_logger()

PRODUCE_SLOT_ITEM_TYPE = "produce_slot"

T = TypeVar("T")


async def run_produce_slot(
    db: asyncpg.Connection,
    run_id: str,
    slot_id: str,
    work_fn: Callable[[], Awaitable[T]],
) -> T:
    """Run `work_fn` (the actual slot-production pipeline) with a checkpoint
    recorded on every exit path. Never swallows an exception or a
    CancelledError — always re-raises after recording, so the caller (and
    asyncio itself, for cancellation) still sees the real outcome. The only
    thing this guarantees is that `acp_stage_checkpoints` never has a slot
    stuck showing 'running' because the process died before writing
    anything — that's what the sweeper (services/acp_produce/sweeper.py)
    exists to catch for cases even this can't cover (hard process kill,
    Spot reclaim mid-instruction, no chance to run any except/finally)."""
    await checkpoint_start(db, run_id, PRODUCE_SLOT_ITEM_TYPE, slot_id)
    try:
        result = await work_fn()
    except asyncio.CancelledError:
        # AA-295: never swallow CancelledError — asyncio needs it propagated
        # for cooperative shutdown to work at all. Record first, then re-raise.
        await checkpoint_failed(db, run_id, PRODUCE_SLOT_ITEM_TYPE, slot_id, "cancelled")
        logger.warning("produce_slot_cancelled", run_id=run_id, slot_id=slot_id)
        raise
    except Exception as e:
        await checkpoint_failed(db, run_id, PRODUCE_SLOT_ITEM_TYPE, slot_id, str(e))
        logger.error("produce_slot_failed", run_id=run_id, slot_id=slot_id, error=str(e))
        raise
    else:
        await checkpoint_complete(db, run_id, PRODUCE_SLOT_ITEM_TYPE, slot_id)
        return result
