"""
/v1/publish-log — T11 Publish. Tenant self-unpublish (AA-455 bước 1) + the real publish layer
(AA-458, T11 PR2): list content approved-and-not-yet-published, and publish one piece to the
tenant's connected WordPress site.

STEP0 (docs/claude_audit/AA-455-01-step0-a4-force-unpublish.md §6) flagged tenant self-unpublish
as undecided by ADR-2026-038 §0.2. Nghiep's decision (Linear AA-455 update, 24/08/2026): Option 2
— tenant self-unpublish IS built, consistent with the same self-service philosophy already
applied to T3/T6/T7/T8 (tenant operates, AA only monitors post-hoc). Separate module rather than
folded into v1_content_writing.py — `publish_log` is its own resource (T11's, not T9/T10's), same
reasoning migration 115 itself used for NOT denormalizing content_piece's parent fields onto
angle_gate_option: a distinct resource gets its own place, callers join back when they need
context. Reuses `get_tenant` from v1_tours.py unchanged (same shared dependency
v1_content_writing.py/v1_angle_gate.py already use — no new auth mechanism).

Ownership checks throughout follow v1_competitors.py:187's exact precedent: `WHERE id = $1 AND
tenant_id = $2`, 404 (not 403) when the row isn't the caller's — doesn't distinguish "not found"
from "not yours" in the response, same anti-IDOR shape AA-445-02/AA-431 already established.

AA-458's publish() applies the AA-460 lesson (see api/routers/v1_integrations.py::test_wordpress
for the original fix this mirrors): WordPressAdapter.create_post() (services/acp_s4_blog/cms/
wordpress.py) now does its own content-type/JSON/shape validation before returning a result —
this router never trusts a bare 200/201 status either, it just relies on create_post() to have
already raised if the response wasn't real WordPress, and records 'failed' + the real error
message rather than a fabricated 'published' row.
"""
from __future__ import annotations

import json
from uuid import UUID

import boto3
import structlog
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request

from api.routers.v1_tours import get_tenant
from services.acp_s4_blog.cms.base import BlogContent
from services.acp_s4_blog.cms.wordpress import WordPressAdapter

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/publish-log", tags=["publish-log"])

_SM_REGION = "us-west-1"
_BLOG_CHANNEL = "blog"  # T11 scope is blog-only (AA-456/AA-458) — 7 other channels deferred


def _get_secret(secret_key: str) -> dict:
    """Same shape as v1_integrations.py's own _get_secret() — arbitrary secret_key at call time,
    no caching. Not imported from there to avoid a cross-router import for one small function;
    matches this codebase's own precedent of small, duplicated-on-purpose secret-fetch helpers
    (v1_integrations.py itself duplicated services/acp_s4_blog/cms/publisher.py::_get_cms_creds()
    for the same reason)."""
    client = boto3.client("secretsmanager", region_name=_SM_REGION)
    return json.loads(client.get_secret_value(SecretId=secret_key)["SecretString"])


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


@router.get("/pending")
async def list_pending(request: Request, tenant=Depends(get_tenant)):
    """AA-458 — the list endpoint AA-456's own STEP0 §5 flagged as missing: a tenant's approved
    content_piece rows for the blog channel that have no successful publish yet. A piece with a
    prior FAILED attempt (or none at all, or a since-unpublished one) still shows up here — only
    a row with a currently-'published' publish_log entry is excluded, so a failed/unpublished
    piece stays retryable rather than disappearing."""
    pool = request.app.state.pool
    tenant_id = tenant["sub"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT cp.piece_id::text, cp.content_text, cp.created_at,
                   agr.channel, ago.name AS angle_name
            FROM acp_shared.content_piece cp
            JOIN acp_shared.angle_gate_request agr ON agr.request_id = cp.angle_gate_request_id
            LEFT JOIN acp_shared.angle_gate_option ago
                ON ago.request_id = agr.request_id AND ago.chosen = true
            LEFT JOIN acp_shared.publish_log pl
                ON pl.piece_id = cp.piece_id AND pl.status = 'published'
            WHERE cp.tenant_id = $1::uuid
              AND cp.status = 'approved'
              AND agr.channel = $2
              AND pl.publish_id IS NULL
            ORDER BY cp.created_at DESC
            """,
            tenant_id, _BLOG_CHANNEL,
        )

    return {
        "data": [
            {
                "piece_id": r["piece_id"],
                "title": r["angle_name"] or "Untitled",
                "content_preview": r["content_text"][:280],
                "channel": r["channel"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("/{piece_id}/publish")
async def publish(piece_id: UUID, request: Request, tenant=Depends(get_tenant)):
    """AA-458 — the real publish endpoint. No AA pre-gate (ADR-2026-038 §0.2, same principle
    AA-455's force-unpublish exists to police after the fact, not before). Ownership + approval
    verified in one query; 404 covers both "not yours" and "not approved yet" identically (no
    existence leak). A retryable prior 'failed' publish_log row for this piece is updated in
    place rather than accumulating duplicate failure rows; a 'published' or 'unpublished' row is
    left untouched and a fresh attempt gets its own new row (preserves that row's real
    unpublished_at/unpublished_by audit trail — AA-455's whole reason for those columns)."""
    pool = request.app.state.pool
    tenant_id = tenant["sub"]

    async with pool.acquire() as conn:
        piece = await conn.fetchrow(
            """
            SELECT cp.piece_id, cp.content_text, cp.status, agr.channel, ago.name AS angle_name
            FROM acp_shared.content_piece cp
            JOIN acp_shared.angle_gate_request agr ON agr.request_id = cp.angle_gate_request_id
            LEFT JOIN acp_shared.angle_gate_option ago
                ON ago.request_id = agr.request_id AND ago.chosen = true
            WHERE cp.piece_id = $1::uuid AND cp.tenant_id = $2::uuid
            """,
            piece_id, tenant_id,
        )

    if not piece or piece["status"] != "approved" or piece["channel"] != _BLOG_CHANNEL:
        raise HTTPException(status_code=404, detail="Content piece not found or not approved")

    async with pool.acquire() as conn:
        integ = await conn.fetchrow(
            "SELECT secret_key FROM shared.tenant_integrations "
            "WHERE tenant_id = $1::uuid AND integration_type = 'wordpress'",
            tenant_id,
        )

    if not integ or not integ["secret_key"]:
        raise HTTPException(status_code=422, detail="Connect WordPress to publish")

    try:
        creds = _get_secret(integ["secret_key"])
    except ClientError as exc:
        logger.error("publish_secret_read_failed", tenant_id=tenant_id,
                     secret_key=integ["secret_key"], error=str(exc))
        raise HTTPException(status_code=502, detail="Could not read saved credentials — try reconnecting")

    title = piece["angle_name"] or "Untitled"
    content = BlogContent(
        title=title, content_html=piece["content_text"], slug="",
        seo_title=title, seo_meta="", status="publish",
    )
    adapter = WordPressAdapter(
        wp_url=creds["wp_url"], username=creds["username"], app_password=creds["app_password"],
    )

    try:
        result = await adapter.create_post(content)
        success = True
        external_id = str(result.post_id)
        external_url = result.post_url
        error_msg = None
    except Exception as exc:  # noqa: BLE001 — create_post() already validated the response shape
        # (AA-460 lesson, applied in the adapter itself); anything reaching here is a real
        # failure (network error, non-2xx, or a non-WordPress response) with a clear message.
        success = False
        external_id = None
        external_url = None
        error_msg = str(exc)[:500]

    new_status = "published" if success else "failed"

    async with pool.acquire() as conn:
        existing_failed = await conn.fetchval(
            "SELECT publish_id FROM acp_shared.publish_log "
            "WHERE piece_id = $1::uuid AND tenant_id = $2::uuid AND status = 'failed'",
            piece_id, tenant_id,
        )
        if existing_failed:
            row = await conn.fetchrow(
                """
                UPDATE acp_shared.publish_log
                SET status = $3, external_id = $4, external_url = $5,
                    published_at = CASE WHEN $3 = 'published' THEN now() ELSE published_at END,
                    last_error = $6
                WHERE publish_id = $1 AND tenant_id = $2::uuid
                RETURNING publish_id::text, status, external_id, external_url, published_at, last_error
                """,
                existing_failed, tenant_id, new_status, external_id, external_url, error_msg,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO acp_shared.publish_log
                    (piece_id, tenant_id, channel, status, external_id, external_url,
                     published_at, last_error)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6,
                        CASE WHEN $4 = 'published' THEN now() ELSE NULL END, $7)
                RETURNING publish_id::text, status, external_id, external_url, published_at, last_error
                """,
                piece_id, tenant_id, _BLOG_CHANNEL, new_status, external_id, external_url, error_msg,
            )

    logger.info("wordpress_publish", tenant_id=tenant_id, piece_id=str(piece_id),
                success=success, external_id=external_id, error=error_msg)

    return {
        "publish_id": row["publish_id"],
        "success": success,
        "status": row["status"],
        "external_id": row["external_id"],
        "external_url": row["external_url"],
        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
        "last_error": row["last_error"],
    }


__all__ = ["router"]
