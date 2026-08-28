"""AA-476 — pipeline_runs.status stuck at 'ingesting' fix.

Root cause: sync_batch_completion() (services/export/handler.py) is the ONLY place
pipeline_runs.status ever advances, and it used to only recognize 'published' as a
resolved tour outcome. A rejected tour never got any raw_tours.pipeline_status update at
all (reject_review() only touched review_queue/generated_content), so it stayed 'ingested'
forever and the batch's status never left 'ingesting' — even once every other tour in the
batch was long done.

These tests drive the real functions (no re-implemented copies), with a minimal fake conn.
"""
import pytest
from unittest.mock import AsyncMock

from services.export.handler import sync_batch_completion, mark_tour_rejected

BATCH_ID = "44444444-4444-4444-4444-444444444444"
TOUR_ID = "55555555-5555-5555-5555-555555555555"


class FakeConn:
    """Fakes just enough of asyncpg's Connection for sync_batch_completion/mark_tour_rejected:
    execute() for the tours_passed UPDATE, fetchval() for the pending count, execute() for the
    status flip, fetchrow() for mark_tour_rejected's UPDATE ... RETURNING batch_id."""

    def __init__(self, pending_count: int, rejected_row_batch_id=BATCH_ID):
        self.pending_count = pending_count
        self.rejected_row_batch_id = rejected_row_batch_id
        self.executed: list[str] = []

    async def execute(self, sql, *args):
        self.executed.append(sql)
        return "UPDATE 1"

    async def fetchval(self, sql, *args):
        return self.pending_count

    async def fetchrow(self, sql, *args):
        if self.rejected_row_batch_id is None:
            return None
        return {"batch_id": self.rejected_row_batch_id}


@pytest.mark.asyncio
async def test_sync_batch_completion_stays_ingesting_while_tours_pending():
    """>0 non-terminal tours remain → status flip UPDATE never issued."""
    conn = FakeConn(pending_count=2)
    pending = await sync_batch_completion(conn, BATCH_ID)
    assert pending == 2
    assert not any("SET status = 'completed'" in sql for sql in conn.executed)


@pytest.mark.asyncio
async def test_sync_batch_completion_flips_to_completed_when_zero_pending():
    """All tours terminal (published + hitl_rejected/failed mix) → status flip fires."""
    conn = FakeConn(pending_count=0)
    pending = await sync_batch_completion(conn, BATCH_ID)
    assert pending == 0
    assert any("SET status = 'completed'" in sql for sql in conn.executed)


@pytest.mark.asyncio
async def test_sync_batch_completion_pending_query_excludes_terminal_non_published():
    """The pending count query must treat hitl_rejected/failed as resolved, not just
    published — this is the actual AA-476 fix, not just a status-flip mechanism check."""
    conn = FakeConn(pending_count=0)
    captured_sql = {}

    async def fetchval(sql, *args):
        captured_sql["sql"] = sql
        return 0

    conn.fetchval = fetchval
    await sync_batch_completion(conn, BATCH_ID)
    assert "hitl_rejected" in captured_sql["sql"]
    assert "failed" in captured_sql["sql"]
    assert "published" in captured_sql["sql"]


@pytest.mark.asyncio
async def test_mark_tour_rejected_sets_terminal_status_and_syncs_batch():
    """reject_review()'s missing half: raw_tours.pipeline_status must actually change, and
    the batch completion check must run off the back of it."""
    conn = FakeConn(pending_count=0, rejected_row_batch_id=BATCH_ID)
    await mark_tour_rejected(conn, TOUR_ID)

    update_calls = [c for c in conn.executed if "SET status = 'completed'" in c]
    assert len(update_calls) == 1


@pytest.mark.asyncio
async def test_mark_tour_rejected_noop_when_tour_has_no_batch():
    """A tour with no batch_id (shouldn't happen, but defensive) must not explode or touch
    pipeline_runs."""
    conn = FakeConn(pending_count=0, rejected_row_batch_id=None)
    await mark_tour_rejected(conn, TOUR_ID)
    assert conn.executed == []
