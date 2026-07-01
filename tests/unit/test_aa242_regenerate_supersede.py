"""AA-242 — admin_supersede_review endpoint (Regenerate flow row-closeout).

Tests drive the REAL endpoint coroutine (api.routers.admin_pipeline.admin_supersede_review),
not a re-implemented copy. No live DB / no AWS: asyncpg is mocked via the same pool.acquire()
context-manager shape used in tests/unit/test_aa211_212_gate_hitl.py.

verify_admin_secret is patched to a no-op (it reads a module-level ADMIN_SECRET that is unset
in the test env and would otherwise 503 before the endpoint body runs).
"""
import asyncpg
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from api.routers.admin_pipeline import admin_supersede_review


REVIEW_ID = "33333333-3333-3333-3333-333333333333"


# ── Mock plumbing (mirrors test_aa211_212_gate_hitl.py) ───────────────────────

def _make_pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _make_request(pool):
    req = MagicMock()
    req.app.state.pool = pool
    req.headers = {}
    return req


@pytest.fixture(autouse=True)
def _no_admin_secret():
    """Bypass admin-secret auth so tests exercise the endpoint body, not the 503/403 guard."""
    with patch("api.routers.admin_pipeline.verify_admin_secret", MagicMock()):
        yield


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_supersede_success():
    """pending row → UPDATE 1 → {"status": "superseded", "review_id": id}; SQL targets
    the pending row by id."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    req = _make_request(_make_pool(conn))

    res = await admin_supersede_review(REVIEW_ID, req, x_admin_secret="s")

    assert res == {"status": "superseded", "review_id": REVIEW_ID}

    # SQL shape: UPDATE the review_queue row, guarded on id + pending, set to superseded
    conn.execute.assert_awaited_once()
    sql, arg = conn.execute.await_args.args
    assert "UPDATE silver_aa_internal.review_queue" in sql
    assert "review_status = 'superseded'::review_status_enum" in sql
    assert "WHERE id = $1::uuid" in sql
    assert "review_status = 'pending'" in sql
    assert arg == REVIEW_ID


@pytest.mark.asyncio
async def test_supersede_already_closed_returns_409():
    """Row already approved/rejected/superseded → WHERE matches nothing → UPDATE 0 → 409."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    req = _make_request(_make_pool(conn))

    with pytest.raises(HTTPException) as exc:
        await admin_supersede_review(REVIEW_ID, req, x_admin_secret="s")

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_supersede_invalid_uuid():
    """The endpoint has NO UUID guard — it hands review_id straight to `$1::uuid`. A malformed
    id makes asyncpg raise on the cast (InvalidTextRepresentationError ⊂ DataError). The endpoint
    does not catch it, so it propagates unchanged (surfaces as a 500 upstream, NOT a 409/422)."""
    conn = AsyncMock()
    conn.execute = AsyncMock(
        side_effect=asyncpg.exceptions.InvalidTextRepresentationError(
            "invalid input syntax for type uuid: \"not-a-uuid\""
        )
    )
    req = _make_request(_make_pool(conn))

    with pytest.raises(asyncpg.exceptions.DataError):
        await admin_supersede_review("not-a-uuid", req, x_admin_secret="s")
