"""
S2 LangGraph research agent graph.

build_s2_graph(pool, s3_client, api_keys) → StateGraph (uncompiled)
get_compiled_s2_graph(pool, s3_client, api_keys, database_url) → compiled graph

Separated so the checkpointer (AsyncPostgresSaver) can be awaited at startup
without mixing sync construction with async setup.
"""
import structlog
from langgraph.graph import StateGraph, START, END

from services.acp.s2.state import S2AgentState
from services.acp.s2.tools import (
    make_dataforseo_node,
    make_apify_node,
    make_google_trends_node,
    make_reddit_node,
    make_gsc_node,
    make_expand_scope_node,
    make_synthesize_node,
)

logger = structlog.get_logger()


def _with_iteration_update(node_fn, node_index: int, pool):
    """Wrap a graph node to write current_iteration to acp_stage_runs.metadata after it runs."""
    async def _wrapped(state: dict) -> dict:
        result = await node_fn(state)
        run_id = state.get("run_id")
        if run_id:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE acp_shared.acp_stage_runs
                        SET metadata = COALESCE(acp_stage_runs.metadata, '{}') ||
                                       jsonb_build_object('current_iteration', $1::text),
                            updated_at = NOW()
                        WHERE run_id = $2::uuid AND stage = 's2'
                        """,
                        str(node_index), run_id,
                    )
            except Exception as exc:
                logger.warning("iteration_update_failed", run_id=run_id,
                               node_index=node_index, error=str(exc))
        return result
    return _wrapped


def build_s2_graph(pool, s3_client, api_keys: dict) -> StateGraph:
    """Build the S2 state graph with nodes wired to runtime dependencies.
    Returns an uncompiled StateGraph — caller must compile with a checkpointer.
    """
    builder = StateGraph(S2AgentState)

    _nodes = [
        ("dataforseo",    make_dataforseo_node(pool, s3_client, api_keys)),
        ("apify",         make_apify_node(pool, s3_client, api_keys)),
        ("google_trends", make_google_trends_node(pool, s3_client)),
        ("reddit",        make_reddit_node(pool, s3_client)),
        ("gsc",           make_gsc_node(pool)),
        ("expand_scope",  make_expand_scope_node(s3_client, api_keys)),
        ("synthesize",    make_synthesize_node(pool, s3_client)),
    ]
    for i, (name, fn) in enumerate(_nodes, start=1):
        builder.add_node(name, _with_iteration_update(fn, i, pool))

    builder.add_edge(START,           "dataforseo")
    builder.add_edge("dataforseo",    "apify")
    builder.add_edge("apify",         "google_trends")
    builder.add_edge("google_trends", "reddit")
    builder.add_edge("reddit",        "gsc")
    builder.add_edge("gsc",           "expand_scope")
    builder.add_edge("expand_scope",  "synthesize")
    builder.add_edge("synthesize",    END)

    return builder


async def get_compiled_s2_graph(pool, s3_client, api_keys: dict, database_url: str):
    """Build and compile the S2 graph with AsyncPostgresSaver checkpointer.

    Opens a single long-lived psycopg3 connection for the checkpointer.
    Returns (compiled_graph, pg_conn) — caller must close pg_conn on shutdown.
    AsyncPostgresSaver.setup() creates LangGraph-internal tables (checkpoints,
    checkpoint_writes, checkpoint_blobs) in the public schema.
    """
    import psycopg
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    conn = await psycopg.AsyncConnection.connect(database_url, autocommit=True)
    checkpointer = AsyncPostgresSaver(conn)
    await checkpointer.setup()
    builder = build_s2_graph(pool, s3_client, api_keys)
    graph = builder.compile(checkpointer=checkpointer)
    logger.info("s2_graph_postgres_checkpointer_ready")
    return graph, conn
