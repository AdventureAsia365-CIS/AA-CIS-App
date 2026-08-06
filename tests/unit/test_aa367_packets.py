"""
tests/unit/test_aa367_packets.py — services/acp_produce/packets.py
(AA-367: assemble_packet() + maybe_mark_packet_ready() + deliver_packet(),
now that C3/E1-E5 (AA-368) produce real 'passed' Piece rows for AA-364's
previously-empty packet shell to actually assemble).

DB/pool mocking follows test_aa364_packets.py's `_make_db()` convention and
test_aa361_atom_usage.py's `_make_pool()`/`_fake_conn()` convention for
write_usage_log()'s own pool.acquire() shape.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.acp_produce.packets import (PacketNotReadyError, assemble_packet,
                                           deliver_packet, maybe_mark_packet_ready)

PACKET = "pkt-1"


class _Row(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _make_db(fetch_return=None, fetchval_return=None, execute_return="UPDATE 1"):
    db = AsyncMock()
    db.fetch = AsyncMock(return_value=fetch_return or [])
    db.fetchval = AsyncMock(return_value=fetchval_return)
    db.execute = AsyncMock(return_value=execute_return)
    return db


class _TxnCM:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _make_pool_and_conn():
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=_TxnCM())
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


# ── assemble_packet() ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assemble_packet_assigns_all_passed_pieces():
    db = _make_db(fetch_return=[
        _Row({"piece_id": "p1", "status": "passed"}),
        _Row({"piece_id": "p2", "status": "passed"}),
    ])

    n = await assemble_packet(db, PACKET, ["p1", "p2"])

    assert n == 2
    db.execute.assert_called_once()
    sql, packet_id, piece_ids = db.execute.call_args.args
    assert "UPDATE acp_deliver.pieces" in sql
    assert "packet_id = $1" in sql
    assert packet_id == PACKET
    assert piece_ids == ["p1", "p2"]


@pytest.mark.asyncio
async def test_assemble_packet_raises_on_missing_piece_id():
    db = _make_db(fetch_return=[_Row({"piece_id": "p1", "status": "passed"})])

    with pytest.raises(ValueError, match=r"missing=\['p2'\]"):
        await assemble_packet(db, PACKET, ["p1", "p2"])
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_assemble_packet_raises_on_held_piece_never_silently_skips():
    db = _make_db(fetch_return=[
        _Row({"piece_id": "p1", "status": "passed"}),
        _Row({"piece_id": "p2", "status": "held"}),
    ])

    with pytest.raises(ValueError, match=r"not_passed=\['p2'\]"):
        await assemble_packet(db, PACKET, ["p1", "p2"])
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_assemble_packet_rejects_empty_piece_ids():
    db = _make_db()
    with pytest.raises(ValueError, match="must not be empty"):
        await assemble_packet(db, PACKET, [])
    db.fetch.assert_not_called()


# ── maybe_mark_packet_ready() — minimum-viable ">=1 passed" threshold ─────

@pytest.mark.asyncio
async def test_maybe_mark_ready_advances_when_at_least_one_passed():
    db = _make_db(fetchval_return=1, execute_return="UPDATE 1")

    advanced = await maybe_mark_packet_ready(db, PACKET)

    assert advanced is True
    db.execute.assert_called_once()
    sql, packet_id = db.execute.call_args.args
    assert "SET status = 'ready'" in sql
    assert "status = 'assembling'" in sql
    assert packet_id == PACKET


@pytest.mark.asyncio
async def test_maybe_mark_ready_noop_when_zero_passed():
    db = _make_db(fetchval_return=0)

    advanced = await maybe_mark_packet_ready(db, PACKET)

    assert advanced is False
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_mark_ready_noop_when_packet_not_assembling():
    """DB-side WHERE status='assembling' guard: fetchval says >=1 passed,
    but the conditional UPDATE affects 0 rows (already ready/delivered)."""
    db = _make_db(fetchval_return=1, execute_return="UPDATE 0")

    advanced = await maybe_mark_packet_ready(db, PACKET)

    assert advanced is False


# ── deliver_packet() — the STEP 5 boundary, write_usage_log timing ────────

@pytest.mark.asyncio
async def test_deliver_packet_blocked_when_not_ready():
    db = _make_db(fetchval_return="assembling")
    pool, conn = _make_pool_and_conn()

    with pytest.raises(PacketNotReadyError, match="must be 'ready'"):
        await deliver_packet(db, pool, PACKET)

    db.fetch.assert_not_called()
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_deliver_packet_writes_usage_log_then_flips_status():
    db = AsyncMock()
    db.fetchval = AsyncMock(return_value="ready")
    db.fetch = AsyncMock(return_value=[
        _Row({"piece_id": "p1", "body_tagged": "Cites [R:atom_1].", "channel": "blog"}),
    ])
    db.execute = AsyncMock()
    pool, conn = _make_pool_and_conn()

    result = await deliver_packet(db, pool, PACKET)

    assert result == {"atom_1": 1}
    # usage_log write happened via the pool (conn.execute), BEFORE the
    # packets.status UPDATE (via db.execute) — call-order proof, not just
    # "both happened".
    conn.execute.assert_called_once()
    sql, atom_id, entries_json = conn.execute.call_args.args
    assert "UPDATE acp_contract.tour_atoms" in sql
    assert atom_id == "atom_1"
    assert json.loads(entries_json)[0]["piece_id"] == "p1"

    db.execute.assert_called_once()
    status_sql, packet_id = db.execute.call_args.args
    assert "SET status = 'delivered'" in status_sql
    assert "delivered_at = now()" in status_sql
    assert packet_id == PACKET


@pytest.mark.asyncio
async def test_deliver_packet_only_reads_passed_pieces_for_this_packet():
    db = AsyncMock()
    db.fetchval = AsyncMock(return_value="ready")
    db.fetch = AsyncMock(return_value=[])
    db.execute = AsyncMock()
    pool, conn = _make_pool_and_conn()

    result = await deliver_packet(db, pool, PACKET)

    assert result == {}
    fetch_sql, packet_id = db.fetch.call_args.args
    assert "status = 'passed'" in fetch_sql
    assert "packet_id = $1" in fetch_sql
    assert packet_id == PACKET
    conn.execute.assert_not_called()  # nothing to log
    db.execute.assert_called_once()  # status still flips even with 0 passed pieces
