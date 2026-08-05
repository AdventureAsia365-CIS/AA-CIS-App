"""AA-361 [N8-1] — usage_log write-back, B8-safe per-piece scoping.

Core regression is the B8 case: a packet with piece A (cites atoms 1,2) and
piece B (cites atoms 3,4) must never cross-contaminate — atom 1/2 get an
entry from A only, atom 3/4 an entry from B only. The prototype bug
(aamc/delivery.py) unioned all pieces' atoms before logging; this suite
proves services.acp_produce.atom_usage never does that.

Pool/conn mocking follows the same pool.acquire() context-manager shape used
in test_aa299_atom_insert.py / test_aa242_regenerate_supersede.py.
"""
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.acp_produce.atom_usage import (atom_ids_cited,
                                              build_usage_entries,
                                              write_usage_log)
from services.acp_produce.models import Piece


def _piece(piece_id, body_tagged, status="passed"):
    return Piece(piece_id=piece_id, body_tagged=body_tagged, status=status)


def _make_pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _fake_conn():
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=_TxnCM())
    return conn


class _TxnCM:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


# ── atom_ids_cited() — pure tag parsing ─────────────────────────────────────

def test_atom_ids_cited_extracts_r_tags_only_deduped_first_seen_order():
    piece = _piece("p1", "Sentence one [R:atom_2]. Sentence two [R:atom_1] and [R:atom_2] again.")
    assert atom_ids_cited(piece) == ["atom_2", "atom_1"]


def test_atom_ids_cited_ignores_fact_tags():
    piece = _piece("p1", "A fact [F:fact_9] and an atom [R:atom_1].")
    assert atom_ids_cited(piece) == ["atom_1"]


def test_atom_ids_cited_empty_body_returns_empty_list():
    piece = _piece("p1", "")
    assert atom_ids_cited(piece) == []


# ── build_usage_entries() — B8 regression (the core requirement) ───────────

def test_build_usage_entries_does_not_cross_contaminate_between_pieces():
    """B8 regression: piece A's atoms must never appear under piece B's
    entries and vice versa — no union anywhere."""
    piece_a = _piece("piece_A", "Cites [R:atom_1] and [R:atom_2].")
    piece_b = _piece("piece_B", "Cites [R:atom_3] and [R:atom_4].")

    entries = build_usage_entries([piece_a, piece_b], today=date(2026, 8, 5))

    assert set(entries.keys()) == {"atom_1", "atom_2", "atom_3", "atom_4"}

    for atom_id in ("atom_1", "atom_2"):
        piece_ids = {e["piece_id"] for e in entries[atom_id]}
        assert piece_ids == {"piece_A"}, f"{atom_id} must only be credited to piece_A, got {piece_ids}"

    for atom_id in ("atom_3", "atom_4"):
        piece_ids = {e["piece_id"] for e in entries[atom_id]}
        assert piece_ids == {"piece_B"}, f"{atom_id} must only be credited to piece_B, got {piece_ids}"


def test_build_usage_entries_skips_non_passed_pieces():
    held = _piece("p_held", "Cites [R:atom_1].", status="held")
    in_progress = _piece("p_wip", "Cites [R:atom_2].", status="in_progress")

    entries = build_usage_entries([held, in_progress], today=date(2026, 8, 5))

    assert entries == {}


def test_build_usage_entries_dedupes_same_atom_cited_twice_in_one_piece():
    piece = _piece("p1", "First [R:atom_1] then again [R:atom_1] later.")
    entries = build_usage_entries([piece], today=date(2026, 8, 5))
    assert len(entries["atom_1"]) == 1


def test_build_usage_entries_entry_shape_date_and_optional_channel():
    piece = _piece("p1", "Cites [R:atom_1].")
    entries = build_usage_entries([piece], today=date(2026, 8, 5), channel_by_piece_id={"p1": "blog"})
    entry = entries["atom_1"][0]
    assert entry == {"piece_id": "p1", "date": "2026-08-05", "channel": "blog"}


def test_build_usage_entries_omits_channel_key_when_not_supplied():
    piece = _piece("p1", "Cites [R:atom_1].")
    entries = build_usage_entries([piece], today=date(2026, 8, 5))
    entry = entries["atom_1"][0]
    assert "channel" not in entry
    assert entry == {"piece_id": "p1", "date": "2026-08-05"}


def test_build_usage_entries_atom_with_no_citations_gets_no_entry():
    piece = _piece("p1", "No citations at all in this body.")
    entries = build_usage_entries([piece], today=date(2026, 8, 5))
    assert entries == {}


# ── write_usage_log() — DB wrapper, same B8 guarantee end-to-end ───────────

@pytest.mark.asyncio
async def test_write_usage_log_issues_one_update_per_atom_no_cross_contamination():
    piece_a = _piece("piece_A", "Cites [R:atom_1] and [R:atom_2].")
    piece_b = _piece("piece_B", "Cites [R:atom_3] and [R:atom_4].")
    conn = _fake_conn()
    pool = _make_pool(conn)

    result = await write_usage_log([piece_a, piece_b], pool, today=date(2026, 8, 5))

    assert result == {"atom_1": 1, "atom_2": 1, "atom_3": 1, "atom_4": 1}
    assert conn.execute.call_count == 4

    calls_by_atom = {}
    for call in conn.execute.call_args_list:
        sql, atom_id, entries_json = call.args
        assert "UPDATE acp_contract.tour_atoms" in sql
        assert "usage_log = usage_log || $2::jsonb" in sql
        calls_by_atom[atom_id] = json.loads(entries_json)

    assert {e["piece_id"] for e in calls_by_atom["atom_1"]} == {"piece_A"}
    assert {e["piece_id"] for e in calls_by_atom["atom_2"]} == {"piece_A"}
    assert {e["piece_id"] for e in calls_by_atom["atom_3"]} == {"piece_B"}
    assert {e["piece_id"] for e in calls_by_atom["atom_4"]} == {"piece_B"}


@pytest.mark.asyncio
async def test_write_usage_log_no_op_when_nothing_passed():
    held = _piece("p_held", "Cites [R:atom_1].", status="held")
    conn = _fake_conn()
    pool = _make_pool(conn)

    result = await write_usage_log([held], pool, today=date(2026, 8, 5))

    assert result == {}
    conn.execute.assert_not_called()
