"""
api/routers/v1_content_writing.py — AA-450: T9 (write) + T10-inline (quality gates), tenant
self-service.

Same convention as v1_angle_gate.py: `/v1/*` tenant-JWT-only, reuses `get_tenant` unchanged, no
staff/admin path. Written fresh per ADR §0.5 — no import from services.acp_s4_social anywhere.

Endpoint shape:
  POST /v1/content-writing/requests/{angle_gate_request_id}/write — the single endpoint: write,
       check (T10, up to 2 total attempts), persist, return the final content_piece.
  GET  /v1/content-writing/pieces/{piece_id} — read a previously written piece back.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.routers.v1_tours import get_tenant
from services.acp_angle_gate.service import RequestNotFoundError
from services.acp_content_writing import service

router = APIRouter(prefix="/v1/content-writing", tags=["tenant-content-writing"])


class WriteBody(BaseModel):
    cta: str | None = None  # fallback CTA — used only when angle_gate_request.cta is NULL


@router.post(
    "/requests/{request_id}/write",
    summary="Write + quality-check content for an approved angle-gate request (T9 + T10-inline)",
)
async def write(request_id: UUID, body: WriteBody, request: Request, tenant=Depends(get_tenant)):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    try:
        return await service.write_and_check(tenant_id, request_id, pool, cta_override=body.cta)
    except RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except service.RequestNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except service.MissingCTAError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except service.ContentWritingError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/pieces/{piece_id}", summary="Read a previously written content piece")
async def get_piece(piece_id: UUID, request: Request, tenant=Depends(get_tenant)):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    try:
        return await service.fetch_piece(tenant_id, piece_id, pool)
    except service.ContentWritingError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
