"""
AA-186: gate-as-event-boundary — acp.hitl.approved/rejected publish tests.

Covers:
  - gate_approve  -> exactly one acp.hitl.approved, payload matches the
                     STEP 1 contract, reviewer_type from the auth dict
  - gate_reject   -> exactly one acp.hitl.rejected, no approved event
  - already-resolved hitl_request -> 409, zero publishes
  - Gate 1 auto-approve (_handle_gate1) -> one acp.hitl.approved,
    gate=1/stage=2/next_stage=3, no pending row left (no awaiting_gate update)
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

from api.routers.v1_acp_gate import (
    gate_approve,
    gate_reject,
    GateApproveRequest,
    GateRejectRequest,
)
from services.acp_shared.event_constants import ACPEventDetailType

_TENANT_ID = "11111111-0000-0000-0000-000000000001"
_RUN_ID = "22222222-0000-0000-0000-000000000001"
_HITL_ID = "33333333-0000-0000-0000-000000000001"

_TENANT_SELF = {
    "sub": _TENANT_ID,
    "tenant_id": _TENANT_ID,
    "role": "tenant",
    "actor": "Acme Corp",
    "reviewer_type": "tenant_self",
}


def _ctx(conn):
    c = AsyncMock()
    c.__aenter__ = AsyncMock(return_value=conn)
    c.__aexit__ = AsyncMock(return_value=False)
    return c


def _make_conn(hitl_status: str):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[
        {"tenant_id": UUID(_TENANT_ID)},                     # acp_runs lookup
        {"hitl_id": UUID(_HITL_ID), "status": hitl_status},  # acp_hitl_requests lookup
    ])
    conn.execute = AsyncMock()
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn)
    return conn


def _make_request(conn):
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_ctx(conn))
    req = MagicMock()
    req.app.state.pool = pool
    return req


@pytest.mark.asyncio
async def test_gate_approve_publishes_hitl_approved_with_step1_payload():
    conn = _make_conn("pending")
    request = _make_request(conn)

    with patch("api.routers.v1_acp_gate.publish_hitl_event") as mock_publish:
        result = await gate_approve(
            stage="s3",
            body=GateApproveRequest(run_id=_RUN_ID, notes="looks good"),
            request=request,
            tenant=_TENANT_SELF,
        )

    assert result["status"] == "approved"
    mock_publish.assert_called_once()
    detail_type, payload = mock_publish.call_args[0]
    assert detail_type == ACPEventDetailType.HITL_APPROVED
    assert payload == {
        "run_id": _RUN_ID,
        "stage": 3,
        "gate": 2,
        "decision": "approved",
        "reviewer_type": "tenant_self",
        "next_stage": 4,
    }


@pytest.mark.asyncio
async def test_gate_reject_publishes_hitl_rejected_only():
    conn = _make_conn("pending")
    request = _make_request(conn)

    with patch("api.routers.v1_acp_gate.publish_hitl_event") as mock_publish, \
         patch("api.routers.v1_acp_gate._h3.extract_and_save_rule", new=AsyncMock()):
        result = await gate_reject(
            stage="s3",
            body=GateRejectRequest(run_id=_RUN_ID, notes="needs more detail"),
            request=request,
            tenant=_TENANT_SELF,
        )

    assert result["status"] == "rejected"
    mock_publish.assert_called_once()
    detail_type, payload = mock_publish.call_args[0]
    assert detail_type == ACPEventDetailType.HITL_REJECTED
    assert payload == {
        "run_id": _RUN_ID,
        "stage": 3,
        "gate": 2,
        "decision": "rejected",
        "reviewer_type": "tenant_self",
        "next_stage": None,
    }
    # Never published an approved event
    for call in mock_publish.call_args_list:
        assert call.args[0] != ACPEventDetailType.HITL_APPROVED


@pytest.mark.asyncio
async def test_gate_approve_publish_failure_logs_but_still_returns_approved():
    conn = _make_conn("pending")
    request = _make_request(conn)

    with patch("api.routers.v1_acp_gate.publish_hitl_event", return_value=False), \
         patch("api.routers.v1_acp_gate.logger") as mock_logger:
        result = await gate_approve(
            stage="s3",
            body=GateApproveRequest(run_id=_RUN_ID, notes="looks good"),
            request=request,
            tenant=_TENANT_SELF,
        )

    assert result["status"] == "approved"
    error_calls = [c for c in mock_logger.error.call_args_list
                   if c.args and c.args[0] == "hitl_approved_publish_failed_post_commit"]
    assert len(error_calls) == 1
    assert error_calls[0].kwargs["run_id"] == _RUN_ID
    assert error_calls[0].kwargs["stage"] == 3
    assert error_calls[0].kwargs["hitl_id"] == _HITL_ID


@pytest.mark.asyncio
async def test_gate_approve_already_resolved_returns_409_no_publish():
    conn = _make_conn("approved")  # already resolved by a prior call
    request = _make_request(conn)

    with patch("api.routers.v1_acp_gate.publish_hitl_event") as mock_publish:
        with pytest.raises(HTTPException) as exc_info:
            await gate_approve(
                stage="s3",
                body=GateApproveRequest(run_id=_RUN_ID, notes="again"),
                request=request,
                tenant=_TENANT_SELF,
            )

    assert exc_info.value.status_code == 409
    mock_publish.assert_not_called()


# ── Gate 1 auto-approve (_handle_gate1) ─────────────────────────────────────

_AA_INTERNAL = "00000000-0000-0000-0000-000000000001"


def _make_gate1_pool(hitl_id=_HITL_ID):
    """Single acquire() — INSERT ... RETURNING hitl_id, then audit_log INSERT."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"hitl_id": UUID(hitl_id)})
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_ctx(conn))
    return pool, conn


@pytest.mark.asyncio
async def test_handle_gate1_auto_approve_publishes_and_skips_awaiting_gate():
    from services.acp.s2.router import _handle_gate1

    pool, conn = _make_gate1_pool()
    run_context = MagicMock(s2_confidence_score=0.92, s2_visibility_report=None)

    with patch("services.acp.s2.router.get_run_context_validated",
               new=AsyncMock(return_value=run_context)), \
         patch("services.acp.s2.router.publish_hitl_event") as mock_publish:
        result = await _handle_gate1(pool, _RUN_ID, _AA_INTERNAL)

    assert result["auto_approved"] is True

    mock_publish.assert_called_once()
    detail_type, payload = mock_publish.call_args[0]
    assert detail_type == ACPEventDetailType.HITL_APPROVED
    assert payload == {
        "run_id": _RUN_ID,
        "stage": 2,
        "gate": 1,
        "decision": "approved",
        "reviewer_type": "aa_internal",
        "next_stage": 3,
    }

    # No "awaiting_gate" UPDATE — only the audit_log INSERT executed.
    assert conn.execute.call_count == 1
    awaiting_gate_calls = [
        c for c in conn.execute.call_args_list
        if "awaiting_gate" in c.args[0]
    ]
    assert awaiting_gate_calls == []


@pytest.mark.asyncio
async def test_handle_gate1_pending_marks_awaiting_gate_no_publish():
    from services.acp.s2.router import _handle_gate1

    pool, conn = _make_gate1_pool()
    # Below threshold -> not auto-approved, even for aa_internal
    run_context = MagicMock(s2_confidence_score=0.50, s2_visibility_report=None)

    with patch("services.acp.s2.router.get_run_context_validated",
               new=AsyncMock(return_value=run_context)), \
         patch("services.acp.s2.router.publish_hitl_event") as mock_publish:
        result = await _handle_gate1(pool, _RUN_ID, _AA_INTERNAL)

    assert result["auto_approved"] is False
    mock_publish.assert_not_called()

    # audit_log INSERT + acp_stage_runs awaiting_gate UPDATE
    assert conn.execute.call_count == 2
    awaiting_gate_calls = [
        c for c in conn.execute.call_args_list
        if "awaiting_gate" in c.args[0]
    ]
    assert len(awaiting_gate_calls) == 1
