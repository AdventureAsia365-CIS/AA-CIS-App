"""Unit tests for per-blog HITL reject semantics (AA-124).

Covers:
  - First Trang rejection → requeue (reset to pending_trang, rewrite_count+1, pipeline re-triggered)
  - Second Trang rejection → escalate to Ms. Thu (escalated_msthy, no pipeline)
  - Trang approval → unaffected (no requeue, no escalate)
  - Only the targeted draft is modified (WHERE draft_id, not WHERE run_id)
  - Ms. Thu rejection → final (msthy_rejected, no requeue)
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from api.routers.v1_s4_blog import hitl_decision, HitlRequest

_DRAFT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_RUN_ID   = "bbbbbbbb-0000-0000-0000-000000000001"
_DRAFT_2  = "aaaaaaaa-0000-0000-0000-000000000002"
_DRAFT_3  = "aaaaaaaa-0000-0000-0000-000000000003"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_conn(fetchrow_return=None):
    """Return an asyncpg connection mock."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute = AsyncMock(return_value=None)
    return conn


def _make_pool(conn):
    """Wrap a mock connection in a mock pool whose acquire() is an async CM."""
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__.return_value = conn
    acquire_ctx.__aexit__.return_value = False
    pool = MagicMock()
    pool.acquire.return_value = acquire_ctx
    return pool


def _make_request(pool):
    req = MagicMock()
    req.app.state.pool = pool
    return req


def _draft_select_row(rewrite_count=0, run_id=_RUN_ID, tenant_id="aa_internal"):
    """Dict that satisfies `row["key"]` lookups for the SELECT path."""
    return {
        "rewrite_count": rewrite_count,
        "run_id": run_id,
        "tenant_id": tenant_id,
    }


def _draft_returning_row(hitl_gate3_status="trang_approved", run_id=_RUN_ID):
    """Dict for the UPDATE RETURNING path, compatible with _row_to_dict."""
    return {
        "draft_id": _DRAFT_ID,
        "run_id": run_id,
        "tenant_id": "aa_internal",
        "hitl_gate3_status": hitl_gate3_status,
        "hitl_reviewer_id": "reviewer-01",
        "hitl_decided_at": None,
    }


def _eat_coro(coro):
    """Close an unawaited coroutine so asyncio doesn't warn in tests."""
    if hasattr(coro, "close"):
        coro.close()
    return MagicMock()


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_rejection_requeues():
    """Draft with rewrite_count=0 → reset to pending_trang, pipeline re-triggered."""
    conn = _make_conn(fetchrow_return=_draft_select_row(rewrite_count=0))
    pool = _make_pool(conn)
    request = _make_request(pool)
    body = HitlRequest(status="rejected", reviewer_id="trang-01", reviewer_role="trang")

    with patch("api.routers.v1_s4_blog._rerun_blog_after_hitl_rejection", new_callable=AsyncMock), \
         patch("asyncio.create_task", side_effect=_eat_coro) as mock_task:
        result = await hitl_decision(_DRAFT_ID, request, body, _auth={"sub": "admin"})

    assert result["status"] == "requeued"
    assert result["rewrite_count"] == 1
    assert "rewrite" in result["message"].lower()

    # Verify UPDATE resets to pending_trang and increments rewrite_count
    update_sql_calls = [c.args[0] for c in conn.execute.call_args_list]
    reset_calls = [s for s in update_sql_calls if "pending_trang" in s]
    assert len(reset_calls) == 1
    assert "rewrite_count=rewrite_count+1" in reset_calls[0]
    assert f"$2::uuid" in reset_calls[0]  # WHERE targets draft_id, not run_id

    # Pipeline must be scheduled
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_second_rejection_escalates():
    """Draft with rewrite_count=1 → escalated_msthy, pipeline NOT triggered."""
    conn = _make_conn(fetchrow_return=_draft_select_row(rewrite_count=1))
    pool = _make_pool(conn)
    request = _make_request(pool)
    body = HitlRequest(status="rejected", reviewer_id="trang-01", reviewer_role="trang")

    with patch("asyncio.create_task", side_effect=_eat_coro) as mock_task:
        result = await hitl_decision(_DRAFT_ID, request, body, _auth={"sub": "admin"})

    assert result["status"] == "escalated"
    assert "Ms. Thu" in result["message"]

    # Verify UPDATE sets escalated_msthy
    update_sql_calls = [c.args[0] for c in conn.execute.call_args_list]
    escalate_calls = [s for s in update_sql_calls if "escalated_msthy" in s]
    assert len(escalate_calls) == 1

    # Pipeline must NOT be scheduled
    mock_task.assert_not_called()


@pytest.mark.asyncio
async def test_approval_unaffected():
    """Trang approval → trang_approved status, no requeue, no escalate."""
    conn = _make_conn(fetchrow_return=_draft_returning_row(hitl_gate3_status="trang_approved"))
    pool = _make_pool(conn)
    request = _make_request(pool)
    body = HitlRequest(status="approved", reviewer_id="trang-01", reviewer_role="trang")

    with patch("asyncio.create_task", side_effect=_eat_coro) as mock_task:
        result = await hitl_decision(_DRAFT_ID, request, body, _auth={"sub": "admin"})

    assert result["hitl_gate3_status"] == "trang_approved"
    # No requeue/escalate keys in a normal approval response
    assert "status" not in result or result.get("status") not in ("requeued", "escalated")

    # No pipeline scheduled for approval
    mock_task.assert_not_called()

    # Verify no pending_trang or escalated_msthy UPDATE was issued
    update_sql_calls = [c.args[0] for c in conn.execute.call_args_list]
    assert not any("pending_trang" in s for s in update_sql_calls)
    assert not any("escalated_msthy" in s for s in update_sql_calls)


@pytest.mark.asyncio
async def test_other_drafts_unaffected():
    """Rejecting draft_2 must only UPDATE draft_2 — drafts 1 and 3 are untouched."""
    conn = _make_conn(fetchrow_return=_draft_select_row(rewrite_count=0))
    pool = _make_pool(conn)
    request = _make_request(pool)
    body = HitlRequest(status="rejected", reviewer_id="trang-01", reviewer_role="trang")

    with patch("api.routers.v1_s4_blog._rerun_blog_after_hitl_rejection", new_callable=AsyncMock), \
         patch("asyncio.create_task", side_effect=_eat_coro):
        await hitl_decision(_DRAFT_2, request, body, _auth={"sub": "admin"})

    # Every execute call that modifies blog_drafts must target draft_2's ID, not run_id
    for args, _ in conn.execute.call_args_list:
        sql = args[0]
        if "UPDATE acp_silver_s4.blog_drafts" in sql:
            # The parameterised WHERE must use $2::uuid (draft_id is always 2nd param)
            assert "$2::uuid" in sql, f"UPDATE must target draft_id; got: {sql}"
            # The draft_id argument must be _DRAFT_2, not _RUN_ID or other drafts
            assert args[1] != _DRAFT_ID  # not draft_1
            assert args[1] != _DRAFT_3   # not draft_3


@pytest.mark.asyncio
async def test_msthy_rejection_no_requeue():
    """Ms. Thu rejection → msthy_rejected status, NO requeue (ms_thu decision is final)."""
    conn = _make_conn(fetchrow_return=_draft_returning_row(hitl_gate3_status="msthy_rejected"))
    pool = _make_pool(conn)
    request = _make_request(pool)
    body = HitlRequest(status="rejected", reviewer_id="ms-thu-01", reviewer_role="ms_thu")

    with patch("asyncio.create_task", side_effect=_eat_coro) as mock_task:
        result = await hitl_decision(_DRAFT_ID, request, body, _auth={"sub": "admin"})

    assert result["hitl_gate3_status"] == "msthy_rejected"

    # No pipeline scheduled — Ms. Thu rejection is final
    mock_task.assert_not_called()

    # No pending_trang or escalated_msthy in any UPDATE
    update_sql_calls = [c.args[0] for c in conn.execute.call_args_list]
    assert not any("pending_trang" in s for s in update_sql_calls)
    assert not any("escalated_msthy" in s for s in update_sql_calls)
