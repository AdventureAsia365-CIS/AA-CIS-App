"""AA-445-02 — run_t5_atomize() now computes+persists real `distinctiveness` per atom,
instead of leaving every T5 (owner_scope=tenant_id) atom at the migration-079 default.

Drives the real coroutine (services.acp_produce.tenant_pipeline.run_t5_atomize), not a
re-implemented copy — same mocking shape as test_aa299_atom_insert.py (pool.acquire() context
manager, invoke_claude patched at its import site). build_competitor_index() is patched to
return a known CompetitorIndex so the test asserts on score_distinctiveness()'s real output,
not on network/DB behavior already covered by test_aa445_competitor_index.py.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_produce import tenant_pipeline
from services.acp_shared.competitor_index import CompetitorIndex

TENANT_ID = "33333333-3333-3333-3333-333333333333"
TOUR_ID = "44444444-4444-4444-4444-444444444444"


def _pool_ctx(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _fake_conn(latest_source_hash=None):
    conn = AsyncMock()
    conn.fetchval.return_value = latest_source_hash  # idempotency hash lookup: no prior atoms
    return conn


class _FakeLLMResult:
    def __init__(self, text):
        self.text = text


@pytest.mark.asyncio
async def test_distinctiveness_column_included_and_scored_per_atom():
    """Two atoms, one with heavy competitor overlap (-> LOW) and one with none (-> HIGH) —
    asserts the actual INSERT carries score_distinctiveness()'s real per-atom output, not a
    flat/hardcoded value."""
    conn = _fake_conn()
    pool = _pool_ctx(conn)

    atoms_json = json.dumps({"atoms": [
        {"place": "the historic bamboo bridge", "action": "cross at dawn before breakfast",
         "activity_type": "trek"},
        {"place": "remote limestone caves", "action": "private overnight kayak expedition through",
         "activity_type": "other"},
    ]})
    competitor_idx = CompetitorIndex(phrases=[
        "Cross the historic bamboo bridge at dawn before breakfast in the village",
    ])

    with patch("services.acp_produce.tenant_pipeline.invoke_claude",
               return_value=_FakeLLMResult(atoms_json)), \
         patch("services.acp_shared.competitor_index.build_competitor_index",
               new=AsyncMock(return_value=competitor_idx)):
        result = await tenant_pipeline.run_t5_atomize(
            TENANT_ID, TOUR_ID, {"name": "Sapa Trek", "summary": "s", "highlights": [], "itineraries": ""},
            pool, country="Vietnam",
        )

    assert result["status"] == "success"
    assert result["atom_count"] == 2

    insert_calls = [c for c in conn.execute.call_args_list if "INSERT INTO acp_contract.tour_atoms" in c.args[0]]
    assert len(insert_calls) == 2

    # column list order: ..., source_hash, itinerary_day, distinctiveness, created_at, updated_at
    first_sql, *first_params = insert_calls[0].args
    second_sql, *second_params = insert_calls[1].args
    assert "distinctiveness" in first_sql

    # last positional bind param before now()/now() is distinctiveness (14th param, index -1)
    first_distinctiveness = first_params[-1]
    second_distinctiveness = second_params[-1]
    assert first_distinctiveness == "LOW"    # near-verbatim overlap with the competitor phrase
    assert second_distinctiveness == "HIGH"  # zero overlap — genuinely distinctive


@pytest.mark.asyncio
async def test_no_country_yields_empty_index_not_an_error():
    """An empty/unresolvable country must not crash T5 — build_competitor_index() itself
    already handles this (empty domains -> empty index -> score_distinctiveness() -> MED)."""
    conn = _fake_conn()
    pool = _pool_ctx(conn)
    atoms_json = json.dumps({"atoms": [{"place": "the tour itself", "action": "some real atom moment"}]})

    with patch("services.acp_produce.tenant_pipeline.invoke_claude",
               return_value=_FakeLLMResult(atoms_json)), \
         patch("services.acp_shared.competitor_index.build_competitor_index",
               new=AsyncMock(return_value=CompetitorIndex())) as mock_build:
        result = await tenant_pipeline.run_t5_atomize(
            TENANT_ID, TOUR_ID, {"name": "T", "summary": "s", "highlights": [], "itineraries": ""},
            pool, country="",
        )

    assert result["status"] == "success"
    mock_build.assert_awaited_once_with(TENANT_ID, "", pool)
