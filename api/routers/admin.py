# api/routers/admin.py
# S16 — Admin endpoint: generate API key for tenant
#
# Flow:
#   POST /admin/tenants/{tenant_id}/generate-key
#   Header: X-Admin-Secret: <ADMIN_SECRET>
#   → generate secrets.token_urlsafe(32) with prefix "cis_"
#   → SHA256 hash → store in shared.tenants.api_key_hash
#   → return plaintext key ONCE — never stored
#
# ADMIN_SECRET: from Secrets Manager aa-cis/dev/admin-secret

import hashlib
import os
import secrets
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")


# ── Auth guard ────────────────────────────────────────────────────────────────

def verify_admin_secret(x_admin_secret: str = Header(None)):
    if not ADMIN_SECRET:
        raise HTTPException(status_code=503, detail="Admin secret not configured")
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin secret")


# ── Models ────────────────────────────────────────────────────────────────────

class GenerateKeyResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    api_key: str   # plaintext — shown once only
    message: str


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/tenants/{tenant_id}/generate-key",
    response_model=GenerateKeyResponse,
    summary="Generate a new API key for a tenant (admin only)",
)
async def generate_api_key(
    tenant_id: UUID,
    request: Request,
    x_admin_secret: str = Header(None),
):
    verify_admin_secret(x_admin_secret)
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tenant_id, name FROM shared.tenants WHERE tenant_id = $1",
            tenant_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Tenant not found")

        plaintext = f"cis_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()

        await conn.execute(
            """
            UPDATE shared.tenants
            SET api_key_hash = $1, updated_at = NOW()
            WHERE tenant_id = $2
            """,
            key_hash,
            tenant_id,
        )

    return GenerateKeyResponse(
        tenant_id=str(row["tenant_id"]),
        tenant_name=row["name"],
        api_key=plaintext,
        message="Store this key securely — it will not be shown again. Calling this endpoint again rotates the key.",
    )
