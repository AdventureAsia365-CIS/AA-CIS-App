"""
tests/unit/test_aa412_piece_review.py — services/acp_produce/packets.py
(AA-412: set_piece_review_status() / packet_pieces_review_complete() — the
per-piece human review state, independent of the pieces.status gate outcome
and of the packet's own publish_mode ramp. See docs/implementation-notes/
AA-412.md D1/D2 for the full decision record.

DB mocking follows tests/unit/test_aa367_packets.py's `_make_db()` convention.
"""
from unittest.mock import AsyncMock

import pytest

from services.acp_produce.packets import (PieceNotFoundError,
                                            packet_pieces_review_complete,
                                            set_piece_review_status)

PACKET = "pkt-1"
PIECE = "slot_abc:blog"
ACTOR = "reviewer-1"


class _Row(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _make_db(fetchrow_return=None, execute_return="UPDATE 1"):
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=fetchrow_return)
    db.execute = AsyncMock(return_value=execute_return)
    return db


# ── set_piece_review_status() ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_piece_review_status_approved():
    db = _make_db(execute_return="UPDATE 1")

    await set_piece_review_status(db, PIECE, "approved", ACTOR, note="looks good")

    db.execute.assert_called_once()
    sql, decision, actor, note, piece_id = db.execute.call_args.args
    assert "UPDATE acp_deliver.pieces" in sql
    assert "review_status" in sql
    assert decision == "approved"
    assert actor == ACTOR
    assert note == "looks good"
    assert piece_id == PIECE


@pytest.mark.asyncio
async def test_set_piece_review_status_rejected_note_optional():
    db = _make_db(execute_return="UPDATE 1")

    await set_piece_review_status(db, PIECE, "rejected", ACTOR)

    _, decision, _, note, _ = db.execute.call_args.args
    assert decision == "rejected"
    assert note is None


@pytest.mark.asyncio
async def test_set_piece_review_status_rejects_invalid_decision():
    db = _make_db()
    with pytest.raises(ValueError, match="decision must be"):
        await set_piece_review_status(db, PIECE, "maybe", ACTOR)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_set_piece_review_status_raises_on_unknown_piece():
    db = _make_db(execute_return="UPDATE 0")
    with pytest.raises(PieceNotFoundError, match=PIECE):
        await set_piece_review_status(db, PIECE, "approved", ACTOR)


# ── packet_pieces_review_complete() ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_review_complete_true_when_all_approved():
    db = _make_db(fetchrow_return=_Row({"total": 3, "approved": 3}))
    assert await packet_pieces_review_complete(db, PACKET) is True


@pytest.mark.asyncio
async def test_review_complete_false_when_some_pending():
    db = _make_db(fetchrow_return=_Row({"total": 3, "approved": 2}))
    assert await packet_pieces_review_complete(db, PACKET) is False


@pytest.mark.asyncio
async def test_review_complete_false_when_packet_has_zero_pieces():
    """A packet with no pieces assigned yet is never 'review complete' — a
    truthy result here must never be usable as an excuse to skip review."""
    db = _make_db(fetchrow_return=_Row({"total": 0, "approved": 0}))
    assert await packet_pieces_review_complete(db, PACKET) is False


@pytest.mark.asyncio
async def test_review_complete_false_when_one_piece_rejected():
    """A rejected piece counts against 'approved', same as 'pending' —
    review_complete requires unanimous approval, not just "no pendings
    left" (docs/implementation-notes/AA-412.md D3)."""
    db = _make_db(fetchrow_return=_Row({"total": 3, "approved": 2}))
    assert await packet_pieces_review_complete(db, PACKET) is False
