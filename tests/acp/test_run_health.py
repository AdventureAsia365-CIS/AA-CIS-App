"""
AA-141 — Run-Health endpoint + SLO helpers unit tests.

Tests:
  1. test_slo_stage_duration_breach          — check_stage_slo returns True when exceeded
  2. test_slo_stage_duration_ok              — returns False within threshold
  3. test_slo_gate_sla_breach                — check_gate_sla returns True when exceeded
  4. test_slo_gate_sla_ok                    — returns False within threshold
  5. test_cost_cap_flagged                   — check_cost_cap True above $10
  6. test_cost_cap_ok                        — check_cost_cap False at/below $10
  7. test_run_health_endpoint_returns_all_runs — admin-secret path returns list
  8. test_run_health_filters_by_tenant       — admin with tenant_id param filters correctly
  9. test_run_health_rls_tenant_sees_own_only — JWT tenant sees own run only
 10. test_stuck_run_detection                — stage running > SLO marks run as stuck
 11. test_cost_cap_breached_flag             — cost > 10 sets cost_cap_breached=True
 12. test_gate_sla_breach_in_response        — pending gate past SLA sets breached=True
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ── 1-6: Pure SLO helper tests ────────────────────────────────────────────────

class TestSLOHelpers:
    def test_slo_stage_duration_breach(self):
        from api.services.acp_health import check_stage_slo
        assert check_stage_slo("s2", 31 * 60) is True   # 31 min > 30 min SLO

    def test_slo_stage_duration_ok(self):
        from api.services.acp_health import check_stage_slo
        assert check_stage_slo("s2", 29 * 60) is False   # 29 min < 30 min SLO

    def test_slo_unknown_stage_never_breaches(self):
        from api.services.acp_health import check_stage_slo
        assert check_stage_slo("s0", 999_999) is False

    def test_slo_gate_sla_breach(self):
        from api.services.acp_health import check_gate_sla
        assert check_gate_sla(1, 5.0) is True    # 5h > Gate 1 SLA of 4h

    def test_slo_gate_sla_ok(self):
        from api.services.acp_health import check_gate_sla
        assert check_gate_sla(1, 3.9) is False   # 3.9h < Gate 1 SLA of 4h

    def test_slo_gate_sla_unknown_gate(self):
        from api.services.acp_health import check_gate_sla
        assert check_gate_sla(99, 1000.0) is False

    def test_cost_cap_flagged(self):
        from api.services.acp_health import check_cost_cap
        assert check_cost_cap(10.01) is True

    def test_cost_cap_ok(self):
        from api.services.acp_health import check_cost_cap
        assert check_cost_cap(10.0) is False    # exactly at cap → not breached
        assert check_cost_cap(9.99) is False


# ── Fixtures for endpoint tests ───────────────────────────────────────────────

RUN_ID = "aaaaaaaa-0000-0000-0000-000000000001"
TENANT_ID = "bbbbbbbb-0000-0000-0000-000000000001"
OTHER_TENANT_ID = "cccccccc-0000-0000-0000-000000000001"
NOW = datetime.now(timezone.utc)


def _make_run(run_id=RUN_ID, tenant_id=TENANT_ID, status="completed", cost=3.5):
    return {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "country": "Vietnam",
        "status": status,
        "total_llm_cost_usd": cost,
        "started_at": NOW - timedelta(hours=2),
        "completed_at": NOW - timedelta(minutes=5),
        "error_message": None,
    }


_UNSET = object()


def _make_stage(run_id=RUN_ID, stage="s2", status="completed",
                started_at=None, completed_at=_UNSET, error_msg=None, cost=1.0):
    started = started_at or (NOW - timedelta(minutes=20))
    completed = (NOW - timedelta(minutes=5)) if completed_at is _UNSET else completed_at
    return {
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "started_at": started,
        "completed_at": completed,
        "error_msg": error_msg,
        "llm_cost_usd": cost,
    }


def _make_hitl(run_id=RUN_ID, stage=2, status="pending",
               created_at=None, resolved_at=None):
    return {
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "created_at": created_at or (NOW - timedelta(hours=3)),
        "resolved_at": resolved_at,
        "auto_approved": False,
        "confidence_score": None,
    }


def _build_app_with_mock_pool(run_rows, stage_rows, hitl_rows, eval_rows):
    """Build a minimal FastAPI test app wiring mock DB results."""
    from fastapi import FastAPI
    from api.routers.acp_health import router

    app = FastAPI()
    app.include_router(router)

    conn = AsyncMock()

    async def _fetch_side_effect(sql, *args, **kwargs):
        sql_stripped = " ".join(sql.split())
        if "acp_shared.acp_runs" in sql_stripped:
            return run_rows
        if "acp_shared.acp_stage_runs" in sql_stripped:
            return stage_rows
        if "acp_shared.acp_hitl_requests" in sql_stripped:
            return hitl_rows
        if "acp_silver_s4.blog_drafts" in sql_stripped:
            return eval_rows
        return []

    conn.fetch = AsyncMock(side_effect=_fetch_side_effect)

    pool_mock = AsyncMock()
    pool_mock.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    app.state.pool = pool_mock
    return app


# ── 7-12: Endpoint tests ──────────────────────────────────────────────────────

class TestRunHealthEndpoint:
    @pytest.mark.asyncio
    async def test_run_health_endpoint_returns_all_runs(self):
        """Admin-secret caller gets all runs."""
        from httpx import AsyncClient, ASGITransport

        run = _make_run()
        app = _build_app_with_mock_pool(
            run_rows=[run],
            stage_rows=[_make_stage()],
            hitl_rows=[],
            eval_rows=[],
        )

        admin_secret = "test-secret"
        with patch.dict("os.environ", {"ADMIN_SECRET": admin_secret}):
            with patch("api.routers.acp_health._emit_cloudwatch_metrics"):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/admin/acp/run-health",
                        headers={"X-Admin-Secret": admin_secret},
                    )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["run_id"] == RUN_ID

    @pytest.mark.asyncio
    async def test_run_health_filters_by_tenant(self):
        """Admin with tenant_id param limits to that tenant."""
        from httpx import AsyncClient, ASGITransport

        run = _make_run(tenant_id=TENANT_ID)
        app = _build_app_with_mock_pool(
            run_rows=[run],
            stage_rows=[],
            hitl_rows=[],
            eval_rows=[],
        )

        admin_secret = "test-secret"
        with patch.dict("os.environ", {"ADMIN_SECRET": admin_secret}):
            with patch("api.routers.acp_health._emit_cloudwatch_metrics"):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        f"/admin/acp/run-health?tenant_id={TENANT_ID}",
                        headers={"X-Admin-Secret": admin_secret},
                    )

        assert resp.status_code == 200
        data = resp.json()
        assert all(r["tenant_id"] == TENANT_ID for r in data)

    @pytest.mark.asyncio
    async def test_run_health_rls_tenant_sees_own_only(self):
        """Tenant JWT: SQL query includes tenant_id filter (non-admin path)."""
        from httpx import AsyncClient, ASGITransport
        from api.routers.acp_health import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        captured_sqls = []
        conn = AsyncMock()

        async def _fetch(sql, *args, **kwargs):
            captured_sqls.append(sql)
            return []

        conn.fetch = AsyncMock(side_effect=_fetch)
        pool_mock = AsyncMock()
        pool_mock.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=None),
        ))
        app.state.pool = pool_mock

        fake_payload = {"sub": TENANT_ID, "role": "tenant"}
        with patch("api.routers.acp_health._verify_jwt", return_value=fake_payload):
            with patch("api.routers.acp_health._emit_cloudwatch_metrics"):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/admin/acp/run-health",
                        headers={"Authorization": "Bearer fake-token"},
                    )

        assert resp.status_code == 200
        # First SQL (acp_runs query) must contain the tenant RLS filter
        runs_sql = captured_sqls[0] if captured_sqls else ""
        assert "tenant_id" in runs_sql

    @pytest.mark.asyncio
    async def test_stuck_run_detection(self):
        """Stage running > SLO duration → run.stuck=True."""
        from httpx import AsyncClient, ASGITransport

        run = _make_run(status="running")
        # S2 running for 35 min (> 30 min SLO)
        stuck_stage = _make_stage(
            stage="s2",
            status="running",
            started_at=NOW - timedelta(minutes=35),
            completed_at=None,
        )

        app = _build_app_with_mock_pool(
            run_rows=[run],
            stage_rows=[stuck_stage],
            hitl_rows=[],
            eval_rows=[],
        )

        admin_secret = "test-secret"
        with patch.dict("os.environ", {"ADMIN_SECRET": admin_secret}):
            with patch("api.routers.acp_health._emit_cloudwatch_metrics"):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/admin/acp/run-health",
                        headers={"X-Admin-Secret": admin_secret},
                    )

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["stuck"] is True
        stuck_stage_out = next(s for s in data[0]["stages"] if s["stage"] == "s2")
        assert stuck_stage_out["slo_breached"] is True

    @pytest.mark.asyncio
    async def test_cost_cap_breached_flag(self):
        """Run cost > $10 → cost_cap_breached=True."""
        from httpx import AsyncClient, ASGITransport

        run = _make_run(cost=12.5)
        app = _build_app_with_mock_pool(
            run_rows=[run],
            stage_rows=[],
            hitl_rows=[],
            eval_rows=[],
        )

        admin_secret = "test-secret"
        with patch.dict("os.environ", {"ADMIN_SECRET": admin_secret}):
            with patch("api.routers.acp_health._emit_cloudwatch_metrics"):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/admin/acp/run-health",
                        headers={"X-Admin-Secret": admin_secret},
                    )

        assert resp.status_code == 200
        assert resp.json()[0]["cost_cap_breached"] is True

    @pytest.mark.asyncio
    async def test_gate_sla_breach_in_response(self):
        """Pending gate past SLA → gate_statuses.gate_1.breached=True."""
        from httpx import AsyncClient, ASGITransport

        run = _make_run()
        # Gate 1 = stage 2, SLA 4h — created 5h ago, still pending
        hitl = _make_hitl(
            stage=2,
            status="pending",
            created_at=NOW - timedelta(hours=5),
            resolved_at=None,
        )

        app = _build_app_with_mock_pool(
            run_rows=[run],
            stage_rows=[],
            hitl_rows=[hitl],
            eval_rows=[],
        )

        admin_secret = "test-secret"
        with patch.dict("os.environ", {"ADMIN_SECRET": admin_secret}):
            with patch("api.routers.acp_health._emit_cloudwatch_metrics"):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/admin/acp/run-health",
                        headers={"X-Admin-Secret": admin_secret},
                    )

        assert resp.status_code == 200
        gate1 = resp.json()[0]["gate_statuses"]["gate_1"]
        assert gate1["breached"] is True
        assert gate1["sla_hours"] == 4.0
