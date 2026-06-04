"""
AA-169: S2 auto crash-recovery + monitoring fields.

Tests:
  1. startup_recovery: no stuck runs → _do_resume_run never called
  2. startup_recovery: 1 stuck run (>2 min old, has checkpointer) → resume called once
  3. grace period: recovery query WHERE clause contains the 2-minute interval guard
  4. no-checkpointer: recovery query WHERE clause filters on metadata ? 'checkpointer'
  5. current_iteration: _with_iteration_update writes node index after each node
  6. compute_saved_pct: ratio computed from dataforseo_cache_hit + apify_cache_hit
"""
import json
import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_pool_mock(fetch_rows=None, execute_ok=True):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=fetch_rows or [])
    mock_conn.execute = AsyncMock(return_value=None)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=mock_conn)
    return mock_pool, mock_conn


# ── Startup recovery: no stuck runs ──────────────────────────────────────────

class TestStartupRecoveryNoRuns:
    @pytest.mark.asyncio
    async def test_no_stuck_runs_no_resume(self):
        """When DB returns no stuck rows, _do_resume_run must never be called."""
        mock_pool, _ = _make_pool_mock(fetch_rows=[])
        mock_graph = MagicMock()

        resume_mock = AsyncMock()
        with patch("api.main._do_resume_run", new=resume_mock):
            from api.main import _recover_stuck_s2_runs
            await _recover_stuck_s2_runs(mock_pool, mock_graph)

        resume_mock.assert_not_awaited()


# ── Startup recovery: stuck run auto-resumed ─────────────────────────────────

class TestStartupRecoveryStuckRun:
    @pytest.mark.asyncio
    async def test_stuck_run_resumes(self):
        """A single stuck run (checkpointer in metadata, >2 min old) must be resumed."""
        run_id = "aaaaaaaa-0000-0000-0000-000000000001"
        tenant_id = "00000000-0000-0000-0000-000000000001"

        row = {"run_id": run_id, "tenant_id": tenant_id}
        mock_pool, _ = _make_pool_mock(fetch_rows=[row])
        mock_graph = MagicMock()

        resume_mock = AsyncMock()
        # Patch in the module where _recover_stuck_s2_runs looks up the name
        with patch("api.main._do_resume_run", new=resume_mock):
            import api.main as main_mod
            await main_mod._recover_stuck_s2_runs(mock_pool, mock_graph)

        resume_mock.assert_awaited_once_with(run_id, tenant_id, mock_pool, mock_graph)

    @pytest.mark.asyncio
    async def test_failed_resume_does_not_abort_others(self):
        """If one run fails to resume, processing continues for remaining runs."""
        rows = [
            {"run_id": "aaaaaaaa-0000-0000-0000-000000000001",
             "tenant_id": "00000000-0000-0000-0000-000000000001"},
            {"run_id": "bbbbbbbb-0000-0000-0000-000000000002",
             "tenant_id": "00000000-0000-0000-0000-000000000001"},
        ]
        mock_pool, _ = _make_pool_mock(fetch_rows=rows)
        mock_graph = MagicMock()

        call_count = 0

        async def _side_effect(run_id, tenant_id, pool, graph):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated resume failure")

        with patch("api.main._do_resume_run", side_effect=_side_effect):
            import api.main as main_mod
            await main_mod._recover_stuck_s2_runs(mock_pool, mock_graph)

        assert call_count == 2, "Both runs must be attempted even when first fails"


# ── Startup recovery: SQL filters (grace period + checkpointer) ───────────────

class TestStartupRecoverySQLFilters:
    def test_recovery_sql_has_grace_period(self):
        """_recover_stuck_s2_runs SQL must enforce the 2-minute grace period."""
        import inspect, api.main as main_mod
        src = inspect.getsource(main_mod._recover_stuck_s2_runs)
        assert "INTERVAL '2 minutes'" in src, (
            "_recover_stuck_s2_runs must use INTERVAL '2 minutes' to guard against "
            "resuming runs that are still legitimately running"
        )

    def test_recovery_sql_filters_on_checkpointer(self):
        """_recover_stuck_s2_runs SQL must filter on metadata ? 'checkpointer'."""
        import inspect, api.main as main_mod
        src = inspect.getsource(main_mod._recover_stuck_s2_runs)
        assert "metadata ? 'checkpointer'" in src, (
            "Recovery must only resume runs whose metadata contains a 'checkpointer' key — "
            "runs without one cannot be replayed"
        )


# ── current_iteration written per node ───────────────────────────────────────

class TestCurrentIterationWritten:
    @pytest.mark.asyncio
    async def test_iteration_written_after_node(self):
        """_with_iteration_update must write current_iteration to acp_stage_runs after node run."""
        from services.acp.s2.graph import _with_iteration_update

        node_index = 3
        run_id = "cccccccc-0000-0000-0000-000000000003"

        mock_node = AsyncMock(return_value={"some_key": "some_val"})
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)

        wrapped = _with_iteration_update(mock_node, node_index, mock_pool)
        state = {"run_id": run_id, "country": "Thailand"}
        result = await wrapped(state)

        assert result == {"some_key": "some_val"}
        mock_conn.execute.assert_awaited_once()
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        assert "current_iteration" in sql
        positional_args = call_args[0]
        assert str(node_index) in positional_args

    @pytest.mark.asyncio
    async def test_iteration_update_failure_is_non_fatal(self):
        """A DB error in the iteration update must not propagate — node result is returned."""
        from services.acp.s2.graph import _with_iteration_update

        mock_node = AsyncMock(return_value={"result": "ok"})
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("db down"))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)

        wrapped = _with_iteration_update(mock_node, 1, mock_pool)
        result = await wrapped({"run_id": "dddddddd-0000-0000-0000-000000000004"})

        assert result == {"result": "ok"}, "Node result must be returned even when metadata write fails"


# ── compute_saved_pct calculation ─────────────────────────────────────────────

class TestComputeSavedPct:
    def _compute(self, dfs_hit: bool, apify_hit: bool) -> int:
        """Mirror the router.py calculation."""
        cache_hits = int(dfs_hit) + int(apify_hit)
        return round((cache_hits / 2) * 100)

    def test_both_cached(self):
        assert self._compute(True, True) == 100

    def test_none_cached(self):
        assert self._compute(False, False) == 0

    def test_one_cached(self):
        assert self._compute(True, False) == 50
        assert self._compute(False, True) == 50

    def test_router_source_computes_pct(self):
        """Verify router.py source contains the compute_saved_pct write after ainvoke."""
        src = open("services/acp/s2/router.py", encoding="utf-8").read()
        assert "compute_saved_pct" in src
        assert "dataforseo_cache_hit" in src
        assert "apify_cache_hit" in src

    def test_apify_returns_cache_hit_flag(self):
        """apify.py must return apify_cache_hit=True on cache-hit path."""
        src = open("services/acp/s2/tools/apify.py", encoding="utf-8").read()
        assert '"apify_cache_hit": True' in src or "'apify_cache_hit': True" in src, (
            "apify.py cache-hit branch must return apify_cache_hit=True for compute_saved_pct"
        )
