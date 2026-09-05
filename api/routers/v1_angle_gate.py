"""
api/routers/v1_angle_gate.py — AA-449: T8 Angle Gate (tenant self-service).

Per ADR-2026-038 §0.2/§10.3 (tenant self-service — AA does not gate tenant content at any T0-T11
step; the T8 "gate" is the TENANT choosing, never AA): this is a `/v1/*` tenant-JWT-only router,
same convention as `v1_planning.py`/`v1_tours.py`/`v1_marketplace.py` (reuses `get_tenant`
unchanged, no staff/admin path).

Written fresh per ADR §0.5 — no import from services.acp_s4_social anywhere in this router or
the services.acp_angle_gate package it calls into.

AA-522 (04/09/2026) — Luồng B removed: `POST /requests` (creating a request from a bare atom_id,
no Subject) and `POST /requests/{id}/channel` (the old post-angle-choice Channel step, AA-469
Việc 4's workflow step 8) are both DELETED. Every request is now created by
services.acp_shared.slate.pick_subject() (api/routers/v1_planning.py), which sets atom_id/
trip_id/channel/subject_id all at INSERT time — channel is never chosen through this router
anymore. See services/acp_angle_gate/service.py's own module docstring for the full rationale.

Endpoint shape:
  GET  /v1/angle-gate/goals                   — static 8-goal list
  POST /v1/angle-gate/requests/{id}/goal       — choose goal, generate 3 angles
  GET  /v1/angle-gate/requests/{id}            — read request + angles             [any time]
  POST /v1/angle-gate/requests/{id}/choose     — tenant picks one, status=approved  [the real gate]
  POST /v1/angle-gate/requests/{id}/reopen     — AA-497 (AA-494 Decision 3): approved ->
                                                   reusable, unlocking .../choose again to pick
                                                   a different one of the 3 already-generated
                                                   angles (no new LLM call)
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.routers.v1_tours import get_tenant
from services.acp_angle_gate import service
from services.acp_angle_gate.generate import AngleGenerationError
from services.acp_angle_gate.goals import GOALS

router = APIRouter(prefix="/v1/angle-gate", tags=["tenant-angle-gate"])


class SetGoalBody(BaseModel):
    goal: str


class ChooseBody(BaseModel):
    idx: int


@router.get("/goals", summary="List the 8 content goals (Bang 1) a tenant can choose from")
async def list_goals():
    return {"goals": GOALS}


@router.post(
    "/requests/{request_id}/goal",
    summary="Choose a goal and generate 3 angles — workflow steps 2-6",
)
async def set_goal(request_id: UUID, body: SetGoalBody, request: Request, tenant=Depends(get_tenant)):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    try:
        return await service.set_goal_and_generate(tenant_id, request_id, body.goal, pool)
    except service.RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except service.InvalidGoalError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except service.WrongStatusError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except AngleGenerationError as exc:
        # LLM output couldn't be parsed into 3 valid angles even after json-repair salvage —
        # the request stays at status='pending_goal' (nothing was written), so the tenant can
        # retry the same goal (or a different one) without needing a fresh request_id.
        raise HTTPException(status_code=502, detail=f"Angle generation failed: {exc}")


@router.get("/requests/{request_id}", summary="Read a request + its angles (if generated)")
async def get_request(request_id: UUID, request: Request, tenant=Depends(get_tenant)):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    try:
        return await service.fetch_request(tenant_id, request_id, pool)
    except service.RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/requests/{request_id}/choose",
    summary="Tenant chooses one of the 3 angles — workflow step 7, the real gate",
)
async def choose(request_id: UUID, body: ChooseBody, request: Request, tenant=Depends(get_tenant)):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    try:
        return await service.choose_angle(tenant_id, request_id, body.idx, pool)
    except service.RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except service.WrongStatusError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except service.AngleGateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/requests/{request_id}/reopen",
    summary="Reopen an approved request to re-select a different already-generated angle "
            "(AA-497 / AA-494 Decision 3) — no new LLM call",
)
async def reopen(request_id: UUID, request: Request, tenant=Depends(get_tenant)):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    try:
        return await service.reopen_request(tenant_id, request_id, pool)
    except service.RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except service.WrongStatusError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
