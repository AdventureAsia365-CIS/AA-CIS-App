"""Unit tests for H-3 Mistake→Rule pipeline — Bedrock mocked."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.acp_shared.h3_rule_extractor import (
    extract_and_save_rule,
    H3_CONFIDENCE_THRESHOLD,
)

_RULE_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_HITL_ID = "bbbbbbbb-0000-0000-0000-000000000001"
_RUN_ID  = "cccccccc-0000-0000-0000-000000000001"
_TENANT  = "00000000-0000-0000-0000-000000000001"


def _make_pool(rule_id=_RULE_ID):
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=rule_id)
    conn.fetchrow = AsyncMock(return_value={"tenant_id": _TENANT})
    # async context manager for pool.acquire()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    return pool, conn


def _haiku_response(should_extract=True, confidence=0.90, pattern="trip of a lifetime",
                    rule_type="block"):
    """AA-491 STEP0: _call_haiku()'s real signature is `tuple[dict, int, int]` (see
    services/acp_shared/h3_rule_extractor.py -- `extracted, in_tok, out_tok = _call_haiku(...)`).
    This helper used to return a bare dict, so every `return_value=_haiku_response(...)` mock
    handed extract_and_save_rule() a 6-key dict where it expected a 3-tuple -- unpacking a dict
    yields its keys, so `a, b, c = <6-key dict>` raised "too many values to unpack (expected
    3)" every time, silently caught by extract_and_save_rule()'s own `except Exception` and
    logged as h3_haiku_failed -- never a LANGFUSE_PUBLIC_KEY or DB-fixture gap (the initial
    suspicion in AA-491), a real pre-existing mock/signature mismatch. Now returns the same
    3-tuple shape the real function does."""
    extracted = {
        "should_extract": should_extract,
        "confidence": confidence,
        "rule_type": rule_type,
        "pattern": pattern,
        "description": "Banned generic phrase — voice violation",
        "reasoning": "Clear, unambiguous brand violation pattern",
    }
    return extracted, 120, 40


@pytest.mark.asyncio
async def test_h3_creates_rule_when_confidence_high():
    pool, conn = _make_pool()
    with patch("services.acp_shared.h3_rule_extractor._call_haiku",
               return_value=_haiku_response(confidence=0.92)):
        result = await extract_and_save_rule(
            pool, _HITL_ID, _RUN_ID, gate_number=2,
            reviewer_notes="The content used 'trip of a lifetime' — brand forbids this phrase.",
        )
    assert result == _RULE_ID
    # INSERT into acp_output_rules happened
    conn.fetchval.assert_called_once()
    # rule_created_id back-fill happened (execute called at least 3 times)
    assert conn.execute.call_count >= 3


@pytest.mark.asyncio
async def test_h3_skips_when_confidence_below_threshold():
    pool, conn = _make_pool()
    with patch("services.acp_shared.h3_rule_extractor._call_haiku",
               return_value=_haiku_response(confidence=0.70)):
        result = await extract_and_save_rule(
            pool, _HITL_ID, _RUN_ID, gate_number=2,
            reviewer_notes="Content didn't feel right for our brand.",
        )
    assert result is None
    conn.fetchval.assert_not_called()  # no INSERT into acp_output_rules


@pytest.mark.asyncio
async def test_h3_skips_when_should_extract_false():
    pool, conn = _make_pool()
    with patch("services.acp_shared.h3_rule_extractor._call_haiku",
               return_value=_haiku_response(should_extract=False, confidence=0.95)):
        result = await extract_and_save_rule(
            pool, _HITL_ID, _RUN_ID, gate_number=3,
            reviewer_notes="I just prefer a different overall tone.",
        )
    assert result is None
    conn.fetchval.assert_not_called()


@pytest.mark.asyncio
async def test_h3_skips_empty_notes():
    pool, conn = _make_pool()
    result = await extract_and_save_rule(
        pool, _HITL_ID, _RUN_ID, gate_number=2, reviewer_notes="",
    )
    assert result is None
    conn.execute.assert_not_called()
    conn.fetchval.assert_not_called()


@pytest.mark.asyncio
async def test_h3_skips_short_notes():
    pool, conn = _make_pool()
    result = await extract_and_save_rule(
        pool, _HITL_ID, _RUN_ID, gate_number=2, reviewer_notes="bad",
    )
    assert result is None
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_h3_handles_haiku_failure_gracefully():
    pool, conn = _make_pool()
    with patch("services.acp_shared.h3_rule_extractor._call_haiku",
               side_effect=Exception("Bedrock timeout")):
        result = await extract_and_save_rule(
            pool, _HITL_ID, _RUN_ID, gate_number=2,
            reviewer_notes="Content uses banned phrase 'hidden gem'.",
        )
    assert result is None  # no crash, graceful fallback
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_h3_writes_structured_note_even_when_below_threshold():
    """rejection_note_structured must always be written for audit."""
    pool, conn = _make_pool()
    with patch("services.acp_shared.h3_rule_extractor._call_haiku",
               return_value=_haiku_response(confidence=0.65)):
        await extract_and_save_rule(
            pool, _HITL_ID, _RUN_ID, gate_number=2,
            reviewer_notes="The wording felt a bit too promotional.",
        )
    # rejection_note_structured UPDATE was called
    update_calls = [str(call) for call in conn.execute.call_args_list]
    assert any("rejection_note_structured" in c for c in update_calls)


@pytest.mark.asyncio
async def test_h3_threshold_boundary():
    """Exactly at threshold (0.80) should create rule."""
    pool, conn = _make_pool()
    with patch("services.acp_shared.h3_rule_extractor._call_haiku",
               return_value=_haiku_response(confidence=H3_CONFIDENCE_THRESHOLD)):
        result = await extract_and_save_rule(
            pool, _HITL_ID, _RUN_ID, gate_number=2,
            reviewer_notes="The calendar includes 'exclusive deals' which is forbidden.",
        )
    assert result == _RULE_ID
