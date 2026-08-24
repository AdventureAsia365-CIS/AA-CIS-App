"""
/v1/publish-log — tenant self-unpublish, AA-455 bước 1.

STEP0 (docs/claude_audit/AA-455-01-step0-a4-force-unpublish.md §6) flagged tenant self-unpublish
as undecided by ADR-2026-038 §0.2. Nghiep's decision (Linear AA-455 update, 24/08/2026): Option 2
— tenant self-unpublish IS built, consistent with the same self-service philosophy already
applied to T3/T6/T7/T8 (tenant operates, AA only monitors post-hoc). Separate module rather than
folded into v1_content_writing.py — `publish_log` is its own resource (T11's, not T9/T10's), same
reasoning migration 115 itself used for NOT denormalizing content_piece's parent fields onto
angle_gate_option: a distinct resource gets its own place, callers join back when they need
context. Reuses `get_tenant` from v1_tours.py unchanged (same shared dependency
v1_content_writing.py/v1_angle_gate.py already use — no new auth mechanism).

Only one endpoint here — a tenant listing their own publish_log isn't in this issue's scope
(deferred to T11 bước 2's own tenant-facing UI, which will need it for real reasons a fresh
GET wired to nothing wouldn't serve). DELETE ownership check follows v1_competitors.py:187's
exact precedent: `WHERE id = $1 AND tenant_id = $2`, 404 (not 403) when the row isn't the
caller's — doesn't distinguish "not found" from "not yours" in the response, same anti-IDOR
shape AA-445-02/AA-431 already established in this codebase.
"""
from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routers.v1_tours import get_tenant

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/publish-log", tags=["publish-log"])


@router.delete("/{publish_id}")
async def unpublish(publish_id: UUID, request: Request, tenant=Depends(get_tenant)):
    """Tenant self-unpublish. Only flips a `status='published'` row the caller's own tenant_id
    owns to 'unpublished' — a row belonging to another tenant, or already
    unpublished/failed, 404s identically (no cross-tenant existence leak, AA-445-02 lesson).
    `unpublished_by` records "tenant:<tenant_id>", distinguishing this from A4's
    "admin:<id>" force-unpublish on the same table."""
    pool = request.app.state.pool
    tenant_id = tenant["sub"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE acp_shared.publish_log
            SET status = 'unpublished', unpublished_at = now(), unpublished_by = $3
            WHERE publish_id = $1 AND tenant_id = $2::uuid AND status = 'published'
            RETURNING publish_id::text, channel, status, unpublished_at
        """, publish_id, tenant_id, f"tenant:{tenant_id}")

    if not row:
        raise HTTPException(status_code=404, detail="publish_log row not found or already unpublished")

    logger.info("tenant_self_unpublish", publish_id=str(publish_id), tenant_id=tenant_id)
    return {
        "publish_id": row["publish_id"],
        "channel": row["channel"],
        "status": row["status"],
        "unpublished_at": row["unpublished_at"].isoformat() if row["unpublished_at"] else None,
        "unpublished_by": f"tenant:{tenant_id}",
    }


__all__ = ["router"]
