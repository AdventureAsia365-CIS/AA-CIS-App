"""
tests/unit/test_aa464_trust_ramp_suggestion.py — AA-464: nối dây suggest_ramp_transition().

Covers the 4 new services/acp_produce/trust_ramp.py functions (compute_tenant_weeks_active,
compute_tenant_engagement_ok, compute_tenant_ramp_signals, compute_ramp_suggestion) and the 3
changed/new api/routers/admin_a4.py endpoints (GET /trust-ramp's new fields, POST
/trust-ramp/{id}/approve, POST /trust-ramp/{id}/skip).

DB mocking for trust_ramp.py functions follows tests/unit/test_aa365_trust_ramp.py's `_make_db()`
convention (plain AsyncMock, fetchval/fetch as AsyncMock with side_effect for ordered returns).
Router-level tests follow tests/unit/test_aa469_viec5_a4_feedback_loop.py's `_make_pool()`/
`_make_request()` convention (call the route handler function directly, no TestClient) and its
`_admin_secret` autouse fixture.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from services.acp_produce.trust_ramp import (compute_ramp_suggestion,
                                              compute_tenant_engagement_ok,
                                              compute_tenant_ramp_signals,
                                              compute_tenant_weeks_active)

_TEST_SECRET = "test-admin-secret"

PACKET = "pkt-1"
TENANT = "tenant-1"


@pytest.fixture(autouse=True)
def _admin_secret(monkeypatch):
    monkeypatch.setattr("api.routers.admin.ADMIN_SECRET", _TEST_SECRET)


def _make_db(fetchval_returns=None, fetch_returns=None):
    """fetchval_returns/fetch_returns: lists consumed in call order (matches
    test_aa365_trust_ramp.py's `_make_db()` shape, extended with `fetch` since the new
    engagement_ok query uses conn.fetch(), not conn.fetchval())."""
    db = AsyncMock()
    if fetchval_returns is not None:
        db.fetchval = AsyncMock(side_effect=fetchval_returns)
    if fetch_returns is not None:
        db.fetch = AsyncMock(side_effect=fetch_returns)
    return db


def _make_pool(fetch_side_effect=None, fetchval_side_effect=None, execute_return="INSERT 0 1"):
    conn = AsyncMock()
    if fetch_side_effect is not None:
        conn.fetch = AsyncMock(side_effect=fetch_side_effect)
    if fetchval_side_effect is not None:
        conn.fetchval = AsyncMock(side_effect=fetchval_side_effect)
    conn.fetchrow = AsyncMock()
    conn.execute = AsyncMock(return_value=execute_return)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


def _make_request(pool):
    req = MagicMock()
    req.app.state.pool = pool
    return req


# ── compute_tenant_weeks_active() ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_weeks_active_counts_packet_rows():
    db = _make_db(fetchval_returns=[5])
    assert await compute_tenant_weeks_active(db, TENANT) == 5
    sql, tenant_param = db.fetchval.call_args.args
    assert "acp_deliver.packets" in sql
    assert "COUNT(*)" in sql
    assert tenant_param == TENANT


@pytest.mark.asyncio
async def test_weeks_active_zero_when_no_packets():
    db = _make_db(fetchval_returns=[None])
    assert await compute_tenant_weeks_active(db, TENANT) == 0


# ── compute_tenant_engagement_ok() ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_engagement_ok_true_above_baseline_with_enough_posts():
    # 3 posts (>= CONFIDENCE_ATOM_MIN_POSTS), engagement/reach well above 0.05 baseline.
    rows = [
        {"reach": 100, "engagement": 20},
        {"reach": 100, "engagement": 20},
        {"reach": 100, "engagement": 20},
    ]
    db = _make_db(fetch_returns=[rows])
    assert await compute_tenant_engagement_ok(db, TENANT) is True


@pytest.mark.asyncio
async def test_engagement_ok_false_below_baseline():
    rows = [
        {"reach": 1000, "engagement": 1},
        {"reach": 1000, "engagement": 1},
        {"reach": 1000, "engagement": 1},
    ]
    db = _make_db(fetch_returns=[rows])
    assert await compute_tenant_engagement_ok(db, TENANT) is False


@pytest.mark.asyncio
async def test_engagement_ok_false_when_fewer_than_min_posts():
    """Fail-closed: 2 real high-engagement rows still isn't enough data to say 'ok' at the
    CONFIDENCE_ATOM_MIN_POSTS=3 gate — never fabricate True on insufficient data."""
    rows = [
        {"reach": 100, "engagement": 50},
        {"reach": 100, "engagement": 50},
    ]
    db = _make_db(fetch_returns=[rows])
    assert await compute_tenant_engagement_ok(db, TENANT) is False


@pytest.mark.asyncio
async def test_engagement_ok_false_when_no_snapshots_at_all():
    db = _make_db(fetch_returns=[[]])
    assert await compute_tenant_engagement_ok(db, TENANT) is False


@pytest.mark.asyncio
async def test_engagement_ok_query_scopes_to_tenant_and_reach_bearing_rows():
    db = _make_db(fetch_returns=[[]])
    await compute_tenant_engagement_ok(db, TENANT)
    sql, tenant_param = db.fetch.call_args.args
    assert "acp_shared.content_metric_snapshot" in sql
    assert "reach IS NOT NULL AND reach > 0" in sql
    assert tenant_param == TENANT


# ── compute_tenant_ramp_signals() ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_ramp_signals_bundles_both():
    db = _make_db(
        fetchval_returns=[4],
        fetch_returns=[[{"reach": 100, "engagement": 20}] * 3],
    )
    signals = await compute_tenant_ramp_signals(db, TENANT)
    assert signals == {"weeks_active": 4, "engagement_ok": True}


# ── compute_ramp_suggestion() ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ramp_suggestion_unknown_packet_raises():
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match="no packet"):
        await compute_ramp_suggestion(db, PACKET)


@pytest.mark.asyncio
async def test_ramp_suggestion_eligible_when_engaged_and_active():
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value={"tenant_id": TENANT, "publish_mode": "propose_only"})
    db.fetchval = AsyncMock(side_effect=[3])  # weeks_active
    db.fetch = AsyncMock(side_effect=[[{"reach": 100, "engagement": 20}] * 3])  # engagement rows

    result = await compute_ramp_suggestion(db, PACKET)

    assert result == {
        "packet_id": PACKET, "tenant_id": TENANT, "current_mode": "propose_only",
        "suggested_mode": "approve_to_publish", "eligible": True,
        "engagement_ok": True, "weeks_active": 3,
    }


@pytest.mark.asyncio
async def test_ramp_suggestion_not_eligible_when_insufficient_signals():
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value={"tenant_id": TENANT, "publish_mode": "propose_only"})
    db.fetchval = AsyncMock(side_effect=[1])  # weeks_active < 2
    db.fetch = AsyncMock(side_effect=[[]])  # no engagement data

    result = await compute_ramp_suggestion(db, PACKET)

    assert result["eligible"] is False
    assert result["suggested_mode"] == "propose_only"


# ── api.routers.admin_a4.get_trust_ramp() — AA-464 fields ──────────────────

@pytest.mark.asyncio
async def test_get_trust_ramp_includes_suggestion_fields():
    from api.routers.admin_a4 import get_trust_ramp

    packet_row = {
        "packet_id": PACKET, "tenant_id": TENANT, "tenant_name": "Test Tenant",
        "tenant_slug": "test-tenant", "year": 2026, "month": 9, "week": 1,
        "status": "delivered", "publish_mode": "propose_only",
        "created_at": None, "delivered_at": None,
    }
    # conn.fetch call order: packets query, then compute_tenant_engagement_ok's query
    # (one distinct tenant_id on the page).
    pool, conn = _make_pool(
        fetch_side_effect=[[packet_row], [{"reach": 100, "engagement": 20}] * 3],
        fetchval_side_effect=[3],  # weeks_active
    )
    req = _make_request(pool)

    result = await get_trust_ramp(req, x_admin_secret=_TEST_SECRET)

    assert result["data"][0]["engagement_ok"] is True
    assert result["data"][0]["weeks_active"] == 3
    assert result["data"][0]["suggested_mode"] == "approve_to_publish"
    assert result["data"][0]["eligible"] is True


@pytest.mark.asyncio
async def test_get_trust_ramp_wrong_secret_rejected():
    from api.routers.admin_a4 import get_trust_ramp

    pool, conn = _make_pool(fetch_side_effect=[[]])
    req = _make_request(pool)
    with pytest.raises(HTTPException):
        await get_trust_ramp(req, x_admin_secret="wrong")


# ── api.routers.admin_a4.approve_ramp_suggestion() ──────────────────────────

@pytest.mark.asyncio
async def test_approve_ramp_suggestion_calls_confirm_and_returns_200_shape():
    from api.routers.admin_a4 import approve_ramp_suggestion

    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(return_value={"tenant_id": TENANT, "publish_mode": "propose_only"})
    conn.fetchval = AsyncMock(side_effect=[
        3,  # compute_ramp_suggestion's weeks_active
        "propose_only",  # confirm_ramp_transition's own current_mode re-lookup
    ])
    conn.fetch = AsyncMock(side_effect=[[{"reach": 100, "engagement": 20}] * 3])
    req = _make_request(pool)

    result = await approve_ramp_suggestion(
        packet_id=PACKET, request=req, x_admin_secret=_TEST_SECRET, x_admin_user_id=None,
    )

    assert result["status"] == "approved"
    assert result["from_mode"] == "propose_only"
    assert result["to_mode"] == "approve_to_publish"
    # 2 execute calls inside confirm_ramp_transition(): packets UPDATE + audit_log INSERT.
    assert conn.execute.call_count == 2
    log_sql = conn.execute.call_args_list[1].args[0]
    assert "publish_mode_transition" in log_sql


@pytest.mark.asyncio
async def test_approve_ramp_suggestion_400_when_not_eligible():
    from api.routers.admin_a4 import approve_ramp_suggestion

    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(return_value={"tenant_id": TENANT, "publish_mode": "propose_only"})
    conn.fetchval = AsyncMock(side_effect=[1])  # weeks_active < 2 -> not eligible
    conn.fetch = AsyncMock(side_effect=[[]])
    req = _make_request(pool)

    with pytest.raises(HTTPException) as exc_info:
        await approve_ramp_suggestion(
            packet_id=PACKET, request=req, x_admin_secret=_TEST_SECRET, x_admin_user_id=None,
        )
    assert exc_info.value.status_code == 400
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_approve_ramp_suggestion_404_unknown_packet():
    from api.routers.admin_a4 import approve_ramp_suggestion

    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(return_value=None)
    req = _make_request(pool)

    with pytest.raises(HTTPException) as exc_info:
        await approve_ramp_suggestion(
            packet_id=PACKET, request=req, x_admin_secret=_TEST_SECRET, x_admin_user_id=None,
        )
    assert exc_info.value.status_code == 404


# ── api.routers.admin_a4.skip_ramp_suggestion() ─────────────────────────────

@pytest.mark.asyncio
async def test_skip_ramp_suggestion_logs_without_mutating_packet():
    from api.routers.admin_a4 import skip_ramp_suggestion

    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(return_value={"tenant_id": TENANT, "publish_mode": "propose_only"})
    conn.fetchval = AsyncMock(side_effect=[3])
    conn.fetch = AsyncMock(side_effect=[[{"reach": 100, "engagement": 20}] * 3])
    req = _make_request(pool)

    result = await skip_ramp_suggestion(
        packet_id=PACKET, request=req, x_admin_secret=_TEST_SECRET,
        x_admin_user_id="c18c1400-c4f8-4feb-825c-e777255b724b",
    )

    assert result["status"] == "skipped"
    assert result["from_mode"] == "propose_only"
    assert result["to_mode"] == "approve_to_publish"
    # Exactly ONE execute call (the audit_log INSERT) — never touches packets.publish_mode.
    conn.execute.assert_called_once()
    log_sql, tenant_param, actor_param, packet_param, details_json = conn.execute.call_args.args
    assert "acp_shared.audit_log" in log_sql
    assert "ramp_suggestion_skipped" in log_sql
    assert tenant_param == TENANT
    assert actor_param == "admin:c18c1400-c4f8-4feb-825c-e777255b724b"
    assert packet_param == PACKET
    details = json.loads(details_json)
    assert details == {"from": "propose_only", "to": "approve_to_publish", "dismissed": True}


@pytest.mark.asyncio
async def test_skip_ramp_suggestion_400_when_not_eligible():
    from api.routers.admin_a4 import skip_ramp_suggestion

    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(return_value={"tenant_id": TENANT, "publish_mode": "veto_window_auto"})
    conn.fetchval = AsyncMock(side_effect=[99])
    conn.fetch = AsyncMock(side_effect=[[{"reach": 100, "engagement": 20}] * 3])
    req = _make_request(pool)

    with pytest.raises(HTTPException) as exc_info:
        await skip_ramp_suggestion(
            packet_id=PACKET, request=req, x_admin_secret=_TEST_SECRET, x_admin_user_id=None,
        )
    assert exc_info.value.status_code == 400
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_skip_ramp_suggestion_admin_actor_falls_back_to_unknown():
    """Same tolerant convention as force_unpublish() (AA-455) — a missing/malformed
    x-admin-user-id doesn't 500, it records 'admin:unknown'."""
    from api.routers.admin_a4 import skip_ramp_suggestion

    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(return_value={"tenant_id": TENANT, "publish_mode": "propose_only"})
    conn.fetchval = AsyncMock(side_effect=[3])
    conn.fetch = AsyncMock(side_effect=[[{"reach": 100, "engagement": 20}] * 3])
    req = _make_request(pool)

    await skip_ramp_suggestion(
        packet_id=PACKET, request=req, x_admin_secret=_TEST_SECRET,
        x_admin_user_id="not-a-uuid",
    )
    actor_param = conn.execute.call_args.args[2]
    assert actor_param == "admin:unknown"
