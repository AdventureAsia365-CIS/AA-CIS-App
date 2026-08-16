"""
tests/unit/test_aa412_admin_produce_router.py — api/routers/admin_produce.py
new AA-412 endpoints: GET .../packets/{id}/pieces, POST .../pieces/{id}/review,
GET .../produce/runs, and the review-gate added to POST .../gate-c/approve.

Mocks the asyncpg pool directly on pool.fetch/pool.fetchrow/pool.execute (most
of these handlers call the pool's own convenience methods, not pool.acquire())
following tests/unit/test_aa300_admin_atoms.py's auth-monkeypatch convention.
jsonb columns are fed back as raw JSON strings (never a parsed dict) — no
codec is registered on this app's connections, same real-asyncpg-shape note
test_aa300_admin_atoms.py's own _atom_row() fixture already documents.
"""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.routers import admin_produce

_TEST_SECRET = "test-admin-secret"
PACKET = str(uuid.uuid4())
PIECE = "slot_abc:blog"


@pytest.fixture(autouse=True)
def _admin_secret(monkeypatch):
    monkeypatch.setattr("api.routers.admin.ADMIN_SECRET", _TEST_SECRET)


class _Row(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _make_pool(**over):
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=over.get("fetch_return", []))
    pool.fetchrow = AsyncMock(return_value=over.get("fetchrow_return"))
    pool.fetchval = AsyncMock(return_value=over.get("fetchval_return"))
    pool.execute = AsyncMock(return_value=over.get("execute_return", "UPDATE 1"))
    return pool


def _make_request(pool):
    request = MagicMock()
    request.app.state.pool = pool
    return request


# ── GET /packets/{id}/pieces ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_packet_pieces_404_unknown_packet():
    pool = _make_pool(fetchrow_return=None)
    with pytest.raises(HTTPException) as exc:
        await admin_produce.list_packet_pieces(PACKET, _make_request(pool), _TEST_SECRET)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_packet_pieces_parses_jsonb_string_gate_ledger():
    ledger_json = json.dumps([{"gate": "F1_grounding", "passed": True, "violations": []}])
    audit_json = json.dumps({"brand_voice_score": 8})
    pool = _make_pool(
        fetchrow_return=_Row({"packet_id": PACKET}),
        fetch_return=[_Row({
            "piece_id": PIECE, "channel": "blog", "status": "passed",
            "body_tagged": "## Real body content", "gate_ledger": ledger_json,
            "brand_seo_audit": audit_json, "held_reason": None, "repair_count": 0,
            "review_status": "pending", "reviewed_by": None, "reviewed_at": None,
            "review_note": None,
        })],
    )

    result = await admin_produce.list_packet_pieces(PACKET, _make_request(pool), _TEST_SECRET)

    assert len(result) == 1
    piece = result[0]
    assert piece["body_tagged"] == "## Real body content"
    assert piece["gate_ledger"] == [{"gate": "F1_grounding", "passed": True, "violations": []}]
    assert piece["brand_seo_audit"] == {"brand_voice_score": 8}
    assert piece["review_status"] == "pending"


@pytest.mark.asyncio
async def test_list_packet_pieces_handles_null_brand_seo_audit():
    pool = _make_pool(
        fetchrow_return=_Row({"packet_id": PACKET}),
        fetch_return=[_Row({
            "piece_id": PIECE, "channel": "tiktok", "status": "held",
            "body_tagged": "draft", "gate_ledger": "[]",
            "brand_seo_audit": None, "held_reason": "F9: too generic", "repair_count": 3,
            "review_status": "pending", "reviewed_by": None, "reviewed_at": None,
            "review_note": None,
        })],
    )

    result = await admin_produce.list_packet_pieces(PACKET, _make_request(pool), _TEST_SECRET)

    assert result[0]["brand_seo_audit"] is None
    assert result[0]["gate_ledger"] == []


# ── POST /pieces/{id}/review ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_review_piece_approve():
    pool = _make_pool(execute_return="UPDATE 1")
    body = admin_produce.PieceReviewRequest(decision="approve", actor="reviewer-1")

    result = await admin_produce.review_piece(PIECE, body, _make_request(pool), _TEST_SECRET)

    assert result == {"piece_id": PIECE, "review_status": "approved"}
    sql = pool.execute.call_args.args[0]
    assert "review_status" in sql
    assert "reviewed_by" in sql


@pytest.mark.asyncio
async def test_review_piece_reject():
    pool = _make_pool(execute_return="UPDATE 1")
    body = admin_produce.PieceReviewRequest(decision="reject", actor="reviewer-1", note="F9 still generic")

    result = await admin_produce.review_piece(PIECE, body, _make_request(pool), _TEST_SECRET)

    assert result == {"piece_id": PIECE, "review_status": "rejected"}


@pytest.mark.asyncio
async def test_review_piece_invalid_decision_400():
    pool = _make_pool()
    body = admin_produce.PieceReviewRequest(decision="maybe", actor="reviewer-1")

    with pytest.raises(HTTPException) as exc:
        await admin_produce.review_piece(PIECE, body, _make_request(pool), _TEST_SECRET)
    assert exc.value.status_code == 400
    pool.execute.assert_not_called()


@pytest.mark.asyncio
async def test_review_piece_unknown_piece_404():
    pool = _make_pool(execute_return="UPDATE 0")
    body = admin_produce.PieceReviewRequest(decision="approve", actor="reviewer-1")

    with pytest.raises(HTTPException) as exc:
        await admin_produce.review_piece(PIECE, body, _make_request(pool), _TEST_SECRET)
    assert exc.value.status_code == 404


# ── POST /packets/{id}/gate-c/approve — AA-412 review-complete gate ────────

@pytest.mark.asyncio
async def test_approve_propose_only_bypasses_review_gate(monkeypatch):
    """'propose_only' is exempt — nothing new to gate on the packet's own
    default state (docs/implementation-notes/AA-412.md, approve_gate_c
    docstring)."""
    pool = _make_pool(fetchrow_return=_Row({"tenant_id": "tenant-1"}))
    pool.acquire = MagicMock()
    ctx = AsyncMock()
    conn = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    called = {}

    async def _fake_confirm(conn, *, packet_id, tenant_id, mode, actor):
        called["mode"] = mode

    monkeypatch.setattr(admin_produce, "confirm_ramp_transition", _fake_confirm)

    body = admin_produce.GateCApproveRequest(mode="propose_only", actor="reviewer-1")
    result = await admin_produce.approve_gate_c(PACKET, body, _make_request(pool), _TEST_SECRET)

    assert result["status"] == "transitioned"
    assert called["mode"] == "propose_only"


@pytest.mark.asyncio
async def test_approve_to_publish_blocked_when_pieces_not_all_approved(monkeypatch):
    pool = _make_pool(fetchrow_return=_Row({"tenant_id": "tenant-1"}))

    async def _fake_review_complete(pool_arg, packet_id):
        return False

    monkeypatch.setattr(admin_produce, "packet_pieces_review_complete", _fake_review_complete)

    called = {"confirm": False}

    async def _fake_confirm(*a, **k):
        called["confirm"] = True

    monkeypatch.setattr(admin_produce, "confirm_ramp_transition", _fake_confirm)

    body = admin_produce.GateCApproveRequest(mode="approve_to_publish", actor="reviewer-1")
    with pytest.raises(HTTPException) as exc:
        await admin_produce.approve_gate_c(PACKET, body, _make_request(pool), _TEST_SECRET)

    assert exc.value.status_code == 409
    assert "not every piece" in exc.value.detail
    assert called["confirm"] is False  # ramp mechanism never touched — the whole point of D2


@pytest.mark.asyncio
async def test_approve_to_publish_allowed_when_all_pieces_approved(monkeypatch):
    pool = _make_pool(fetchrow_return=_Row({"tenant_id": "tenant-1"}))
    ctx = AsyncMock()
    conn = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)

    async def _fake_review_complete(pool_arg, packet_id):
        return True

    monkeypatch.setattr(admin_produce, "packet_pieces_review_complete", _fake_review_complete)

    called = {}

    async def _fake_confirm(conn, *, packet_id, tenant_id, mode, actor):
        called["mode"] = mode

    monkeypatch.setattr(admin_produce, "confirm_ramp_transition", _fake_confirm)

    body = admin_produce.GateCApproveRequest(mode="approve_to_publish", actor="reviewer-1")
    result = await admin_produce.approve_gate_c(PACKET, body, _make_request(pool), _TEST_SECRET)

    assert result["status"] == "transitioned"
    assert called["mode"] == "approve_to_publish"


# ── GET /produce/runs ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_produce_runs_empty():
    pool = _make_pool(fetch_return=[])
    result = await admin_produce.list_produce_runs(_make_request(pool), _TEST_SECRET)
    assert result == []
    pool.fetch.assert_called_once()  # gate_ledger query short-circuits, never issued for 0 runs


@pytest.mark.asyncio
async def test_list_produce_runs_aggregates_gate_summary():
    run_id = str(uuid.uuid4())
    now = datetime(2026, 8, 16, tzinfo=timezone.utc)
    runs_row = _Row({
        "run_id": run_id, "tenant_id": "tenant-1", "year": 2026, "month": 9, "week": 2,
        "status": "completed", "created_at": now, "completed_at": now,
        "piece_count": 9, "passed_count": 0, "held_count": 9,
    })
    gate_rows = [
        _Row({"run_id": run_id, "gate": "F1_grounding", "passed": 5, "failed": 4}),
        _Row({"run_id": run_id, "gate": "F9_brand_seo_audit", "passed": 6, "failed": 3}),
    ]
    pool = MagicMock()
    pool.fetch = AsyncMock(side_effect=[[runs_row], gate_rows])

    result = await admin_produce.list_produce_runs(_make_request(pool), _TEST_SECRET)

    assert len(result) == 1
    run = result[0]
    assert run["run_id"] == run_id
    assert run["piece_count"] == 9
    assert run["held_count"] == 9
    assert run["gate_summary"] == {
        "F1_grounding": {"passed": 5, "failed": 4},
        "F9_brand_seo_audit": {"passed": 6, "failed": 3},
    }
    assert run["triggered_at"] == now.isoformat()
