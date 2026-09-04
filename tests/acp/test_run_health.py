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
 10. test_stuck_detection_never_fires_for_v2_slots_yet — AA-491 rewrite: v2 slot data has no
     matching SLO mapping yet, so `stuck` stays False even for an overdue slot (real, current,
     documented behavior -- was asserting the opposite, pre-AA-441-rewrite v1 shape)
 11. test_cost_cap_never_breached_for_v2_runs_yet      — AA-491 rewrite: acp_v2_runs has no
     cost column (hardcoded 0.0), so cost_cap_breached stays False for every run today
 12. test_gate_statuses_all_none_for_v2_runs_yet       — AA-491 rewrite: no v2 hitl-request
     equivalent exists yet, so every gate_statuses.gate_N stays None for every run today

AA-491 (04/09/2026): tests 7-12 were failing before this rewrite -- NOT a missing env var or
DB fixture (the two hypotheses this issue's own description flagged as unconfirmed), but a
real, confirmed cause: AA-441 (already shipped) rewrote GET /admin/acp/run-health from the
legacy v1 tables to acp_v2_runs/acp_v2_slots, and this test file's mocks/fixtures were never
updated to match. See the fixture block below (and api/routers/acp_health.py's own docstring)
for the full trace.
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

# AA-491 STEP0 (04/09/2026): this whole fixture block used to mock the LEGACY v1 tables
# (acp_shared.acp_runs / acp_stage_runs / acp_hitl_requests / acp_silver_s4.blog_drafts).
# AA-441 (already shipped, real production fix) rewrote GET /admin/acp/run-health to read
# acp_shared.acp_v2_runs / acp_v2_slots instead -- the real, live N7/N8 tables -- because the
# v1 tables it used to read are the deliberately-unlinked ACP v1 pipeline, 0 live rows (see
# api/routers/acp_health.py's own docstring on get_run_health()). This test file was never
# updated for that rewrite: the mock matched on v1 table-name substrings that no longer appear
# in the real SQL, so `_fetch_side_effect` fell through to `return []` for every query --
# EVERY endpoint test failed with 0 rows back, not a missing-env-var or missing-fixture issue
# (the two hypotheses AA-491's own description flagged as unconfirmed). Confirmed the real
# cause via `git log`/reading acp_health.py directly, not assumed.
#
# AA-441's docstring also documents 3 real, deliberate, PERMANENT-FOR-NOW gaps in the v2 path
# (not bugs -- no v2 equivalent exists yet for this data):
#   * stuck-run detection: `check_stage_slo()` only recognizes v1 stage keys (s2/s3/s4_blog/
#     s4_social); a v2 "channel:kind" name (e.g. "email:newsletter") never matches -> always
#     returns False, so `stuck` can never be True for a v2 run today.
#   * cost cap: acp_v2_runs has no cost column -- `cost` is hardcoded 0.0 ("not tracked", not
#     "confirmed zero") -> `cost_cap_breached` can never be True today.
#   * gate SLA: no v2 equivalent to acp_hitl_requests exists yet -> `gate_statuses` is always
#     all-None for every run today.
# The 3 corresponding tests below (originally written against the v1 shape, asserting these
# COULD be True) are rewritten to assert the real, current, documented v2 behavior instead of
# a scenario the code cannot produce -- so they still catch a real regression (someone wiring
# v2 tracking back in without updating these) rather than encoding a wish.


def _make_run(run_id=RUN_ID, tenant_id=TENANT_ID, status="completed"):
    """Matches acp_v2_runs' real columns as SELECTed by get_run_health():
    run_id, tenant_id, status, created_at (aliased AS started_at), completed_at. No country/
    cost/error_message columns exist on acp_v2_runs (see module docstring above)."""
    return {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "status": status,
        "started_at": NOW - timedelta(hours=2),
        "completed_at": NOW - timedelta(minutes=5),
    }


def _make_slot(run_id=RUN_ID, channel="email", kind="newsletter", status="produced",
               due_at=None, produced_at=None, skipped_reason=None):
    """Matches acp_v2_slots' real columns as SELECTed by get_run_health(): run_id, slot_id,
    channel, kind, status, due_at, produced_at, skipped_reason."""
    return {
        "run_id": run_id,
        "slot_id": f"{run_id}-{channel}-{kind}",
        "channel": channel,
        "kind": kind,
        "status": status,
        "due_at": due_at or (NOW - timedelta(minutes=20)),
        "produced_at": produced_at if produced_at is not None else (NOW - timedelta(minutes=5)),
        "skipped_reason": skipped_reason,
    }


def _build_app_with_mock_pool(run_rows, slot_rows=None, **_unused_v1_fixtures):
    """Build a minimal FastAPI test app wiring mock DB results for the real v2 query shape.
    `**_unused_v1_fixtures` absorbs legacy hitl_rows/eval_rows kwargs from any caller that
    still passes them -- get_run_health() no longer queries either table (see module
    docstring), they were never a real input to the endpoint's actual behavior."""
    from fastapi import FastAPI
    from api.routers.acp_health import router

    app = FastAPI()
    app.include_router(router)

    conn = AsyncMock()

    async def _fetch_side_effect(sql, *args, **kwargs):
        sql_stripped = " ".join(sql.split())
        if "acp_shared.acp_v2_runs" in sql_stripped:
            return run_rows
        if "acp_shared.acp_v2_slots" in sql_stripped:
            return slot_rows or []
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
            slot_rows=[_make_slot()],
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
        assert data[0]["stages"][0]["stage"] == "email:newsletter"

    @pytest.mark.asyncio
    async def test_run_health_filters_by_tenant(self):
        """Admin with tenant_id param limits to that tenant."""
        from httpx import AsyncClient, ASGITransport

        run = _make_run(tenant_id=TENANT_ID)
        app = _build_app_with_mock_pool(run_rows=[run])

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
        # AA-491: the old assertion (`all(... for r in data)`) was vacuously true even for an
        # empty list -- it never actually caught the v1/v2 table-name mismatch that made every
        # one of these tests silently return 0 rows. Assert real data came back, not just that
        # nothing contradicted an empty response.
        assert len(data) == 1
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
    async def test_stuck_detection_never_fires_for_v2_slots_yet(self):
        """AA-491 rewrite (was test_stuck_run_detection, asserted `stuck is True`): a v2 slot
        "due" far past its due_at is exactly the shape that WOULD be stuck under the old v1
        stage-key model, but check_stage_slo() only recognizes v1 keys (s2/s3/s4_blog/
        s4_social) -- a v2 "channel:kind" name never matches, so `slo_breached`/`stuck` stay
        False today, by AA-441's own documented, deliberate design (no v2 SLO table yet). This
        locks in that real current behavior so a change here is a deliberate future feature,
        not a silent regression."""
        from httpx import AsyncClient, ASGITransport

        run = _make_run(status="running")
        # "due" 35 min past its due_at -- would be stuck if any v2 SLO mapping existed
        overdue_slot = _make_slot(
            channel="email", kind="newsletter", status="due",
            due_at=NOW - timedelta(minutes=35), produced_at=None,
        )

        app = _build_app_with_mock_pool(run_rows=[run], slot_rows=[overdue_slot])

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
        assert data[0]["stuck"] is False
        slot_out = data[0]["stages"][0]
        assert slot_out["slo_breached"] is False

    @pytest.mark.asyncio
    async def test_cost_cap_never_breached_for_v2_runs_yet(self):
        """AA-491 rewrite (was test_cost_cap_breached_flag, asserted `is True`):
        acp_v2_runs has no cost column -- get_run_health() hardcodes cost=0.0 ("not tracked",
        not "confirmed zero", see module docstring) -- so check_cost_cap(0.0) can never be
        True today, regardless of the run's real LLM spend. Locks in that real current
        behavior rather than asserting a scenario the code cannot produce."""
        from httpx import AsyncClient, ASGITransport

        run = _make_run()
        app = _build_app_with_mock_pool(run_rows=[run])

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
        assert data[0]["total_cost_usd"] == 0.0
        assert data[0]["cost_cap_breached"] is False

    @pytest.mark.asyncio
    async def test_gate_statuses_all_none_for_v2_runs_yet(self):
        """AA-491 rewrite (was test_gate_sla_breach_in_response, asserted gate_1.breached is
        True): no v2 equivalent to acp_hitl_requests exists yet, so hitl_by_run is always {}
        (see module docstring) -- every gate_statuses.gate_N stays None for every run today,
        regardless of any real pending-approval SLA. Locks in that real current behavior."""
        from httpx import AsyncClient, ASGITransport

        run = _make_run()
        app = _build_app_with_mock_pool(run_rows=[run])

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
        gate_statuses = data[0]["gate_statuses"]
        assert gate_statuses == {"gate_0": None, "gate_1": None, "gate_2": None, "gate_3": None}
