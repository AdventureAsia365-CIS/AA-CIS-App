"""
tests/unit/test_aa364_packets.py — services/acp_produce/packets.py
(AA-364: create_packet() shell + set_publish_mode() F6 revenue-safety guard).
"""
from unittest.mock import AsyncMock

import pytest

from services.acp_produce.packets import (ALLOWED_PUBLISH_MODES_UNTIL_F6,
                                           PublishModeBlockedError, create_packet,
                                           set_publish_mode)

TENANT = "00000000-0000-0000-0000-000000000001"


def _make_db(fetchrow_return=None):
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=fetchrow_return)
    db.execute = AsyncMock()
    return db


# ── (c): create_packet() — default publish_mode is 'propose_only' (DB default, not overridden) ──

@pytest.mark.asyncio
async def test_create_packet_inserts_and_returns_packet_id():
    db = _make_db(fetchrow_return={"packet_id": "22222222-2222-2222-2222-222222222222"})

    packet_id = await create_packet(db, TENANT, year=2026, week=32)

    assert packet_id == "22222222-2222-2222-2222-222222222222"
    db.fetchrow.assert_called_once()
    sql, *params = db.fetchrow.call_args.args
    assert "INSERT INTO acp_deliver.packets" in sql
    assert params == [TENANT, 2026, 32]
    # publish_mode/status are NOT in the INSERT column list at all — left to
    # the DB defaults ('propose_only' / 'assembling', migration 094), not
    # re-asserted in Python where they could silently drift from the schema.
    assert "publish_mode" not in sql
    assert "status" not in sql


# ── (d): F6 guard — AA-365 (14/08/2026) widened this to all 3 ramp states ──

def test_allowed_modes_is_all_three_ramp_states_since_aa365():
    """Nghiep's AA-365 decision (14/08/2026) widened this past AA-364's
    original propose_only-only lock, now that F6 is confirmed wired into
    run_gates(). If this ever changes again, it must be a deliberate edit
    accompanying a new recorded decision — not a silent narrowing/widening."""
    assert ALLOWED_PUBLISH_MODES_UNTIL_F6 == frozenset(
        {"propose_only", "approve_to_publish", "veto_window_auto"}
    )


@pytest.mark.asyncio
async def test_set_publish_mode_propose_only_succeeds():
    db = _make_db()
    await set_publish_mode(db, "pkt-1", "propose_only")
    db.execute.assert_called_once()
    sql, *params = db.execute.call_args.args
    assert params == ["propose_only", "pkt-1"]


@pytest.mark.asyncio
async def test_set_publish_mode_approve_to_publish_succeeds_since_aa365():
    db = _make_db()
    await set_publish_mode(db, "pkt-1", "approve_to_publish")
    db.execute.assert_called_once()
    sql, *params = db.execute.call_args.args
    assert params == ["approve_to_publish", "pkt-1"]


@pytest.mark.asyncio
async def test_set_publish_mode_veto_window_auto_succeeds_since_aa365():
    db = _make_db()
    await set_publish_mode(db, "pkt-1", "veto_window_auto")
    db.execute.assert_called_once()
    sql, *params = db.execute.call_args.args
    assert params == ["veto_window_auto", "pkt-1"]


@pytest.mark.asyncio
async def test_set_publish_mode_rejects_invalid_mode_string():
    """The membership check stays as a general invalid-mode guard even
    though all 3 real ramp states are now allowed (AA-365)."""
    db = _make_db()
    with pytest.raises(PublishModeBlockedError, match="not a valid mode"):
        await set_publish_mode(db, "pkt-1", "bogus_mode")
    db.execute.assert_not_called()
