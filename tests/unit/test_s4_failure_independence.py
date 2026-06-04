"""Unit tests for S4.1/S4.2 failure independence (AA-114).

Verifies:
  - _derive_run_status() logic for all relevant combinations
  - S4.1 (blog) pipeline writes only s4_blog_status, not s4_social_status
  - S4.2 (social) pipeline writes only s4_social_status, not s4_blog_status
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from api.routers.v1_s4_blog import _derive_run_status, _run_pipeline


# ── _derive_run_status tests ──────────────────────────────────────────────────

def test_derive_run_status_all_combinations():
    assert _derive_run_status("pending", "pending") == "s4_running"
    assert _derive_run_status("running", "complete") == "s4_running"
    assert _derive_run_status("failed", "complete") == "s4_partial_failed"
    assert _derive_run_status("complete", "complete") == "s4_complete"
    assert _derive_run_status("hitl_wait", "complete") == "s4_hitl_wait"
    assert _derive_run_status("complete", "hitl_wait") == "s4_hitl_wait"


def test_blog_hitl_social_complete():
    result = _derive_run_status("hitl_wait", "complete")
    assert result == "s4_hitl_wait"


def test_both_complete():
    result = _derive_run_status("complete", "complete")
    assert result == "s4_complete"


def test_blog_fail_does_not_affect_social():
    """Blog failure → s4_partial_failed; social status preserved independently."""
    blog = "failed"
    social = "complete"
    derived = _derive_run_status(blog, social)
    assert derived == "s4_partial_failed"


def test_social_fail_does_not_affect_blog():
    """Social failure → s4_partial_failed; blog status preserved independently."""
    blog = "hitl_wait"
    social = "failed"
    derived = _derive_run_status(blog, social)
    assert derived == "s4_partial_failed"


# ── S4.1 pipeline only writes s4_blog_status ─────────────────────────────────

@pytest.mark.asyncio
async def test_blog_pipeline_writes_only_s4_blog_status():
    """_run_pipeline (S4.1) must UPDATE s4_blog_status, never s4_social_status."""
    run_id = "aaaaaaaa-0000-0000-0000-000000000001"

    db = AsyncMock()
    db.fetch = AsyncMock(return_value=[])
    db.execute = AsyncMock(return_value=None)

    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=_async_ctx(db))

    initial_state = {
        "run_id": run_id,
        "tenant_id": "aa_internal",
        "calendar_item_id": "cccccccc-0000-0000-0000-000000000001",
        "primary_keyword": "Vietnam tours",
        "outline": [],
        "target_keywords": [],
        "title": "Best Vietnam Tours",
    }

    fake_final = {"status": "done", "draft_id": "dddddddd-0000-0000-0000-000000000001", "error": ""}

    with patch("services.acp_s4.graph.build_s4_graph") as mock_graph_fn:
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=fake_final)
        mock_graph_fn.return_value = mock_graph
        await _run_pipeline(run_id, pool, initial_state)

    # Collect all SQL executed on db
    executed_sql = [str(call_args[0][0]) for call_args in db.execute.call_args_list]

    # Must update s4_blog_status
    assert any("s4_blog_status" in sql for sql in executed_sql), (
        "Expected s4_blog_status update but found: " + str(executed_sql)
    )
    # Must NOT touch s4_social_status
    assert not any("s4_social_status" in sql for sql in executed_sql), (
        "S4.1 must not write s4_social_status: " + str(executed_sql)
    )
    # Must NOT update bare status=
    status_updates = [sql for sql in executed_sql if "SET status=" in sql or "SET status =" in sql]
    assert not status_updates, (
        "S4.1 must not write acp_runs.status directly: " + str(status_updates)
    )


@pytest.mark.asyncio
async def test_blog_pipeline_failure_writes_only_s4_blog_status():
    """_run_pipeline exception path must SET s4_blog_status='failed', not status."""
    run_id = "eeeeeeee-0000-0000-0000-000000000001"

    db_success = AsyncMock()
    db_success.fetch = AsyncMock(side_effect=RuntimeError("graph exploded"))

    db_failure = AsyncMock()
    db_failure.execute = AsyncMock(return_value=None)

    call_count = [0]

    class _CtxMgr:
        async def __aenter__(self):
            call_count[0] += 1
            return db_success if call_count[0] == 1 else db_failure

        async def __aexit__(self, *_):
            pass

    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=_CtxMgr())

    initial_state = {
        "run_id": run_id,
        "tenant_id": "aa_internal",
        "calendar_item_id": "ffffffff-0000-0000-0000-000000000001",
        "primary_keyword": "Thailand tours",
        "outline": [],
        "target_keywords": [],
        "title": "Best Thailand Tours",
    }

    with patch("services.acp_s4.graph.build_s4_graph"):
        await _run_pipeline(run_id, pool, initial_state)

    executed_sql = [str(c[0][0]) for c in db_failure.execute.call_args_list]
    assert any("s4_blog_status" in sql for sql in executed_sql)
    assert not any("s4_social_status" in sql for sql in executed_sql)


# ── Helpers ───────────────────────────────────────────────────────────────────

class _async_ctx:
    """Minimal async context manager returning a fixed object."""
    def __init__(self, obj):
        self._obj = obj

    async def __aenter__(self):
        return self._obj

    async def __aexit__(self, *_):
        pass
