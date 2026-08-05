"""
services.acp_produce.atom_usage — AA-361 [N8-1] usage_log write-back for
acp_contract.tour_atoms.

STEP 0 (AA-361, see docs/implementation-notes/AA-361.md) confirmed usage_log/
weight already exist (migration 079) and are READ by
services/acp_planning/quarter.py (big-rock atom selection, ~line 162) and
allocator.py (weight multiplier, ~line 66), but nothing in the repo writes
usage_log — every atom looks permanently unused. This module is the missing
write-back. It is independent of the not-yet-built Weekly Packet (N8-4,
AA-364): it takes any list of gated Piece objects and returns/persists
per-atom usage entries; N8-4 calls it once real packet assembly exists.

Piece (services.acp_produce.models) has no explicit atom_ids field — STEP 0
confirmed this is NOT a blocker: every atom a piece actually used is already
recorded in its own body_tagged as a "[R:atom_id]" citation tag, the same
convention gate_grounding() (F1, gates.py) and s1_from_atom.py's CITE_RE
already rely on. Parsing each piece's OWN body_tagged, independently, is what
keeps this naturally scoped per-piece.

Bug B8 (prototype docs/AI-gent-for automation works/aa-marketing-v2/aamc/
delivery.py:41-49,66-74 — gitignored dead code, never imported by the real
app) computed `used_atom_ids` as the UNION of every atom cited by EVERY piece
in a packet, then looped every passed piece over that whole union — every
piece got credited with every OTHER piece's atoms too. Avoided here
structurally: atom_ids_cited() takes ONE piece and reads only that piece's
own body_tagged; there is no cross-piece collection anywhere in this module.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional

from services.acp_produce.models import Piece

# "R:" = atom reference/citation, same convention as
# services/content_generation/s1_from_atom.py's CITE_RE ("[R:atom_xxx]").
# gates.py's TAG_RE additionally accepts "F:" (non-atom fact citations, per
# its own docstring "the atom/fact set assigned to this brief") —
# deliberately excluded here: usage_log lives on acp_contract.tour_atoms rows
# only, and an [F:...] id is never a row in that table.
ATOM_CITE_RE = re.compile(r"\[R:([^\]]+)\]")


def atom_ids_cited(piece: Piece) -> list[str]:
    """Unique atom ids this ONE piece's own body_tagged cites, first-seen
    order. Pure — no DB, no other pieces involved (see module docstring re:
    bug B8)."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for atom_id in ATOM_CITE_RE.findall(piece.body_tagged or ""):
        if atom_id not in seen_set:
            seen_set.add(atom_id)
            seen.append(atom_id)
    return seen


def build_usage_entries(
    pieces: list[Piece],
    today: Optional[date] = None,
    channel_by_piece_id: Optional[dict[str, str]] = None,
) -> dict[str, list[dict]]:
    """Pure computation (no DB): atom_id -> list of new usage_log entries to
    append, one entry per (atom, piece) pair, built ONLY from pieces with
    status == "passed" — held/in_progress pieces are never logged.
    `channel_by_piece_id` is optional since Piece has no channel field yet;
    N8-4's real packet assembly can supply it without changing this
    function."""
    today = today or date.today()
    channel_by_piece_id = channel_by_piece_id or {}
    entries: dict[str, list[dict]] = {}
    for piece in pieces:
        if piece.status != "passed":
            continue
        for atom_id in atom_ids_cited(piece):
            entry = {"piece_id": piece.piece_id, "date": today.isoformat()}
            channel = channel_by_piece_id.get(piece.piece_id)
            if channel:
                entry["channel"] = channel
            entries.setdefault(atom_id, []).append(entry)
    return entries


async def write_usage_log(
    pieces: list[Piece],
    pool,
    today: Optional[date] = None,
    channel_by_piece_id: Optional[dict[str, str]] = None,
) -> dict[str, int]:
    """DB-wiring wrapper around build_usage_entries(). Appends to the
    existing JSONB usage_log column (migration 079) via `||` concat — no
    schema change. Returns {atom_id: entries_appended} for the caller to
    log/verify."""
    entries_by_atom = build_usage_entries(pieces, today, channel_by_piece_id)
    if not entries_by_atom:
        return {}
    async with pool.acquire() as conn:
        async with conn.transaction():
            for atom_id, entries in entries_by_atom.items():
                await conn.execute(
                    """
                    UPDATE acp_contract.tour_atoms
                    SET usage_log = usage_log || $2::jsonb, updated_at = now()
                    WHERE atom_id = $1
                    """,
                    atom_id, json.dumps(entries),
                )
    return {atom_id: len(entries) for atom_id, entries in entries_by_atom.items()}


__all__ = ["ATOM_CITE_RE", "atom_ids_cited", "build_usage_entries", "write_usage_log"]
