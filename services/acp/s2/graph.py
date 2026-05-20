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


def build_s2_graph(pool, s3_client, api_keys: dict) -> StateGraph:
    """Build the S2 state graph with nodes wired to runtime dependencies.
    Returns an uncompiled StateGraph — caller must compile with a checkpointer.
    """
    builder = StateGraph(S2AgentState)

    builder.add_node("dataforseo",    make_dataforseo_node(pool, s3_client, api_keys))
    builder.add_node("apify",         make_apify_node(pool, s3_client, api_keys))
    builder.add_node("google_trends", make_google_trends_node(pool, s3_client))
    builder.add_node("reddit",        make_reddit_node(pool, s3_client))
    builder.add_node("gsc",           make_gsc_node(pool))
    builder.add_node("expand_scope",  make_expand_scope_node(s3_client, api_keys))
    builder.add_node("synthesize",    make_synthesize_node(pool, s3_client))

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
    """Build and compile the S2 graph with an AsyncPostgresSaver checkpointer.
    Calls checkpointer.setup() to create checkpoint tables in acp_shared schema.
    Must be awaited inside an async lifespan context.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    checkpointer = AsyncPostgresSaver.from_conn_string(database_url)
    await checkpointer.setup()
    logger.info("s2_graph_postgres_checkpointer_ready")

    builder = build_s2_graph(pool, s3_client, api_keys)
    return builder.compile(checkpointer=checkpointer)
