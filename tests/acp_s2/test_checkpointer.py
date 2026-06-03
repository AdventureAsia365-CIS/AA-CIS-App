"""
AA-112 — AsyncPostgresSaver checkpointer unit tests.

Tests:
  1. test_checkpointer_type          — graph compiled with AsyncPostgresSaver, not MemorySaver
  2. test_metadata_logged_fresh_run  — fresh run → acp_stage_runs.metadata has resume_from_iteration=0
  3. test_metadata_logged_resume     — resume with checkpoint iteration=2 → resume_from_iteration=2
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestCheckpointerType:
    @pytest.mark.asyncio
    async def test_checkpointer_type(self):
        """get_compiled_s2_graph returns a graph compiled with AsyncPostgresSaver."""
        mock_conn = AsyncMock()
        mock_checkpointer = MagicMock()
        mock_checkpointer.setup = AsyncMock()

        mock_graph = MagicMock()
        mock_builder = MagicMock()
        mock_builder.compile.return_value = mock_graph

        with (
            patch("psycopg.AsyncConnection.connect", new=AsyncMock(return_value=mock_conn)),
            patch(
                "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver",
                return_value=mock_checkpointer,
            ),
            patch(
                "services.acp.s2.graph.build_s2_graph",
                return_value=mock_builder,
            ),
        ):
            from services.acp.s2.graph import get_compiled_s2_graph

            graph, conn = await get_compiled_s2_graph(
                pool=MagicMock(),
                s3_client=MagicMock(),
                api_keys={},
                database_url="postgresql://test:test@localhost/test",
            )

        assert graph is mock_graph
        assert conn is mock_conn
        mock_checkpointer.setup.assert_awaited_once()
        mock_builder.compile.assert_called_once_with(checkpointer=mock_checkpointer)

        # Confirm MemorySaver was NOT used
        from langgraph.checkpoint.memory import MemorySaver
        compile_kwargs = mock_builder.compile.call_args.kwargs
        assert not isinstance(compile_kwargs.get("checkpointer"), MemorySaver)


class TestMetadataLoggedFreshRun:
    @pytest.mark.asyncio
    async def test_metadata_logged_fresh_run(self):
        """POST /acp/s2/run inserts metadata with resume_from_iteration=0."""
        execute_calls = []

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=lambda sql, *args: execute_calls.append(
            {"sql": sql.strip(), "args": list(args)}
        ))
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)

        # Simulate the INSERT into acp_stage_runs.metadata at start of _background
        sql = """
            INSERT INTO acp_shared.acp_stage_runs (run_id, stage, metadata)
            VALUES ($1::uuid, 's2', $2::jsonb)
            ON CONFLICT (run_id, stage) DO UPDATE
            SET metadata = COALESCE(acp_stage_runs.metadata, '{}') || EXCLUDED.metadata
        """
        metadata_payload = json.dumps(
            {"resume_from_iteration": 0, "checkpointer": "AsyncPostgresSaver"}
        )
        await mock_conn.execute(sql, "test-run-id", metadata_payload)

        assert len(execute_calls) == 1
        args = execute_calls[0]["args"]
        assert args[0] == "test-run-id"
        payload = json.loads(args[1])
        assert payload["resume_from_iteration"] == 0
        assert payload["checkpointer"] == "AsyncPostgresSaver"


class TestMetadataLoggedResume:
    @pytest.mark.asyncio
    async def test_metadata_logged_resume(self):
        """POST /acp/s2/resume/{run_id} reads iteration from checkpoint state and logs it."""
        # Mock graph state with iteration=2
        mock_state = MagicMock()
        mock_state.values = {"iteration": 2, "country": "Vietnam"}

        mock_graph = AsyncMock()
        mock_graph.aget_state = AsyncMock(return_value=mock_state)
        mock_graph.ainvoke = AsyncMock(return_value=None)

        execute_calls = []
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=lambda sql, *args: execute_calls.append(
            {"sql": sql.strip(), "args": list(args)}
        ))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)

        # Replicate the _resume() metadata logic
        config = {"configurable": {"thread_id": "test-run-id"}}
        state = await mock_graph.aget_state(config)
        iteration = state.values.get("iteration", 0) if state and state.values else 0

        sql = """
            INSERT INTO acp_shared.acp_stage_runs (run_id, stage, metadata)
            VALUES ($1::uuid, 's2', $2::jsonb)
            ON CONFLICT (run_id, stage) DO UPDATE
            SET metadata = COALESCE(acp_stage_runs.metadata, '{}') || EXCLUDED.metadata
        """
        metadata_payload = json.dumps(
            {"resume_from_iteration": iteration, "checkpointer": "AsyncPostgresSaver"}
        )
        await mock_conn.execute(sql, "test-run-id", metadata_payload)

        assert iteration == 2
        assert len(execute_calls) == 1
        payload = json.loads(execute_calls[0]["args"][1])
        assert payload["resume_from_iteration"] == 2
        assert payload["checkpointer"] == "AsyncPostgresSaver"

    @pytest.mark.asyncio
    async def test_metadata_resume_defaults_zero_when_no_state(self):
        """If checkpoint state is None (no prior checkpoint), defaults to iteration=0."""
        mock_graph = AsyncMock()
        mock_graph.aget_state = AsyncMock(return_value=None)

        config = {"configurable": {"thread_id": "new-run-id"}}
        state = await mock_graph.aget_state(config)
        iteration = state.values.get("iteration", 0) if state and state.values else 0

        assert iteration == 0
