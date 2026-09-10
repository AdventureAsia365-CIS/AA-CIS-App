"""
AA-544 Stage 1 — concurrent-tenant GUC/RLS leak test, against REAL RDS.

Unlike test_007_rls_isolation.py / test_tenant_rls.py (both connect to a local Postgres,
`cis_integration_test` — never RDS, one of the gaps AA-544's own investigation found: even the
"correct" role was never proven against the real database), this test connects to the real
aa_app_user role on the real RDS dev instance via the same DSN
api/core/aa544_tenant_pool.py::create_tenant_pool() fetches at runtime (Secrets Manager
`aa-cis/dev/rds-app-user`).

Skipped by default — CI (GitHub Actions) has no network path into the RDS VPC, so running this
unconditionally would just hang/fail for reasons unrelated to the code. Run manually against
real RDS dev (from inside the ECS task, which does have network access — see the S3-mediated
ECS exec pattern in ~/.claude/CLAUDE.md) with:

    AA544_RUN_REAL_RDS_TESTS=1 pytest tests/integration/test_aa544_stage1_tenant_pool_leak.py -v

Exercises exactly the mechanism api/core/aa544_tenant_pool.py::acquire_scoped_conn() uses
(SET LOCAL app.tenant_id inside a transaction) against the exact query GET /v1/publish-log/pending
runs, with a small pool (max_size=2) under real concurrency (many more coroutines than physical
connections) to force real connection reuse across different tenants — the concrete risk AA-544's
own investigation flagged as the one that needed a dedicated test before any cutover.
"""
import asyncio
import os
import random

import asyncpg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AA544_RUN_REAL_RDS_TESTS") != "1",
    reason="Real-RDS-only test — set AA544_RUN_REAL_RDS_TESTS=1 and run from an environment "
           "with network access to RDS dev (e.g. inside the ECS task). See module docstring.",
)

# Real tenants on RDS dev, live as of AA-544 Stage 1 (10/09/2026) — wanderlux-travel is the only
# tenant with approved content_piece rows joinable through angle_gate_request at this time.
WANDERLUX = "a1b2c3d4-0001-4000-8000-000000000001"
EXPLOREASIA = "a1b2c3d4-0002-4000-8000-000000000002"
FAKE_TENANTS = [f"deadbeef-{i:04d}-4000-8000-{i:012d}" for i in range(8)]

LIST_PENDING_SQL = """
    SELECT cp.piece_id::text
    FROM acp_shared.content_piece cp
    JOIN acp_shared.angle_gate_request agr ON agr.request_id = cp.angle_gate_request_id
    LEFT JOIN acp_shared.angle_gate_option ago
        ON ago.option_id = cp.angle_gate_option_id
        OR (cp.angle_gate_option_id IS NULL AND ago.request_id = agr.request_id AND ago.chosen = true)
    LEFT JOIN acp_shared.publish_log pl
        ON pl.piece_id = cp.piece_id AND pl.status = 'published'
    WHERE cp.tenant_id = $1::uuid
      AND cp.status = 'approved'
      AND COALESCE(cp.channel, agr.channel) = ANY($2::text[])
      AND pl.publish_id IS NULL
"""


async def _get_dsn():
    import boto3
    client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-1"))
    return client.get_secret_value(SecretId="aa-cis/dev/rds-app-user")["SecretString"]


async def _scoped_query(pool, tenant_id, errors, counts):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
            await asyncio.sleep(random.uniform(0, 0.01))
            readback = await conn.fetchval("SELECT current_setting('app.tenant_id', true)")
            rows = await conn.fetch(LIST_PENDING_SQL, tenant_id, ["blog", "facebook"])

    if readback != tenant_id:
        errors.append(f"GUC readback mismatch for {tenant_id}: got {readback}")
        return
    counts.setdefault(tenant_id, set()).add(len(rows))
    if tenant_id != WANDERLUX and len(rows) > 0:
        errors.append(f"LEAK: {tenant_id} saw {len(rows)} rows it does not own")


@pytest.mark.asyncio
async def test_concurrent_tenant_no_leak_on_reused_connection():
    dsn = await _get_dsn()
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=2)
    try:
        candidates = [WANDERLUX, EXPLOREASIA] + FAKE_TENANTS
        errors = []
        counts = {}
        tasks = [
            _scoped_query(pool, random.choice(candidates), errors, counts)
            for _ in range(200)
        ]
        await asyncio.gather(*tasks)

        assert errors == [], f"Leak/GUC errors found: {errors}"
        # Every non-wanderlux tenant must have seen ONLY 0 rows, every time.
        for tenant_id, seen in counts.items():
            if tenant_id != WANDERLUX:
                assert seen <= {0}, f"{tenant_id} saw non-zero counts: {seen}"
        # wanderlux must be consistent across every call (no variance = no leak masking it).
        if WANDERLUX in counts:
            assert len(counts[WANDERLUX]) == 1, (
                f"wanderlux saw inconsistent counts across calls: {counts[WANDERLUX]}"
            )
    finally:
        await pool.close()
