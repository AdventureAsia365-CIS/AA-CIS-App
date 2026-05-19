"""
Unit tests for v1_s0 — field_coverage_pct calculation, bulk approve count,
reject notes validation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from api.routers.v1_s0 import _field_coverage_pct


# ── _field_coverage_pct ───────────────────────────────────────────────────────

def test_coverage_all_null():
    row = {
        "src_name": None, "country": None, "src_subtitle": None,
        "src_summary": None, "src_highlights": None,
        "src_itineraries": None, "price_raw": None,
    }
    assert _field_coverage_pct(row) == 0


def test_coverage_all_filled():
    row = {
        "src_name": "Tour A", "country": "Vietnam", "src_subtitle": "Sub",
        "src_summary": "Summary", "src_highlights": ["h1", "h2"],
        "src_itineraries": "Day 1: ...", "price_raw": "1200",
    }
    assert _field_coverage_pct(row) == 100


def test_coverage_partial_4_of_7():
    row = {
        "src_name": "Tour A", "country": "Vietnam",
        "src_subtitle": None,
        "src_summary": "Summary", "src_highlights": None,
        "src_itineraries": "Day 1: ...", "price_raw": None,
    }
    # 4/7 = 0.571 → round → 57
    assert _field_coverage_pct(row) == 57


def test_coverage_empty_string_not_counted():
    row = {
        "src_name": "", "country": "Vietnam", "src_subtitle": None,
        "src_summary": None, "src_highlights": None,
        "src_itineraries": None, "price_raw": None,
    }
    # src_name="" is treated as missing; only country filled = 1/7 ≈ 14
    assert _field_coverage_pct(row) == 14


def test_coverage_jsonb_empty_list_counts():
    row = {
        "src_name": "Tour", "country": "Thailand", "src_subtitle": None,
        "src_summary": None, "src_highlights": [],  # non-null even if empty
        "src_itineraries": None, "price_raw": None,
    }
    # src_name, country, src_highlights present ([] is not None, str([]) != "")
    # 3/7 ≈ 43
    assert _field_coverage_pct(row) == 43


# ── bulk_approve ──────────────────────────────────────────────────────────────

def _make_pool(execute="UPDATE 3"):
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=execute)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _make_request(pool):
    req = MagicMock()
    req.app.state.pool = pool
    req.headers = {}
    return req


TENANT = {"sub": "00000000-0000-0000-0000-000000000001", "role": "admin"}


@pytest.mark.asyncio
async def test_bulk_approve_returns_correct_count():
    from api.routers.v1_s0 import bulk_approve, BulkApproveRequest
    pool = _make_pool(execute="UPDATE 3")
    body = BulkApproveRequest(tour_ids=["id1", "id2", "id3"])
    result = await bulk_approve(body, _make_request(pool), TENANT)
    assert result["approved"] == 3
    assert "3 tours approved" in result["message"]


@pytest.mark.asyncio
async def test_bulk_approve_empty_ids_raises_400():
    from api.routers.v1_s0 import bulk_approve, BulkApproveRequest
    pool = _make_pool()
    body = BulkApproveRequest(tour_ids=[])
    with pytest.raises(HTTPException) as exc:
        await bulk_approve(body, _make_request(pool), TENANT)
    assert exc.value.status_code == 400


# ── bulk_reject ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reject_requires_non_empty_notes():
    from api.routers.v1_s0 import bulk_reject, BulkRejectRequest
    pool = _make_pool()
    for bad_notes in ("", "   ", "\t"):
        body = BulkRejectRequest(tour_ids=["id1"], notes=bad_notes)
        with pytest.raises(HTTPException) as exc:
            await bulk_reject(body, _make_request(pool), TENANT)
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_reject_succeeds_with_notes():
    from api.routers.v1_s0 import bulk_reject, BulkRejectRequest
    pool = _make_pool(execute="UPDATE 2")
    body = BulkRejectRequest(tour_ids=["id1", "id2"], notes="Price data missing")
    result = await bulk_reject(body, _make_request(pool), TENANT)
    assert result["rejected"] == 2


@pytest.mark.asyncio
async def test_reject_empty_ids_raises_400():
    from api.routers.v1_s0 import bulk_reject, BulkRejectRequest
    pool = _make_pool()
    body = BulkRejectRequest(tour_ids=[], notes="Some notes")
    with pytest.raises(HTTPException) as exc:
        await bulk_reject(body, _make_request(pool), TENANT)
    assert exc.value.status_code == 400
