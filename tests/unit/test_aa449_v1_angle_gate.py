"""AA-449 — api/routers/v1_angle_gate.py. Same convention test_aa448_v1_planning.py uses:
`tenant=` dependency bypassed (endpoint functions called directly, not through FastAPI's
Depends() machinery), service.py itself patched (already unit-tested separately in
test_aa449_angle_gate_service.py) — this file checks HTTP status-code mapping."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.routers import v1_angle_gate
from services.acp_angle_gate import service
from services.acp_angle_gate.generate import AngleGenerationError

TENANT_ID = str(uuid.uuid4())
REQUEST_ID = uuid.uuid4()


def _make_request():
    request = MagicMock()
    request.app.state.pool = MagicMock()
    return request


class TestListGoals:
    @pytest.mark.asyncio
    async def test_returns_eight_goals(self):
        result = await v1_angle_gate.list_goals()
        assert len(result["goals"]) == 8
        assert result["goals"][0]["key"] == "promotion"


class TestCreateRequest:
    @pytest.mark.asyncio
    async def test_success(self):
        body = v1_angle_gate.CreateRequestBody(atom_id="atom_1", channel="facebook")
        with patch.object(
            v1_angle_gate.service, "create_request",
            new=AsyncMock(return_value={
                "request_id": REQUEST_ID, "atom_id": "atom_1", "trip_id": None,
                "channel": "facebook", "cta": None, "status": "pending_goal",
            }),
        ):
            result = await v1_angle_gate.create_request(body, _make_request(), tenant={"sub": TENANT_ID})
        assert result["status"] == "pending_goal"

    @pytest.mark.asyncio
    async def test_atom_not_found_404(self):
        body = v1_angle_gate.CreateRequestBody(atom_id="atom_missing", channel="facebook")
        with patch.object(
            v1_angle_gate.service, "create_request",
            new=AsyncMock(side_effect=service.AtomNotFoundError("nope")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_angle_gate.create_request(body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 404


class TestSetGoal:
    @pytest.mark.asyncio
    async def test_wrong_status_409(self):
        body = v1_angle_gate.SetGoalBody(goal="promotion")
        with patch.object(
            v1_angle_gate.service, "set_goal_and_generate",
            new=AsyncMock(side_effect=service.WrongStatusError("already set")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_angle_gate.set_goal(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_invalid_goal_422(self):
        body = v1_angle_gate.SetGoalBody(goal="not_a_goal")
        with patch.object(
            v1_angle_gate.service, "set_goal_and_generate",
            new=AsyncMock(side_effect=service.InvalidGoalError("bad goal")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_angle_gate.set_goal(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_llm_failure_502(self):
        body = v1_angle_gate.SetGoalBody(goal="promotion")
        with patch.object(
            v1_angle_gate.service, "set_goal_and_generate",
            new=AsyncMock(side_effect=AngleGenerationError("bad json")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_angle_gate.set_goal(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 502

    @pytest.mark.asyncio
    async def test_success(self):
        body = v1_angle_gate.SetGoalBody(goal="promotion")
        with patch.object(
            v1_angle_gate.service, "set_goal_and_generate",
            new=AsyncMock(return_value={"status": "pending_choice", "angles": [1, 2, 3]}),
        ):
            result = await v1_angle_gate.set_goal(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert result["status"] == "pending_choice"


class TestGetRequest:
    @pytest.mark.asyncio
    async def test_not_found_404(self):
        with patch.object(
            v1_angle_gate.service, "fetch_request",
            new=AsyncMock(side_effect=service.RequestNotFoundError("nope")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_angle_gate.get_request(REQUEST_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 404


class TestChoose:
    @pytest.mark.asyncio
    async def test_success(self):
        body = v1_angle_gate.ChooseBody(idx=1)
        with patch.object(
            v1_angle_gate.service, "choose_angle",
            new=AsyncMock(return_value={"status": "approved"}),
        ):
            result = await v1_angle_gate.choose(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_wrong_status_409(self):
        body = v1_angle_gate.ChooseBody(idx=1)
        with patch.object(
            v1_angle_gate.service, "choose_angle",
            new=AsyncMock(side_effect=service.WrongStatusError("not ready")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_angle_gate.choose(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_bad_idx_422(self):
        body = v1_angle_gate.ChooseBody(idx=9)
        with patch.object(
            v1_angle_gate.service, "choose_angle",
            new=AsyncMock(side_effect=service.AngleGateError("bad idx")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_angle_gate.choose(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 422
