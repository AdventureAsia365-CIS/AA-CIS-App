"""
api/routers/v1_content_writing.py — AA-450: T9 (write) + T10-inline (quality gates), tenant
self-service.

Same convention as v1_angle_gate.py: `/v1/*` tenant-JWT-only, reuses `get_tenant` unchanged, no
staff/admin path. Written fresh per ADR §0.5 — no import from services.acp_s4_social anywhere.

AA-466: POST .../write moved to 202 Accepted + poll (real API Gateway 504s on long LLM+T10 runs,
AA-453/465). `service.start_write()` does the fast pre-flight (unchanged 404/409/422 contract)
and inserts a `content_piece` placeholder (status='processing'); the slow write/check loop runs
in `service.run_write_background()`, launched via `asyncio.create_task()` with a strong ref
(`_background_tasks` set + `add_done_callback`) — same GC-safety pattern
`api/routers/v1_tours.py::trigger_rewrite()` already uses (AA-425), not the bare
`asyncio.create_task()` `v1_s4_blog.py` uses.

Endpoint shape:
  POST /v1/content-writing/requests/{angle_gate_request_id}/write — 202 Accepted immediately,
       body = the content_piece placeholder (status='processing'). Poll GET .../pieces/{piece_id}
       for the final result (status becomes approved/held/failed).
  GET  /v1/content-writing/pieces/{piece_id} — read a piece back, at any status. UNCHANGED by
       AA-466 — already returns every field a poller needs (status/content_text/held_reason).
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.routers.v1_tours import get_tenant
from services.acp_angle_gate.service import RequestNotFoundError
from services.acp_content_writing import service

router = APIRouter(prefix="/v1/content-writing", tags=["tenant-content-writing"])

# AA-466: strong refs to the fire-and-forget write+check background task — asyncio only keeps a
# weak ref to a bare create_task() result, so an unreferenced task can be GC'd mid-flight (same
# class of bug AA-223 found/fixed for admin_pipeline.py, AA-425 found/fixed for this router's own
# sibling api/routers/v1_tours.py::trigger_rewrite() — this endpoint now runs the same length of
# background work T9's write/rewrite + T10 gate loop does, up to ~89s, so it needs the same guard).
_background_tasks: set = set()


class WriteBody(BaseModel):
    cta: str | None = None  # fallback CTA — used only when angle_gate_request.cta is NULL


@router.post(
    "/requests/{request_id}/write",
    status_code=202,
    summary="Start writing + quality-checking content for an approved angle-gate request "
            "(T9 + T10-inline) — 202 Accepted, poll GET .../pieces/{piece_id} for the result",
)
async def write(request_id: UUID, body: WriteBody, request: Request, tenant=Depends(get_tenant)):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    try:
        started = await service.start_write(tenant_id, request_id, pool, cta_override=body.cta)
    except RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except service.RequestNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except service.MissingCTAError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except service.ContentWritingError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    piece, context = started["piece"], started["context"]
    task = asyncio.create_task(
        service.run_write_background(request_id, UUID(piece["piece_id"]), context, pool)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return piece


@router.get("/pieces/{piece_id}", summary="Read a previously written content piece")
async def get_piece(piece_id: UUID, request: Request, tenant=Depends(get_tenant)):
    tenant_id = UUID(tenant["sub"])
    pool = request.app.state.pool
    try:
        return await service.fetch_piece(tenant_id, piece_id, pool)
    except service.ContentWritingError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
