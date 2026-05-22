"""
Bedrock Titan Embed Text v2 — pgvector dedup + internal linking for S4 blog.
PRD v1.0 Q13: dedup cosine threshold 0.92.
Gracefully degrades when pgvector extension or embedding column is absent.
"""
import json
import logging
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

_EMBED_MODEL = "amazon.titan-embed-text-v2:0"
_EMBED_REGION = "us-west-1"
_DEDUP_THRESHOLD = 0.92
_LINK_MIN_SIMILARITY = 0.60
_BEDROCK = boto3.client("bedrock-runtime", region_name=_EMBED_REGION)


def embed_text(text: str) -> list[float]:
    """Generate 1536-dim embedding via Bedrock Titan Embed v2. Raises on failure."""
    response = _BEDROCK.invoke_model(
        modelId=_EMBED_MODEL,
        body=json.dumps({"inputText": text[:8000]}),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]


def _vec_literal(embedding: list[float]) -> str:
    return f"[{','.join(str(x) for x in embedding)}]"


async def check_blog_dedup(
    db_conn,
    tenant_id: str,
    title: str,
    primary_keyword: str,
    threshold: float = _DEDUP_THRESHOLD,
) -> Optional[str]:
    """
    Returns draft_id of an existing similar draft if cosine similarity > threshold, else None.
    Fails open (returns None) if pgvector unavailable or any error.
    """
    try:
        embedding = embed_text(f"{title} {primary_keyword}")
    except Exception as exc:
        logger.warning("dedup_embed_failed (non-fatal): %s", exc)
        return None

    try:
        row = await db_conn.fetchrow(
            """
            SELECT draft_id::text,
                   1 - (content_embedding <=> $1::vector) AS similarity
            FROM acp_silver_s4.blog_drafts
            WHERE tenant_id = $2
              AND content_embedding IS NOT NULL
              AND 1 - (content_embedding <=> $1::vector) > $3
            ORDER BY similarity DESC
            LIMIT 1
            """,
            _vec_literal(embedding), tenant_id, threshold,
        )
        if row:
            logger.info("dedup_hit similarity=%.3f existing=%s", row["similarity"], row["draft_id"])
            return row["draft_id"]
    except Exception as exc:
        logger.warning("dedup_query_failed (non-fatal): %s", exc)
    return None


async def find_internal_links(
    db_conn,
    tenant_id: str,
    section_text: str,
    top_k: int = 3,
    min_similarity: float = _LINK_MIN_SIMILARITY,
) -> list[dict]:
    """
    Semantic internal link suggestions via pgvector on published_tours.
    Returns list of {tour_id, aa_name, slug, similarity}.
    Fails open (returns []) if pgvector unavailable.
    """
    try:
        embedding = embed_text(section_text[:2000])
    except Exception as exc:
        logger.warning("internal_link_embed_failed (non-fatal): %s", exc)
        return []

    try:
        rows = await db_conn.fetch(
            """
            SELECT tour_id::text, aa_name,
                   LOWER(REPLACE(COALESCE(aa_name, ''), ' ', '-')) AS slug,
                   1 - (content_embedding <=> $1::vector) AS similarity
            FROM gold_aa_internal.published_tours
            WHERE tenant_id = $2
              AND content_embedding IS NOT NULL
              AND 1 - (content_embedding <=> $1::vector) > $3
            ORDER BY similarity DESC
            LIMIT $4
            """,
            _vec_literal(embedding), tenant_id, min_similarity, top_k,
        )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("internal_link_query_failed (non-fatal): %s", exc)
        return []


async def store_blog_embedding(db_conn, draft_id: str, title: str, primary_keyword: str) -> None:
    """Store content embedding on blog_drafts after INSERT. Non-fatal on failure."""
    try:
        embedding = embed_text(f"{title} {primary_keyword}")
        await db_conn.execute(
            "UPDATE acp_silver_s4.blog_drafts SET content_embedding = $1::vector WHERE draft_id = $2::uuid",
            _vec_literal(embedding), draft_id,
        )
        logger.info("blog_embedding_stored draft_id=%s", draft_id)
    except Exception as exc:
        logger.warning("blog_embedding_store_failed (non-fatal) draft_id=%s: %s", draft_id, exc)
