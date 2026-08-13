"""tests/verify_scripts/aa389_gate_a_bypass_verify.py — AA-389 live verify.

WHY THIS FILE EXISTS: AA-389 built the N1 onboarding UI (seed-atoms/angle/Gate A) on top of
AA-309's already-shipped endpoints (unchanged here) plus one real backend fix found during
STEP 0 — PATCH /admin/tenants/{id} could activate a tenant that never went through Gate A at
all (no seed-atoms, no assigned_angle, no approval), a one-click bypass of the "REQUIRED/
NEVER-auto" guarantee gate-a/approve exists to enforce. Confirmed with Nghiep before building
(AskUserQuestion) that this should be closed as part of AA-389.

Runs the real, unmodified AA-309 functions (create_tenant/seed_tenant_atoms/
assign_tenant_angle/get_gate_a_status/approve_gate_a) plus the NEW update_tenant() guard,
directly against real dev Postgres — same "call the real route function with a real pool"
convention as test_aa309_tenant_onboarding.py's mocked-pool unit tests, except the pool here
is real (proves the SQL itself, not just the mocked call shape).

Run ONLY inside the ECS task (S3-mediated exec), AFTER the modified api/routers/admin.py has
been pushed into the container (this branch isn't deployed) — same technique AA-309/AA-330
used ("code pushed into the already-running ECS container ... real functions run against a
real pool, not a re-simulation"). Does NOT touch the live uvicorn process (no --reload in the
Dockerfile) — only this script's own fresh `python3` import picks up the overwritten file; the
already-running API server keeps serving the old code, unaffected.

Self-daemonizes (double-fork) and logs to /tmp/aa389_verify.log — a foreground exec through
the SSM session drops with "Cannot perform start session: EOF" mid-run even for short async
work (same pitfall memory ecs-exec-long-sync-daemonize documents); poll that log file in a
separate quick exec for the DONE_MARKER line instead of waiting on this invocation directly.

    python3 /tmp/aa389_verify.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/app")


def _daemonize(log_path: str) -> None:
    if os.fork() > 0:
        print(f"SPAWNED log={log_path}")
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    sys.stdout.flush()
    sys.stderr.flush()
    log_fd = open(log_path, "a", buffering=1)
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())


if __name__ == "__main__":
    _daemonize("/tmp/aa389_verify.log")

import asyncio  # noqa: E402
import secrets  # noqa: E402
from urllib.parse import urlparse  # noqa: E402
from uuid import UUID  # noqa: E402

import asyncpg  # noqa: E402
import boto3  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from api.routers import admin  # noqa: E402

DONE_MARKER = "AA389_VERIFY_DONE"

# Real finalized portfolio from AA-309/AA-330's own live verify (still finalized unless deleted).
PORTFOLIO_ID = "9fa1800e-1038-4b31-b9a8-4e399f9044ee"
TEST_SLUG = f"aa389-test-{secrets.token_hex(4)}"


def _step(title: str) -> None:
    print(f"\n{'=' * 12} {title} {'=' * 12}")


def _get_dsn() -> str:
    sm = boto3.client("secretsmanager", region_name="us-west-1")
    return sm.get_secret_value(SecretId="aa-cis/dev/rds")["SecretString"]


class _SingleConnPool:
    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeApp:
    def __init__(self, pool):
        self.state = type("S", (), {"pool": pool})()


class _FakeRequest:
    def __init__(self, pool):
        self.app = _FakeApp(pool)


async def main() -> None:
    dsn = _get_dsn()
    u = urlparse(dsn)
    db = await asyncpg.connect(
        host=u.hostname, port=u.port or 5432, user=u.username, password=u.password,
        database=u.path.lstrip("/"), ssl="require",
    )
    pool = _SingleConnPool(db)
    request = _FakeRequest(pool)
    secret = admin.ADMIN_SECRET
    tenant_id: UUID | None = None

    try:
        portfolio = await db.fetchrow(
            "SELECT status FROM acp_shared.marketplace_portfolios WHERE portfolio_id = $1", PORTFOLIO_ID,
        )
        print(f"Portfolio {PORTFOLIO_ID} status = {portfolio['status'] if portfolio else 'NOT FOUND'}")
        if not portfolio or portfolio["status"] != "finalized":
            raise RuntimeError("reference portfolio missing/not finalized -- pick another real finalized one")

        _step("1. create_tenant -- expect is_active=false")
        body = admin.CreateTenantRequest(
            name=f"AA389 Test Tenant {TEST_SLUG}", slug=TEST_SLUG, plan_tier="growth", posts_per_week=3,
        )
        created = await admin.create_tenant(body, request, x_admin_secret=secret)
        tenant_id = UUID(created.tenant_id)
        print(f"tenant_id={tenant_id} is_active={created.is_active}")
        row = await db.fetchrow("SELECT is_active FROM shared.tenants WHERE tenant_id = $1", tenant_id)
        print(f"DB check: is_active={row['is_active']}")
        assert row["is_active"] is False

        _step("2. GATE A BYPASS CHECK (pre-fix behaviour would succeed here) -- activate BEFORE onboarding")
        try:
            await admin.update_tenant(
                tenant_id, request, x_admin_secret=secret, plan_tier=None, is_active=True,
            )
            print("BUG: activation succeeded with no Gate A onboarding row at all!")
            raise RuntimeError("Gate A bypass guard did NOT block activation -- fix not effective")
        except HTTPException as e:
            print(f"Correctly rejected: {e.status_code} {e.detail}")
            assert e.status_code == 400
        row = await db.fetchrow("SELECT is_active FROM shared.tenants WHERE tenant_id = $1", tenant_id)
        print(f"DB check: is_active still {row['is_active']} (must still be False)")
        assert row["is_active"] is False

        _step("3. seed-atoms")
        seed_body = admin.SeedAtomsRequest(portfolio_id=UUID(PORTFOLIO_ID))
        seeded = await admin.seed_tenant_atoms(tenant_id, seed_body, request, x_admin_secret=secret)
        print(seeded)

        _step("4. GATE A BYPASS CHECK -- activate with onboarding row still 'pending' (angle not set)")
        try:
            await admin.update_tenant(
                tenant_id, request, x_admin_secret=secret, plan_tier=None, is_active=True,
            )
            raise RuntimeError("Gate A bypass guard did NOT block activation while pending")
        except HTTPException as e:
            print(f"Correctly rejected: {e.status_code} {e.detail}")
            assert e.status_code == 400

        _step("5. angle assign")
        angle_body = admin.AssignAngleRequest(assigned_angle="culinary_people")
        angle_result = await admin.assign_tenant_angle(tenant_id, angle_body, request, x_admin_secret=secret)
        print(angle_result)

        _step("6. gate-a/status BEFORE approve")
        status_before = await admin.get_gate_a_status(tenant_id, request, x_admin_secret=secret)
        print(status_before)
        assert status_before["approval_status"] == "pending"
        assert status_before["tenant_is_active"] is False

        _step("7. gate-a/approve")
        approve_body = admin.GateAApproveRequest(approved_by="Nghiep (AA-389 live verify)")
        approved = await admin.approve_gate_a(tenant_id, approve_body, request, x_admin_secret=secret)
        print(approved)
        row = await db.fetchrow("SELECT is_active FROM shared.tenants WHERE tenant_id = $1", tenant_id)
        print(f"DB check: is_active={row['is_active']} (must now be True)")
        assert row["is_active"] is True

        _step("8. double-approve -- expect 409, no silent no-op")
        try:
            await admin.approve_gate_a(tenant_id, approve_body, request, x_admin_secret=secret)
            raise RuntimeError("double-approve was not rejected")
        except HTTPException as e:
            print(f"Correctly rejected: {e.status_code} {e.detail}")
            assert e.status_code == 409

        _step("9. deactivate (business suspend) then REACTIVATE -- must succeed now (already approved once)")
        await admin.update_tenant(tenant_id, request, x_admin_secret=secret, plan_tier=None, is_active=False)
        row = await db.fetchrow("SELECT is_active FROM shared.tenants WHERE tenant_id = $1", tenant_id)
        print(f"DB check after deactivate: is_active={row['is_active']}")
        assert row["is_active"] is False
        await admin.update_tenant(tenant_id, request, x_admin_secret=secret, plan_tier=None, is_active=True)
        row = await db.fetchrow("SELECT is_active FROM shared.tenants WHERE tenant_id = $1", tenant_id)
        print(f"DB check after reactivate: is_active={row['is_active']} (must be True, Gate A already cleared)")
        assert row["is_active"] is True

        print("\nALL CHECKS PASSED")

    except Exception as e:
        print(f"\nFAILED: {type(e).__name__}: {e}")
        raise

    finally:
        if tenant_id is not None:
            _step("CLEANUP -- deleting AA-389 test tenant + related rows")
            await db.execute("DELETE FROM acp_shared.audit_log WHERE tenant_id = $1", str(tenant_id))
            await db.execute("DELETE FROM acp_shared.tenant_onboarding WHERE tenant_id = $1", tenant_id)
            await db.execute("DELETE FROM acp_shared.tenant_atom_state WHERE tenant_id = $1", tenant_id)
            await db.execute("DELETE FROM acp_shared.acp_quota_ledger WHERE tenant_id = $1", tenant_id)
            await db.execute("DELETE FROM shared.tenant_brand_rules WHERE tenant_id = $1", tenant_id)
            await db.execute("DELETE FROM shared.tenants WHERE tenant_id = $1", tenant_id)
            remaining = await db.fetchval("SELECT count(*) FROM shared.tenants WHERE tenant_id = $1", tenant_id)
            print(f"remaining={remaining}")
        await db.close()
        print(f"\n{DONE_MARKER}")


if __name__ == "__main__":
    asyncio.run(main())
