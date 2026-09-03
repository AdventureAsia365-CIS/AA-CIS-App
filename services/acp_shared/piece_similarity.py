"""
services.acp_shared.piece_similarity — AA-499 (AA-494 Decision 5). Reads
`content_piece.content_embedding` (written by `services.acp_content_writing.service` at
`_finalize_piece()` time, `status='approved'` only — see that module's own comment).

Migration 124's own column comment: "for within-tenant/cross-tenant similarity checks (shared
mechanism, two call sites)." `find_similar_pieces()` IS that shared mechanism — one function,
`cross_tenant: bool` picks the scope:

- `cross_tenant=False` (this build's own consumption — see
  `services.acp_content_writing.service`'s within-tenant reuse flag): scoped to `$1 = tenant_id`,
  a soft/informational signal only (`flags`, non-blocking, ADR 0023's shape).
- `cross_tenant=True` (NOT consumed by any code in THIS build — provided as reusable
  infrastructure for AA-484's cannibalization gate, which `blocks` this issue in Linear and whose
  origin design, AA-332, already has a Nghiệp-confirmed decision (Q6=B, 25/07/2026, cited in
  AA-484's own Linear comment) to run cross-tenant cosine similarity as a real BLOCKING gate at
  threshold 0.92 — that confirmed decision is what licenses building the cross-tenant CAPABILITY
  here; wiring it into anything tenant-visible remains AA-484's own scope, deliberately not
  built in this issue, per this issue's own explicit "cần xác nhận với Nghiệp, không tự suy diễn"
  caution about anything BEYOND that already-confirmed gate use). No tenant-facing endpoint in
  this codebase exposes cross-tenant results as of this build.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from services.acp_shared.content_embedding import embedding_to_pgvector_literal

# cosine distance ($1::vector <=> content_embedding) is in [0, 2]; similarity = 1 - distance.
# ORDER BY the raw distance operator (not the derived similarity) so pgvector's ivfflat index
# (migration 140) is actually used — computing "1 - distance" in the SELECT list doesn't block
# that, but ORDER BY on a computed expression instead of the bare operator can silently fall back
# to a sequential scan on some planner versions; kept as the operator itself for safety.
_WITHIN_TENANT_QUERY = """
    SELECT cp.piece_id, cp.tenant_id, agr.atom_id, cp.angle_gate_request_id,
           1 - (cp.content_embedding <=> $1::vector) AS similarity
    FROM acp_shared.content_piece cp
    JOIN acp_shared.angle_gate_request agr ON cp.angle_gate_request_id = agr.request_id
    WHERE cp.tenant_id = $2 AND cp.status = 'approved' AND cp.content_embedding IS NOT NULL
      AND ($3::uuid IS NULL OR cp.piece_id != $3)
    ORDER BY cp.content_embedding <=> $1::vector
    LIMIT $4
"""

# Same shape, no tenant_id WHERE clause — real cross-tenant scan. Not called by any code in this
# build (see this module's own header) — exercised only by its own unit tests, ready for AA-484.
_CROSS_TENANT_QUERY = """
    SELECT cp.piece_id, cp.tenant_id, agr.atom_id, cp.angle_gate_request_id,
           1 - (cp.content_embedding <=> $1::vector) AS similarity
    FROM acp_shared.content_piece cp
    JOIN acp_shared.angle_gate_request agr ON cp.angle_gate_request_id = agr.request_id
    WHERE cp.status = 'approved' AND cp.content_embedding IS NOT NULL
      AND ($2::uuid IS NULL OR cp.piece_id != $2)
    ORDER BY cp.content_embedding <=> $1::vector
    LIMIT $3
"""


@dataclass(frozen=True)
class SimilarPiece:
    piece_id: str
    tenant_id: str
    atom_id: Optional[str]
    similarity: float


async def find_similar_pieces(
    embedding: list[float], pool, *, tenant_id: Optional[UUID] = None,
    cross_tenant: bool = False, exclude_piece_id: Optional[UUID] = None, limit: int = 5,
) -> list[SimilarPiece]:
    """Returns up to `limit` approved pieces most similar to `embedding`, most similar first —
    NOT pre-filtered by any threshold (the caller decides what similarity counts as "too
    similar" for its own use case; a fixed threshold here would bake one call site's judgment
    into shared infrastructure). `tenant_id` is required unless `cross_tenant=True` (a within-
    tenant query with no tenant to scope by is a caller bug, not a valid "search everything"
    request — use `cross_tenant=True` explicitly for that)."""
    if not cross_tenant and tenant_id is None:
        raise ValueError("tenant_id is required unless cross_tenant=True")
    vector_literal = embedding_to_pgvector_literal(embedding)
    async with pool.acquire() as conn:
        if cross_tenant:
            rows = await conn.fetch(
                _CROSS_TENANT_QUERY, vector_literal,
                str(exclude_piece_id) if exclude_piece_id else None, limit,
            )
        else:
            rows = await conn.fetch(
                _WITHIN_TENANT_QUERY, vector_literal, tenant_id,
                str(exclude_piece_id) if exclude_piece_id else None, limit,
            )
    return [
        SimilarPiece(
            piece_id=str(r["piece_id"]), tenant_id=str(r["tenant_id"]),
            atom_id=r["atom_id"], similarity=float(r["similarity"]),
        )
        for r in rows
    ]


__all__ = ["SimilarPiece", "find_similar_pieces"]
