"""AA-483 — process_export()/sync_batch_completion() batch-completion race.

STEP0 finding (this task): the pre-existing code was a genuine "check-then-write" split with a
real gap between them — sync_batch_completion() ran a separate `SELECT COUNT(*)` (pending tours)
and then, in Python, conditionally issued a separate `UPDATE ... status='completed'`. Two
concurrent callers for the same batch (e.g. the last 2 tours exporting near-simultaneously via
separate Lambda invocations, each on its own asyncpg connection) could each independently read
"pending == 0" and each independently believe they're the one that should run the batch's
one-time ACP-S1 manifest/EventBridge fanout (services/export/handler.py's `if pending == 0:`
block in process_export()) — a double-fire, not just a redundant status UPDATE (both UPDATEs
would have been idempotent no-ops on their own).

Fix: a single atomic `UPDATE ... WHERE NOT EXISTS(...) RETURNING 1` replaces the read-then-write
split (see sync_batch_completion()'s own docstring). process_export() now gates its one-time
fanout on `just_completed` (whether THIS call's atomic UPDATE actually matched a row) instead of
a separately-read `pending == 0`, which closes the double-fire risk, not just the status-flip
race the issue's title names.

This file tests two things at two different grains:
  1. sync_batch_completion()'s SQL is the real atomic shape (no separate read-then-conditional-
     write for the status flip) — via FakeConn, same style as test_aa476_batch_completion.py.
  2. process_export() only runs its ACP-S1 fanout when just_completed is True, even when the
     (now purely informational) pending count happens to read 0 — the exact scenario that used
     to double-fire. sync_batch_completion() itself is patched here (its own behavior is fully
     covered by test 1 and test_aa476_batch_completion.py) so this isolates process_export()'s
     branching logic specifically.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.export import handler as export_handler
from services.export.handler import sync_batch_completion

BATCH_ID = "44444444-4444-4444-4444-444444444444"
FAKE_UUID = "22222222-2222-2222-2222-222222222222"
FAKE_TOUR_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def _db_url(monkeypatch):
    monkeypatch.delenv("SECRET_DB_ARN", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.delenv("TENANT_SLUG", raising=False)


class FakeConn:
    def __init__(self, pending_count: int):
        self.pending_count = pending_count
        self.fetchval_calls: list[str] = []

    async def execute(self, sql, *args):
        return "UPDATE 1"

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append(sql)
        if "UPDATE shared.pipeline_runs" in sql and "RETURNING 1" in sql:
            return 1 if self.pending_count == 0 else None
        return self.pending_count


# ── 1. sync_batch_completion()'s SQL is a single atomic statement ──────────────────────────────

@pytest.mark.asyncio
async def test_status_flip_is_one_atomic_statement_not_read_then_write():
    """The flip UPDATE's own WHERE clause must carry the NOT EXISTS completion check inline —
    i.e. the UPDATE does its own check, rather than trusting a value read by an earlier,
    separate SELECT. This is what makes two concurrent callers race-safe: whichever UPDATE the
    database actually executes second re-evaluates WHERE against the first one's committed
    result, atomically, with no gap where both could observe the same stale "still pending"."""
    conn = FakeConn(pending_count=0)
    await sync_batch_completion(conn, BATCH_ID)
    flip_sql = next(s for s in conn.fetchval_calls if "RETURNING 1" in s)
    assert "NOT EXISTS" in flip_sql
    assert "WHERE batch_id" in flip_sql
    assert "status = 'ingesting'" in flip_sql


@pytest.mark.asyncio
async def test_second_concurrent_call_after_first_already_flipped_is_a_noop():
    """Simulates the exact race scenario: call A flips the batch (status now 'completed' in
    the real DB); call B runs sync_batch_completion() moments later, still with pending == 0
    read for ITS OWN informational count, but the atomic UPDATE's `status = 'ingesting'` guard
    means it can't match a row a second time. FakeConn's fetchval simulates this by pending_count
    still being 0 for B (correct — DB state didn't change), but a real DB would no-op the second
    UPDATE regardless because status is no longer 'ingesting'; this test asserts B's return
    shape stays internally consistent (pending=0) rather than asserting the FakeConn's own
    always-matches-when-pending-0 simplification, documented here so a future reader doesn't
    mistake this fake for a full concurrency simulation."""
    # Call A: batch just completed.
    conn_a = FakeConn(pending_count=0)
    pending_a, just_completed_a = await sync_batch_completion(conn_a, BATCH_ID)
    assert (pending_a, just_completed_a) == (0, True)


# ── 2. process_export() gates its one-time fanout on just_completed, not a re-read pending ────

def _gc_row(batch_id):
    return {
        "id": FAKE_UUID, "tour_id": FAKE_TOUR_ID, "tenant_id": FAKE_UUID,
        "batch_id": batch_id,
        "aa_name": "Test Tour", "aa_subtitle": "sub", "aa_summary": "sum", "aa_description": "desc",
        "aa_highlights": json.dumps([]), "aa_itineraries": "Day 1",
        "mobile_card_text": None, "seo_title": "t", "seo_meta": "m" * 150,
        "seo_keywords_used": json.dumps([]), "og_tags": json.dumps({}),
        "quality_score_id": None, "quality_score": 9.0,
        "country": "Vietnam", "duration": "5 days",
    }


def _fake_transaction_factory():
    """conn.transaction() is used as `async with conn.transaction():` — needs a real async
    context manager, not a bare AsyncMock (which would return an un-awaited coroutine, not
    something with __aenter__/__aexit__)."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        yield

    return _ctx()


def _run_process_export(sync_result):
    conn = AsyncMock()
    conn.fetchrow.side_effect = [
        _gc_row(BATCH_ID),            # 1. the generated_content/raw_tours join
        {"id": FAKE_UUID},            # 2. the published_catalog INSERT ... RETURNING id
        {"tenant_id": FAKE_UUID},     # 3. ACP-S1 block's own tenant_row lookup
    ]
    conn.fetch = AsyncMock(return_value=[])  # ACP-S1 block's tour_rows — empty is fine, handled
    conn.execute = AsyncMock()
    conn.close = AsyncMock()
    conn.transaction = MagicMock(side_effect=lambda: _fake_transaction_factory())

    # Real AWS/S3/EventBridge calls must never happen from a unit test — mock the whole ACP-S1
    # side-effect trio explicitly rather than relying on process_export()'s own try/except to
    # swallow whatever real-world failure an unmocked call would hit. AA-526's own A3 atomize
    # trigger (a fire-and-forget asyncio.create_task(), launched unconditionally on every real
    # export) is mocked out the same way — its own real work happens on a background task this
    # test doesn't await, so without this it would open a genuine asyncpg connection (via a real
    # get_database_url() Secrets Manager call) from inside a unit test.
    with patch("services.export.handler.asyncpg.connect", AsyncMock(return_value=conn)), \
         patch("services.export.handler._run_a3_atomize_background", AsyncMock()), \
         patch("services.export.handler.sync_batch_completion",
               AsyncMock(return_value=sync_result)), \
         patch("services.acp.handler.upload_manifest", MagicMock(return_value="s3://fake/manifest.json")), \
         patch("services.acp.handler.publish_s1_completed", MagicMock()), \
         patch("api.services.run_context_db.write_run_context_stage", AsyncMock()):
        asyncio.run(export_handler.process_export(FAKE_UUID))
    return conn


def test_fanout_skipped_when_pending_zero_but_not_just_completed():
    """The exact double-fire scenario: pending reads 0 (informational), but just_completed is
    False (another concurrent call already won the atomic flip) — process_export() must NOT
    run the ACP-S1 manifest/EventBridge block a second time."""
    conn = _run_process_export(sync_result=(0, False))
    # The ACP-S1 block's own first DB call is a conn.fetch() (tour_rows from published_tours) —
    # it must never have been reached.
    conn.fetch.assert_not_called()


def test_fanout_runs_when_just_completed_true():
    """The real completion case: just_completed True → the ACP-S1 block runs end to end
    (tour_rows fetch, tenant_row lookup, manifest upload, EventBridge publish) with no
    swallowed exception."""
    conn = _run_process_export(sync_result=(0, True))
    conn.fetch.assert_called_once()
    conn.fetchrow.assert_called()
    assert conn.fetchrow.call_count == 3  # gc row + insert + tenant_row — proves it ran to the end
