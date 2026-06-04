"""Tests for services/acp_shared/stage_checkpoint.py (AA-107)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from services.acp_shared.stage_checkpoint import (
    checkpoint_complete,
    checkpoint_failed,
    checkpoint_start,
    get_incomplete_items,
)

RUN_ID = "run-uuid-001"
ITEM_TYPE = "social_tour"


def make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetch = AsyncMock()
    return db


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCheckpointStart:
    def test_checkpoint_start_inserts(self):
        db = make_db()
        run(checkpoint_start(db, RUN_ID, ITEM_TYPE, "tour-1"))
        db.execute.assert_awaited_once()
        sql = db.execute.call_args[0][0]
        assert "INSERT INTO acp_shared.acp_stage_checkpoints" in sql
        assert "ON CONFLICT" in sql
        assert "running" in sql


class TestCheckpointComplete:
    def test_checkpoint_complete_updates(self):
        db = make_db()
        run(checkpoint_complete(db, RUN_ID, ITEM_TYPE, "tour-1"))
        db.execute.assert_awaited_once()
        sql = db.execute.call_args[0][0]
        assert "UPDATE acp_shared.acp_stage_checkpoints" in sql
        assert "complete" in sql


class TestCheckpointFailed:
    def test_checkpoint_failed_records_error(self):
        db = make_db()
        run(checkpoint_failed(db, RUN_ID, ITEM_TYPE, "tour-1", "timeout"))
        db.execute.assert_awaited_once()
        sql = db.execute.call_args[0][0]
        assert "UPDATE acp_shared.acp_stage_checkpoints" in sql
        assert "failed" in sql
        assert "error_msg" in sql


class TestGetIncompleteItems:
    def test_get_incomplete_items_filters_correctly(self):
        db = make_db()
        row1 = MagicMock()
        row1.__getitem__ = lambda self, k: "tour-1" if k == "item_id" else None
        row2 = MagicMock()
        row2.__getitem__ = lambda self, k: "tour-3" if k == "item_id" else None
        db.fetch = AsyncMock(return_value=[row1, row2])

        result = run(get_incomplete_items(db, RUN_ID, ITEM_TYPE))

        db.fetch.assert_awaited_once()
        sql = db.fetch.call_args[0][0]
        assert "NOT IN ('complete', 'skipped_duplicate')" in sql
        assert result == ["tour-1", "tour-3"]

    def test_get_incomplete_items_empty(self):
        db = make_db()
        db.fetch = AsyncMock(return_value=[])

        result = run(get_incomplete_items(db, RUN_ID, ITEM_TYPE))

        assert result == []
