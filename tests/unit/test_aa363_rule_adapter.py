"""AA-363 — rule_adapter.py: apply_output_rules() wired into N7 Piece.

Core requirement: prove the adapter is not a no-op wrapper. A rule pattern
present in a Piece's body_tagged must actually be caught (test_*_with_adapter
tests below) — and, as the counter-proof the issue explicitly asked for,
calling the REAL apply_output_rules() on a Piece WITHOUT going through the
adapter must fail open (test_no_adapter_fails_open) so the reason the
adapter exists is documented, not just asserted.

DB mock follows the exact convention already used for apply_output_rules()
itself in tests/unit/test_acp_post_processor.py (_Row/_make_rule/_make_db).
"""
from unittest.mock import AsyncMock

import pytest

from api.services.acp_post_processor import apply_output_rules
from services.acp_produce.models import Piece
from services.acp_produce.rule_adapter import (apply_output_rules_to_piece,
                                                piece_to_rule_input)


class _Row(dict):
    """Minimal asyncpg Record mock — supports both dict[key] and .key access."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _make_rule(rule_id, rule_type, pattern, action_value=None, error_message=None):
    return _Row({
        "rule_id": rule_id,
        "rule_type": rule_type,
        "pattern": pattern,
        "action_value": action_value,
        "error_message": error_message or f"Rule {rule_id} violated",
    })


def _make_db(rules):
    db = AsyncMock()
    db.fetch = AsyncMock(return_value=rules)
    db.execute = AsyncMock()
    return db


def _piece(body_tagged):
    return Piece(piece_id="p1", body_tagged=body_tagged, status="in_progress")


TENANT = "00000000-0000-0000-0000-000000000001"


# ── piece_to_rule_input() — pure ────────────────────────────────────────────

def test_piece_to_rule_input_maps_body_tagged_to_content():
    piece = _piece("A great travel piece [R:atom_1].")
    assert piece_to_rule_input(piece) == {"content": "A great travel piece [R:atom_1]."}


def test_piece_to_rule_input_handles_empty_body():
    piece = _piece("")
    assert piece_to_rule_input(piece) == {"content": ""}


# ── apply_output_rules_to_piece() WITH adapter — real rejection happens ────

@pytest.mark.asyncio
async def test_block_rule_caught_with_adapter():
    rules = [_make_rule("r1", "block", "hidden gem", error_message="Generic cliché")]
    db = _make_db(rules)
    piece = _piece("This trip takes you to a hidden gem in the mountains.")

    result = await apply_output_rules_to_piece(piece, stage=None, tenant_id=TENANT, db=db)

    assert result.gate == "output_rules"
    assert result.passed is False
    assert any("r1" in v for v in result.violations)


@pytest.mark.asyncio
async def test_flag_rule_caught_with_adapter():
    rules = [_make_rule("r2", "flag", "tour_id", error_message="Raw DB field leak")]
    db = _make_db(rules)
    piece = _piece("Details: tour_id=abc123 for this route.")

    result = await apply_output_rules_to_piece(piece, stage=None, tenant_id=TENANT, db=db)

    assert result.passed is False
    assert any("r2" in v for v in result.violations)


@pytest.mark.asyncio
async def test_clean_content_passes_with_adapter():
    rules = [_make_rule("r3", "block", "hidden gem")]
    db = _make_db(rules)
    piece = _piece("A well-written piece about Sapa trekking routes.")

    result = await apply_output_rules_to_piece(piece, stage=None, tenant_id=TENANT, db=db)

    assert result.passed is True
    assert result.violations == []


# ── Counter-proof: WITHOUT the adapter, the real function fails open ──────

@pytest.mark.asyncio
async def test_no_adapter_fails_open():
    """Calling the REAL apply_output_rules() directly with a raw dict keyed
    by "body_tagged" (i.e. skipping piece_to_rule_input()) must silently let
    a banned pattern through — this is the exact failure mode the adapter
    exists to prevent, proven here rather than just asserted in a comment."""
    rules = [_make_rule("r1", "block", "hidden gem", error_message="Generic cliché")]
    db = _make_db(rules)
    piece = _piece("This trip takes you to a hidden gem in the mountains.")

    raw_output = {"body_tagged": piece.body_tagged}  # no adapter — wrong key
    result = await apply_output_rules(raw_output, stage=None, tenant_id=TENANT, db=db)

    # Fail-open: no exception raised, no rule triggered, despite "hidden gem"
    # being present in the piece's actual text.
    assert result["rules_applied"] == []
    assert result["review_flags"] == []
