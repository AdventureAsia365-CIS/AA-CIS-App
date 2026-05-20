"""
S2 LangGraph research agent graph.

build_s2_graph(pool, s3_client, api_keys) → CompiledStateGraph

Linear flow: dataforseo → apify → google_trends → reddit → gsc → expand_scope → synthesize
Conditional logic is handled inside each node (no-op if condition not met).

Checkpointing: uses AsyncPostgresSaver if langgraph-checkpoint-postgres is installed;
falls back to MemorySaver (loses state across pod restarts — not for production).
"""
import os
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


def build_s2_graph(pool, s3_client, api_keys: dict):
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

    checkpointer = _make_checkpointer()
    return builder.compile(checkpointer=checkpointer)


def _make_checkpointer():
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        db_url = os.environ["DATABASE_URL"]
        logger.info("s2_graph_using_postgres_checkpointer")
        return AsyncPostgresSaver.from_conn_string(db_url, schema_name="acp_shared")
    except (ImportError, KeyError, Exception) as exc:
        from langgraph.checkpoint.memory import MemorySaver
        logger.warning("s2_graph_using_memory_checkpointer", reason=str(exc))
        return MemorySaver()
