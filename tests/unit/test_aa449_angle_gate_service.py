"""AA-449 — services/acp_angle_gate/service.py (request lifecycle). Mocked asyncpg pool, same
convention test_aa448_v1_planning.py already uses. generate_angles() is patched — this file
tests the DB lifecycle/state-machine, not LLM behavior (see test_aa449_angle_gate_generate.py
for that)."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_angle_gate import service

TENANT_ID = uuid.uuid4()
OTHER_TENANT_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
TRIP_ID = uuid.uuid4()


class _TxnCM:
    """conn.transaction() is a sync method returning an async context manager — AsyncMock's
    default mocks the METHOD as async, not its return value, so `async with conn.transaction():`
    breaks unless overridden this way. Same fix as test_aa309_tenant_onboarding.py/
    test_aa367_packets.py/test_aa448_v1_planning.py."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _make_pool(conn):
    conn.transaction = MagicMock(return_value=_TxnCM())
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _atom_row():
    return {"atom_id": "atom_abc123", "tour_id": TRIP_ID, "text": "Cross the bamboo bridge at dawn"}


def _request_row(**over):
    base = {
        "request_id": REQUEST_ID, "tenant_id": TENANT_ID, "atom_id": "atom_abc123",
        "trip_id": TRIP_ID, "channel": "facebook", "goal": None, "status": "pending_goal",
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    base.update(over)
    return base


def _option_row(idx, recommended=False, chosen=False):
    return {
        "idx": idx, "name": f"Angle {idx}", "why_it_works": "why", "formula_fit": "AIDA",
        "best_final_style": "style", "recommended": recommended, "chosen": chosen,
    }


@pytest.mark.asyncio
class TestCreateRequest:
    async def test_creates_request_for_owned_atom(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [_atom_row(), _request_row()]
        pool = _make_pool(conn)

        result = await service.create_request(TENANT_ID, "atom_abc123", "facebook", pool)

        assert result["status"] == "pending_goal"
        insert_query, *params = conn.fetchrow.call_args_list[1][0]
        assert "INSERT INTO acp_shared.angle_gate_request" in insert_query
        assert params[0] == TENANT_ID

    async def test_atom_not_owned_raises_not_found(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None  # owner_scope check finds nothing
        pool = _make_pool(conn)
        with pytest.raises(service.AtomNotFoundError):
            await service.create_request(TENANT_ID, "atom_someone_elses", "facebook", pool)


@pytest.mark.asyncio
class TestSetGoalAndGenerate:
    async def test_happy_path_writes_goal_and_three_options(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _request_row(status="pending_goal"),  # _fetch_request_row (status check)
            _atom_row(),                          # _fetch_atom_for_tenant
            {"customer_segment": "Senior execs", "customer_mindset": "seek depth"},  # brand fetchrow
        ]
        conn.fetch.return_value = []  # fetch_tenant_trips -> no trips (trip_name stays None, fine)
        pool = _make_pool(conn)

        angles = [
            {"name": "A", "why_it_works": "wa", "formula_fit": "fa", "best_final_style": "sa"},
            {"name": "B", "why_it_works": "wb", "formula_fit": "fb", "best_final_style": "sb"},
            {"name": "C", "why_it_works": "wc", "formula_fit": "fc", "best_final_style": "sc"},
        ]
        with patch.object(service, "generate_angles", new=AsyncMock(return_value=(angles, 1, "B is best", 0.02))), \
             patch.object(service, "fetch_request", new=AsyncMock(return_value={"status": "pending_choice"})):
            result = await service.set_goal_and_generate(TENANT_ID, REQUEST_ID, "promotion", pool)

        assert result["status"] == "pending_choice"
        insert_calls = [c for c in conn.execute.call_args_list if "angle_gate_option" in c[0][0]]
        assert len(insert_calls) == 3
        # recommended=True only on idx 1
        recommended_flags = [c[0][-1] for c in insert_calls]
        assert recommended_flags == [False, True, False]

    async def test_wrong_status_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_choice")  # already past pending_goal
        pool = _make_pool(conn)
        with pytest.raises(service.WrongStatusError):
            await service.set_goal_and_generate(TENANT_ID, REQUEST_ID, "promotion", pool)

    async def test_unknown_goal_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_goal")
        pool = _make_pool(conn)
        with pytest.raises(service.InvalidGoalError):
            await service.set_goal_and_generate(TENANT_ID, REQUEST_ID, "not_a_real_goal", pool)

    async def test_cross_tenant_request_not_found(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None  # WHERE tenant_id=$2 excludes another tenant's request
        pool = _make_pool(conn)
        with pytest.raises(service.RequestNotFoundError):
            await service.set_goal_and_generate(OTHER_TENANT_ID, REQUEST_ID, "promotion", pool)


@pytest.mark.asyncio
class TestChooseAngle:
    async def test_happy_path_sets_chosen_and_approved(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_choice", goal="promotion")
        conn.execute.side_effect = ["UPDATE 1", "UPDATE 1"]
        pool = _make_pool(conn)

        with patch.object(service, "fetch_request", new=AsyncMock(return_value={"status": "approved"})):
            result = await service.choose_angle(TENANT_ID, REQUEST_ID, 1, pool)

        assert result["status"] == "approved"
        status_update = [c for c in conn.execute.call_args_list if "SET status = 'approved'" in c[0][0]]
        assert len(status_update) == 1

    async def test_wrong_status_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_goal")  # no angles generated yet
        pool = _make_pool(conn)
        with pytest.raises(service.WrongStatusError):
            await service.choose_angle(TENANT_ID, REQUEST_ID, 0, pool)

    async def test_invalid_idx_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_choice")
        pool = _make_pool(conn)
        with pytest.raises(service.AngleGateError):
            await service.choose_angle(TENANT_ID, REQUEST_ID, 7, pool)


@pytest.mark.asyncio
class TestFetchRequest:
    async def test_returns_request_with_ordered_angles(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_choice", goal="promotion")
        conn.fetch.return_value = [_option_row(0), _option_row(1, recommended=True), _option_row(2)]
        pool = _make_pool(conn)

        result = await service.fetch_request(TENANT_ID, REQUEST_ID, pool)

        assert result["status"] == "pending_choice"
        assert len(result["angles"]) == 3
        assert result["angles"][1]["recommended"] is True

    async def test_not_found_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = _make_pool(conn)
        with pytest.raises(service.RequestNotFoundError):
            await service.fetch_request(TENANT_ID, REQUEST_ID, pool)
