"""
AA-544 Stage 1 — aa_app_user tenant pool + per-request RLS GUC helper.

Canary scope: wired into exactly ONE route today (GET /v1/publish-log/pending,
v1_publish.py::list_pending) behind the Redis flag below. Do NOT import this into any other
router without going through AA-544's own stage-by-stage report-then-confirm ritual first --
expanding which routes use this pool is Stage 2+'s job, not something to copy-paste in ad hoc.

Design (matches AA-544's approved 2-pool split): Admin (/admin/*) keeps app.state.pool
(aa_cis_admin, BYPASSRLS) unchanged, always. This module adds a SECOND pool, aa_app_user
(non-BYPASSRLS, real RLS applies), used ONLY by routes that explicitly opt in via
acquire_scoped_conn() below, and only when the flag is on.

Rollback: `redis-cli DEL aa544:stage1:publish_pending_pool` (or SET ... false) reverts the
canary route to the admin pool immediately -- no deploy needed. Nothing else changes.

GUC safety: app.tenant_id is set via set_config(..., is_local=true) INSIDE an explicit
transaction (SET LOCAL semantics) -- scoped to that one transaction so it cannot leak onto the
next request that reuses this same physical connection from the pool. Every query that needs
tenant scoping MUST run inside the same `async with conn.transaction():` block
acquire_scoped_conn() opens -- see its docstring.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg
import structlog
from fastapi import Request

logger = structlog.get_logger()

_FLAG_KEY = "aa544:stage1:publish_pending_pool"
_SECRET_ID = "aa-cis/dev/rds-app-user"


async def create_tenant_pool() -> Optional[asyncpg.Pool]:
    """Best-effort, called once at app startup (api/main.py's lifespan()). A missing/
    unreachable secret must never crash app boot -- same convention as the AA-223 startup
    sweep already in lifespan(). Returns None on any failure; every caller below treats None
    as "stay on the admin pool" (fail closed to pre-Stage-1 behavior, never fail open into an
    unproven code path).

    Small pool (max_size=5) on purpose -- this is a 1-route canary, not yet real traffic
    volume; revisit sizing when Stage 2+ adds more routes."""
    try:
        import boto3
        client = boto3.client(
            "secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-1")
        )
        dsn = client.get_secret_value(SecretId=_SECRET_ID)["SecretString"]
        return await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    except Exception as e:
        logger.error("aa544_tenant_pool_create_failed", error=repr(e))
        return None


async def stage1_flag_enabled(request: Request) -> bool:
    """Fail CLOSED -- any Redis error or unset key means "off" (the pre-Stage-1 behavior:
    admin pool, no RLS). Never fail open into a code path that hasn't been proven yet."""
    try:
        val = await request.app.state.redis.get(_FLAG_KEY)
    except Exception as e:
        logger.warning("aa544_stage1_flag_read_failed", error=repr(e))
        return False
    return val == "true"


@asynccontextmanager
async def acquire_scoped_conn(request: Request, tenant_id: str):
    """Yields (conn, used_tenant_pool: bool).

    When the Stage 1 flag is on AND the tenant pool booted successfully: acquires from
    request.app.state.tenant_pool (aa_app_user, non-BYPASSRLS) and opens a transaction with
    app.tenant_id set LOCAL to it. Everything the caller does with `conn` inside this
    `async with` block MUST happen inside that same transaction for the GUC to apply -- do not
    acquire a second connection or start a nested transaction on this one mid-block.

    Otherwise (flag off, or tenant pool never came up): acquires from
    request.app.state.pool (aa_cis_admin, current behavior, completely unchanged) with no
    transaction wrapper -- this is the fail-closed default path, not an error case."""
    tenant_pool = getattr(request.app.state, "tenant_pool", None)
    use_tenant_pool = tenant_pool is not None and await stage1_flag_enabled(request)

    if use_tenant_pool:
        async with tenant_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
                yield conn, True
    else:
        async with request.app.state.pool.acquire() as conn:
            yield conn, False
