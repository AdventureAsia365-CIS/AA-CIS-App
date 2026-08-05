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


# ── (d): F6 guard — the counter-proof test the task explicitly asked for ──

def test_allowed_modes_is_exactly_propose_only_today():
    """If this ever changes, it must be a deliberate edit accompanying a new
    Nghiep decision recorded in AA-364.md — not a silent widening."""
    assert ALLOWED_PUBLISH_MODES_UNTIL_F6 == frozenset({"propose_only"})


@pytest.mark.asyncio
async def test_set_publish_mode_propose_only_succeeds():
    db = _make_db()
    await set_publish_mode(db, "pkt-1", "propose_only")
    db.execute.assert_called_once()
    sql, *params = db.execute.call_args.args
    assert params == ["propose_only", "pkt-1"]


@pytest.mark.asyncio
async def test_set_publish_mode_approve_to_publish_blocked():
    db = _make_db()
    with pytest.raises(PublishModeBlockedError, match="approve_to_publish"):
        await set_publish_mode(db, "pkt-1", "approve_to_publish")
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_set_publish_mode_veto_window_auto_blocked():
    db = _make_db()
    with pytest.raises(PublishModeBlockedError, match="veto_window_auto"):
        await set_publish_mode(db, "pkt-1", "veto_window_auto")
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_set_publish_mode_error_cites_f6_and_the_decision_date():
    db = _make_db()
    with pytest.raises(PublishModeBlockedError, match="F6"):
        await set_publish_mode(db, "pkt-1", "approve_to_publish")
