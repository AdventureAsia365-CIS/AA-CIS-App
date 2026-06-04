"""Per-item checkpoint manager for ACP stage batch runs (AA-107).

Enables resume on spot interruption: before processing an item, call
checkpoint_start(); on success call checkpoint_complete(); on error call
checkpoint_failed(). Use get_incomplete_items() at batch start to skip
already-complete items.
"""
import asyncpg
import structlog

logger = structlog.get_logger(__name__)


async def checkpoint_start(
    db: asyncpg.Connection,
    run_id: str,
    item_type: str,
    item_id: str,
) -> None:
    await db.execute(
        """
        INSERT INTO acp_shared.acp_stage_checkpoints
            (run_id, item_type, item_id, status, updated_at)
        VALUES ($1, $2, $3, 'running', NOW())
        ON CONFLICT (run_id, item_type, item_id)
        DO UPDATE SET status = 'running', updated_at = NOW()
        """,
        run_id, item_type, item_id,
    )
    logger.info("checkpoint_start", run_id=run_id, item_type=item_type, item_id=item_id)


async def checkpoint_complete(
    db: asyncpg.Connection,
    run_id: str,
    item_type: str,
    item_id: str,
) -> None:
    await db.execute(
        """
        UPDATE acp_shared.acp_stage_checkpoints
        SET status = 'complete', updated_at = NOW()
        WHERE run_id = $1 AND item_type = $2 AND item_id = $3
        """,
        run_id, item_type, item_id,
    )
    logger.info("checkpoint_complete", run_id=run_id, item_type=item_type, item_id=item_id)


async def checkpoint_failed(
    db: asyncpg.Connection,
    run_id: str,
    item_type: str,
    item_id: str,
    error_msg: str,
) -> None:
    await db.execute(
        """
        UPDATE acp_shared.acp_stage_checkpoints
        SET status = 'failed', error_msg = $4, updated_at = NOW()
        WHERE run_id = $1 AND item_type = $2 AND item_id = $3
        """,
        run_id, item_type, item_id, error_msg,
    )
    logger.warning(
        "checkpoint_failed",
        run_id=run_id, item_type=item_type, item_id=item_id, error=error_msg,
    )


async def get_incomplete_items(
    db: asyncpg.Connection,
    run_id: str,
    item_type: str,
) -> list[str]:
    rows = await db.fetch(
        """
        SELECT item_id FROM acp_shared.acp_stage_checkpoints
        WHERE run_id = $1
          AND item_type = $2
          AND status NOT IN ('complete', 'skipped_duplicate')
        ORDER BY created_at
        """,
        run_id, item_type,
    )
    item_ids = [row["item_id"] for row in rows]
    logger.info(
        "get_incomplete_items",
        run_id=run_id, item_type=item_type, count=len(item_ids),
    )
    return item_ids
