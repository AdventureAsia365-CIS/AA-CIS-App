"""AA-499 (AA-494 Decision 5) — services/acp_shared/piece_similarity.py."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.acp_shared.piece_similarity import SimilarPiece, find_similar_pieces

TENANT_ID = uuid.uuid4()
EMBEDDING = [0.1] * 1536


def _make_pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _row(piece_id, tenant_id, atom_id, similarity):
    return {
        "piece_id": piece_id, "tenant_id": tenant_id, "atom_id": atom_id,
        "angle_gate_request_id": uuid.uuid4(), "similarity": similarity,
    }


@pytest.mark.asyncio
class TestFindSimilarPieces:
    async def test_within_tenant_maps_rows(self):
        pid = uuid.uuid4()
        conn = AsyncMock()
        conn.fetch.return_value = [_row(pid, TENANT_ID, "atom_other", 0.95)]
        pool = _make_pool(conn)
        result = await find_similar_pieces(EMBEDDING, pool, tenant_id=TENANT_ID)
        assert result == [SimilarPiece(piece_id=str(pid), tenant_id=str(TENANT_ID),
                                        atom_id="atom_other", similarity=0.95)]

    async def test_within_tenant_uses_the_scoped_query_with_tenant_param(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        await find_similar_pieces(EMBEDDING, pool, tenant_id=TENANT_ID, limit=3)
        query, *params = conn.fetch.call_args[0]
        assert "WHERE cp.tenant_id = $2" in query
        assert params[1] == TENANT_ID
        assert params[-1] == 3

    async def test_missing_tenant_id_without_cross_tenant_raises(self):
        pool = _make_pool(AsyncMock())
        with pytest.raises(ValueError):
            await find_similar_pieces(EMBEDDING, pool, tenant_id=None, cross_tenant=False)

    async def test_cross_tenant_scans_without_tenant_filter(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        await find_similar_pieces(EMBEDDING, pool, cross_tenant=True)
        query = conn.fetch.call_args[0][0]
        assert "cp.tenant_id = " not in query  # the SELECT list legitimately names the column

    async def test_exclude_piece_id_passed_through(self):
        exclude = uuid.uuid4()
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        await find_similar_pieces(EMBEDDING, pool, tenant_id=TENANT_ID, exclude_piece_id=exclude)
        params = conn.fetch.call_args[0]
        assert str(exclude) in params

    async def test_empty_result_is_not_an_error(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        result = await find_similar_pieces(EMBEDDING, pool, tenant_id=TENANT_ID)
        assert result == []

    async def test_embedding_passed_as_pgvector_literal_string_not_raw_list(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        pool = _make_pool(conn)
        await find_similar_pieces(EMBEDDING, pool, tenant_id=TENANT_ID)
        first_param = conn.fetch.call_args[0][1]
        assert isinstance(first_param, str)
        assert first_param.startswith("[") and first_param.endswith("]")
