"""AA-344 — GET /admin/upload-history surfaces rows_landed/rows_dropped from
shared.pipeline_runs.ingest_details (migration 091, AA-343 Part C), not just row_count (the
PARSED count, which misleadingly read "30" while only 16 rows landed — AA-343 P1.3).

Covers:
  1. test_upload_history_surfaces_landed_and_dropped — a source whose batch has a matching
     pipeline_runs.ingest_details row returns real int rows_landed/rows_dropped
  2. test_upload_history_null_for_pre_migration_091_source — a source with no matching
     pipeline_runs row (pre-091, or batch_id mismatch) degrades to null, not an error
  3. test_upload_history_zero_dropped_is_int_zero_not_null — a fully-clean ingest
     (rows_dropped = 0) is a real 0, distinguishable from "no data" (null)
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.routers import admin_pipeline
from api.routers import admin as admin_module


def _make_request(rows):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    pool.acquire.return_value.__aexit__.return_value = False
    request = MagicMock()
    request.app.state.pool = pool
    return request


@pytest.mark.asyncio
class TestAA344UploadHistoryLandedDropped:
    async def test_upload_history_surfaces_landed_and_dropped(self, monkeypatch):
        monkeypatch.setattr(admin_module, "ADMIN_SECRET", "test-secret")
        row = {
            "id": "src-1", "filename": "laos_biking_publish_ready.xlsx",
            "file_size_kb": 120.5, "row_count": 30, "parsed_at": None,
            "parse_errors": None, "batch_id": "batch-1",
            "rows_landed": "16", "rows_dropped": "14",
        }
        request = _make_request([row])
        result = await admin_pipeline.get_upload_history(request, x_admin_secret="test-secret")

        s = result["sources"][0]
        assert s["row_count"] == 30
        assert s["rows_landed"] == 16
        assert s["rows_dropped"] == 14
        assert isinstance(s["rows_landed"], int)
        assert isinstance(s["rows_dropped"], int)

    async def test_upload_history_null_for_pre_migration_091_source(self, monkeypatch):
        monkeypatch.setattr(admin_module, "ADMIN_SECRET", "test-secret")
        row = {
            "id": "src-2", "filename": "old_upload.xlsx",
            "file_size_kb": None, "row_count": 42, "parsed_at": None,
            "parse_errors": None, "batch_id": "batch-2",
            "rows_landed": None, "rows_dropped": None,
        }
        request = _make_request([row])
        result = await admin_pipeline.get_upload_history(request, x_admin_secret="test-secret")

        s = result["sources"][0]
        assert s["row_count"] == 42
        assert s["rows_landed"] is None
        assert s["rows_dropped"] is None

    async def test_upload_history_zero_dropped_is_int_zero_not_null(self, monkeypatch):
        monkeypatch.setattr(admin_module, "ADMIN_SECRET", "test-secret")
        row = {
            "id": "src-3", "filename": "clean_upload.xlsx",
            "file_size_kb": 50.0, "row_count": 20, "parsed_at": None,
            "parse_errors": None, "batch_id": "batch-3",
            "rows_landed": "20", "rows_dropped": "0",
        }
        request = _make_request([row])
        result = await admin_pipeline.get_upload_history(request, x_admin_secret="test-secret")

        s = result["sources"][0]
        assert s["rows_dropped"] == 0
        assert s["rows_dropped"] is not None
