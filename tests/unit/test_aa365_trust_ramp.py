"""
tests/unit/test_aa365_trust_ramp.py — services/acp_produce/trust_ramp.py
(AA-365: 3-state trust ramp on top of packets.publish_mode, Decision log via
acp_shared.audit_log, hard BOFU/pricing veto_window_auto block).

DB mocking follows tests/unit/test_aa367_packets.py's `_make_db()`/`_Row`
convention.
"""
from unittest.mock import AsyncMock

import pytest

from services.acp_produce.trust_ramp import (RAMP, BofuVetoBlockedError,
                                              confirm_ramp_transition,
                                              packet_has_bofu_piece,
                                              suggest_ramp_transition)

PACKET = "pkt-1"
TENANT = "tenant-1"
ACTOR = "reviewer-1"


def _make_db(fetchval_returns=None, execute_return="INSERT 0 1"):
    """fetchval_returns: list consumed in call order (current_mode, then
    packet_has_bofu_piece's EXISTS result, ...)."""
    db = AsyncMock()
    if fetchval_returns is not None:
        db.fetchval = AsyncMock(side_effect=fetchval_returns)
    db.execute = AsyncMock(return_value=execute_return)
    return db


# ── suggest_ramp_transition() — pure function, no DB ───────────────────────

def test_suggest_advances_when_engaged_and_active_long_enough():
    assert suggest_ramp_transition("propose_only", engagement_ok=True, weeks_active=2) \
        == "approve_to_publish"


def test_suggest_stays_when_not_engaged():
    assert suggest_ramp_transition("propose_only", engagement_ok=False, weeks_active=10) \
        == "propose_only"


def test_suggest_stays_when_not_active_long_enough():
    assert suggest_ramp_transition("propose_only", engagement_ok=True, weeks_active=1) \
        == "propose_only"


def test_suggest_stays_at_top_of_ramp():
    assert suggest_ramp_transition("veto_window_auto", engagement_ok=True, weeks_active=99) \
        == "veto_window_auto"


def test_suggest_unknown_mode_treated_as_bottom_of_ramp():
    assert suggest_ramp_transition("bogus", engagement_ok=True, weeks_active=2) \
        == "approve_to_publish"


# ── packet_has_bofu_piece() ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_packet_has_bofu_piece_true():
    db = _make_db(fetchval_returns=[True])
    assert await packet_has_bofu_piece(db, PACKET) is True
    sql, packet_id = db.fetchval.call_args.args
    assert "acp_shared.acp_v2_slots" in sql
    assert "funnel_stage" in sql
    assert "BOFU" in sql
    assert packet_id == PACKET


@pytest.mark.asyncio
async def test_packet_has_bofu_piece_false():
    db = _make_db(fetchval_returns=[False])
    assert await packet_has_bofu_piece(db, PACKET) is False


# ── confirm_ramp_transition() ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_rejects_invalid_mode():
    db = _make_db()
    with pytest.raises(ValueError, match="not a valid ramp state"):
        await confirm_ramp_transition(db, packet_id=PACKET, tenant_id=TENANT,
                                       mode="bogus", actor=ACTOR)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_rejects_unknown_packet():
    db = _make_db(fetchval_returns=[None])
    with pytest.raises(ValueError, match="no packet"):
        await confirm_ramp_transition(db, packet_id=PACKET, tenant_id=TENANT,
                                       mode="propose_only", actor=ACTOR)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_propose_only_succeeds_and_logs():
    # fetchval order: current_mode lookup, then set_publish_mode has no fetchval call.
    db = _make_db(fetchval_returns=["propose_only"])

    await confirm_ramp_transition(db, packet_id=PACKET, tenant_id=TENANT,
                                   mode="propose_only", actor=ACTOR)

    # 2 execute calls: set_publish_mode's UPDATE, then the audit_log INSERT.
    assert db.execute.call_count == 2
    update_sql = db.execute.call_args_list[0].args[0]
    assert "UPDATE acp_deliver.packets" in update_sql
    log_sql, tenant_id, actor, packet_id, details_json = db.execute.call_args_list[1].args
    assert "acp_shared.audit_log" in log_sql
    assert "publish_mode_transition" in log_sql
    assert tenant_id == TENANT
    assert actor == ACTOR
    assert packet_id == PACKET
    import json
    details = json.loads(details_json)
    assert details == {"from": "propose_only", "to": "propose_only",
                        "blocked": False, "block_reason": None}


@pytest.mark.asyncio
async def test_confirm_approve_to_publish_succeeds_and_logs_since_aa365_unlock():
    """AA-365 (14/08/2026) widened ALLOWED_PUBLISH_MODES_UNTIL_F6 — this no
    longer raises PublishModeBlockedError."""
    db = _make_db(fetchval_returns=["propose_only"])

    await confirm_ramp_transition(db, packet_id=PACKET, tenant_id=TENANT,
                                   mode="approve_to_publish", actor=ACTOR)

    # 2 execute calls: set_publish_mode's UPDATE, then the audit_log INSERT.
    assert db.execute.call_count == 2
    update_sql, mode_param, packet_param = db.execute.call_args_list[0].args
    assert "UPDATE acp_deliver.packets" in update_sql
    assert mode_param == "approve_to_publish"
    assert packet_param == PACKET
    import json
    details = json.loads(db.execute.call_args_list[1].args[4])
    assert details == {"from": "propose_only", "to": "approve_to_publish",
                        "blocked": False, "block_reason": None}


@pytest.mark.asyncio
async def test_confirm_veto_window_auto_succeeds_for_non_bofu_packet_since_aa365_unlock():
    # fetchval order: current_mode lookup, then packet_has_bofu_piece's EXISTS (False).
    db = _make_db(fetchval_returns=["approve_to_publish", False])

    await confirm_ramp_transition(db, packet_id=PACKET, tenant_id=TENANT,
                                   mode="veto_window_auto", actor=ACTOR)

    assert db.execute.call_count == 2
    update_sql, mode_param, packet_param = db.execute.call_args_list[0].args
    assert "UPDATE acp_deliver.packets" in update_sql
    assert mode_param == "veto_window_auto"
    import json
    details = json.loads(db.execute.call_args_list[1].args[4])
    assert details == {"from": "approve_to_publish", "to": "veto_window_auto",
                        "blocked": False, "block_reason": None}


@pytest.mark.asyncio
async def test_confirm_veto_window_auto_still_blocked_for_bofu_packet_after_aa365_unlock():
    """The one thing AA-365's unlock must NOT touch: a packet holding >=1
    BOFU piece still cannot reach veto_window_auto, even now that
    ALLOWED_PUBLISH_MODES_UNTIL_F6 allows the mode itself."""
    # fetchval order: current_mode lookup, then packet_has_bofu_piece's EXISTS (True).
    db = _make_db(fetchval_returns=["approve_to_publish", True])

    with pytest.raises(BofuVetoBlockedError, match="approval-forever"):
        await confirm_ramp_transition(db, packet_id=PACKET, tenant_id=TENANT,
                                       mode="veto_window_auto", actor=ACTOR)

    # BOFU check short-circuits BEFORE set_publish_mode is ever called ->
    # only the audit_log INSERT ran, no packets UPDATE attempt.
    assert db.execute.call_count == 1
    log_sql = db.execute.call_args.args[0]
    assert "acp_shared.audit_log" in log_sql
    import json
    details = json.loads(db.execute.call_args.args[4])
    assert details == {
        "from": "approve_to_publish", "to": "veto_window_auto",
        "blocked": True,
        "block_reason": "BOFU/pricing content is approval-forever, never veto_window_auto",
    }


def test_ramp_and_allowed_publish_modes_stay_in_sync():
    """Guards against RAMP (trust_ramp.py) and ALLOWED_PUBLISH_MODES_UNTIL_F6
    (packets.py) silently drifting apart now that both are the same 3
    states (AA-365 unlock) — a future edit to one without the other should
    fail this test."""
    from services.acp_produce.packets import ALLOWED_PUBLISH_MODES_UNTIL_F6
    assert set(RAMP) == ALLOWED_PUBLISH_MODES_UNTIL_F6


def test_full_ramp_propose_only_to_veto_window_auto_for_non_bofu_packet():
    """Pure suggest_ramp_transition() walk through all 3 states — confirms
    the ramp itself is fully traversable now that AA-365 unlocked
    set_publish_mode(); the DB-level confirm() path is covered by the
    async tests above."""
    mode = "propose_only"
    for _ in range(len(RAMP) - 1):
        mode = suggest_ramp_transition(mode, engagement_ok=True, weeks_active=2)
    assert mode == "veto_window_auto"


def test_ramp_constant_matches_prototype():
    assert RAMP == ["propose_only", "approve_to_publish", "veto_window_auto"]
