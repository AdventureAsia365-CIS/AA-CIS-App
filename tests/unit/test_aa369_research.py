"""
tests/unit/test_aa369_research.py — services/acp_produce/research.py (AA-369:
C1/C2 DataForSEO keyword+SERP per SLOT, C3 Brief compile + demand-law reject)
and services/acp_produce/dataforseo.py::fetch_serp_profile() (C2 parser).

No live DataForSEO/Bedrock calls — httpx, DataForSEOClient, and
bedrock_satellite.invoke_claude are mocked. DB mock follows the same
AsyncMock convention as test_aa364_pipeline.py.

Per AA-369 IMPLEMENT scope note (Nghiep): B14 (PAA harvest) is verified
fixed as a side effect of reusing DataForSEOClient.fetch_people_also_ask()
--- but B13 (word_count_range) is deliberately left UNFIXED (belongs to
AA-327) --- test_serp_profile_word_count_range_stays_unset_b13 documents
that gap rather than closing it.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_produce.dataforseo import fetch_serp_profile
from services.acp_produce.models import Brief, KeywordRecord, SERPProfile
from services.acp_produce.research import (build_gap_statement, compile_brief,
                                            fetch_slot_atoms, fetch_slot_demand_data,
                                            log_unknown)
from services.acp_planning.models import Slot
from shared.llm_client.bedrock_satellite import BedrockInvokeResult, BedrockUnavailable

TENANT = "00000000-0000-0000-0000-000000000001"

SERP_RESPONSE_WITH_PAA = {
    "tasks": [{"result": [{"items": [
        {"type": "organic", "url": "https://example.com/a", "domain": "example.com",
         "title": "Best Sapa Trekking Tours & Prices"},
        {"type": "organic", "url": "https://example.com/b", "domain": "rival.com",
         "title": "Sapa Trekking Guide: What to Know"},
        {"type": "people_also_ask", "items": [
            {"title": "Is Sapa trekking safe?"},
            {"title": "What to pack for Sapa trekking?"},
        ]},
        {"type": "related_searches", "items": ["sapa trekking best time", "sapa trekking cost"]},
    ]}]}]
}


def _resp(json_data):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = json_data
    m.raise_for_status = MagicMock()
    return m


def _slot(**overrides) -> Slot:
    defaults = dict(
        slot_id="slot-1", week=1, channel="blog", kind="evergreen",
        atom_ids=["atom_a", "atom_b"], funnel_stage="TOFU", framework=None,
        cta_target="https://aa.example.com/tours/sapa", topic_hint="Sapa trekking",
        keyword_seed="sapa trekking tours",
    )
    defaults.update(overrides)
    return Slot(**defaults)


def _db(atom_rows=None):
    db = AsyncMock()
    db.fetch = AsyncMock(return_value=atom_rows if atom_rows is not None else [
        {"atom_id": "atom_a", "text": "Sapa trek passes 3 ethnic minority villages over 2 days."},
        {"atom_id": "atom_b", "text": "Homestay dinner is cooked by the host family, not a restaurant."},
    ])
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------- C2 SERP profile / B14

@pytest.mark.asyncio
async def test_fetch_serp_profile_harvests_paa_b14():
    client = AsyncMock()
    client.post.return_value = _resp(SERP_RESPONSE_WITH_PAA)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("services.acp_produce.dataforseo.httpx.AsyncClient", return_value=client):
        profile = await fetch_serp_profile("user", "pass", "sapa trekking tours", "US")

    assert profile.confidence == "dfs"
    assert "Is Sapa trekking safe?" in profile.paa_questions
    assert "What to pack for Sapa trekking?" in profile.paa_questions
    assert profile.related_searches == ["sapa trekking best time", "sapa trekking cost"]
    assert set(profile.top10_domains) == {"example.com", "rival.com"}


@pytest.mark.asyncio
async def test_serp_profile_word_count_range_stays_unset_b13():
    """B13 documented, not fixed (AA-327 scope) — real SERP data comes back,
    profile.confidence flips to 'dfs', but word_count_range stays None."""
    client = AsyncMock()
    client.post.return_value = _resp(SERP_RESPONSE_WITH_PAA)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("services.acp_produce.dataforseo.httpx.AsyncClient", return_value=client):
        profile = await fetch_serp_profile("user", "pass", "sapa trekking tours", "US")

    assert profile.confidence == "dfs"
    assert profile.word_count_range is None


@pytest.mark.asyncio
async def test_fetch_serp_profile_offline_degrades_to_heuristic():
    profile = await fetch_serp_profile("", "", "sapa trekking tours", "US")
    assert profile.confidence == "heuristic"
    assert profile.paa_questions == []


@pytest.mark.asyncio
async def test_fetch_serp_profile_api_failure_degrades_not_crashes():
    """Same caught-exception scope as parse_top_pages()/_top_ranking_urls()
    (httpx.HTTPError, KeyError, IndexError, TypeError) — a real network
    failure, not an arbitrary bug, so a bare Exception is not the right
    fixture here."""
    import httpx
    client = AsyncMock()
    client.post.side_effect = httpx.ConnectError("boom")
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("services.acp_produce.dataforseo.httpx.AsyncClient", return_value=client):
        profile = await fetch_serp_profile("user", "pass", "sapa trekking tours", "US")
    assert profile.confidence == "heuristic"


# ---------------------------------------------------------------- C1 keyword demand

@pytest.mark.asyncio
async def test_fetch_slot_demand_data_uses_keyword_seed_not_topic_hint():
    slot = _slot(keyword_seed="sapa trekking tours", topic_hint="something else entirely")
    dfs_client = AsyncMock()
    dfs_client.fetch_keywords = AsyncMock(return_value={
        "top_keywords": ["sapa trekking tours"],
        "search_volumes": {"sapa trekking tours": 1200},
    })
    with patch("services.acp_produce.research.fetch_serp_profile",
               new=AsyncMock(return_value=SERPProfile(keyword="sapa trekking tours", location="US"))):
        demand, serp = await fetch_slot_demand_data(slot, "US", dfs_client=dfs_client)

    assert demand.keyword == "sapa trekking tours"
    assert demand.volume == 1200
    assert demand.confidence == "dfs"
    dfs_client.fetch_keywords.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_slot_demand_data_degrades_to_heuristic_on_failure():
    slot = _slot()
    dfs_client = AsyncMock()
    dfs_client.fetch_keywords = AsyncMock(side_effect=Exception("timeout"))
    with patch("services.acp_produce.research.fetch_serp_profile",
               new=AsyncMock(return_value=SERPProfile(keyword=slot.keyword_seed, location="US"))):
        demand, _ = await fetch_slot_demand_data(slot, "US", dfs_client=dfs_client)

    assert demand.volume is None
    assert demand.confidence == "heuristic"


@pytest.mark.asyncio
async def test_fetch_slot_demand_data_requires_a_seed_keyword():
    slot = _slot(keyword_seed=None, topic_hint=None)
    with pytest.raises(ValueError):
        await fetch_slot_demand_data(slot, "US")


# ---------------------------------------------------------------- atom pack (per SLOT)

@pytest.mark.asyncio
async def test_fetch_slot_atoms_empty_ids_skips_query():
    db = _db()
    atoms = await fetch_slot_atoms([], db)
    assert atoms == []
    db.fetch.assert_not_awaited()


# ---------------------------------------------------------------- C3 demand-law reject

@pytest.mark.asyncio
async def test_compile_brief_demand_law_rejects_no_evidence_and_logs_unknown_ledger():
    db = _db()
    slot = _slot(kind="evergreen")
    demand = KeywordRecord(keyword="obscure phrase", location="US", volume=None, confidence="heuristic")

    brief = await compile_brief(db, TENANT, slot, demand, serp=None)

    assert brief is None
    db.execute.assert_awaited_once()
    args = db.execute.call_args.args
    assert "no_demand_evidence" in args
    assert slot.slot_id in args


@pytest.mark.asyncio
async def test_compile_brief_campaign_kind_bypasses_demand_law():
    db = _db()
    slot = _slot(kind="campaign")
    demand = KeywordRecord(keyword="obscure phrase", location="US", volume=None, confidence="heuristic")

    with patch("services.acp_produce.research.build_gap_statement", return_value=None):
        brief = await compile_brief(db, TENANT, slot, demand, serp=None)

    assert isinstance(brief, Brief)
    assert brief.demand_reason is not None and "campaign" in brief.demand_reason
    db.execute.assert_not_awaited()  # no reject logged — campaign kind is a valid reason


@pytest.mark.asyncio
async def test_compile_brief_no_atoms_rejects():
    db = _db(atom_rows=[])
    slot = _slot()
    demand = KeywordRecord(keyword="sapa trekking tours", location="US", volume=500, confidence="dfs")

    brief = await compile_brief(db, TENANT, slot, demand, serp=None)

    assert brief is None
    db.execute.assert_awaited_once()
    assert "no_atom" in db.execute.call_args.args


@pytest.mark.asyncio
async def test_compile_brief_no_cta_target_rejects():
    db = _db()
    slot = _slot(cta_target=None)
    demand = KeywordRecord(keyword="sapa trekking tours", location="US", volume=500, confidence="dfs")

    brief = await compile_brief(db, TENANT, slot, demand, serp=None)

    assert brief is None
    db.execute.assert_awaited_once()
    assert "no_cta_target" in db.execute.call_args.args


@pytest.mark.asyncio
async def test_compile_brief_unmatched_paa_logged_unanswerable():
    db = _db()
    slot = _slot()
    demand = KeywordRecord(keyword="sapa trekking tours", location="US", volume=500, confidence="dfs")
    serp = SERPProfile(keyword="sapa trekking tours", location="US",
                        paa_questions=["completely unrelated question about penguins"])

    with patch("services.acp_produce.research.build_gap_statement", return_value=None):
        brief = await compile_brief(db, TENANT, slot, demand, serp=serp)

    assert isinstance(brief, Brief)
    assert brief.faq_candidates == []
    assert db.execute.await_count == 1
    assert "unanswerable_paa" in db.execute.call_args.args


@pytest.mark.asyncio
async def test_compile_brief_happy_path_builds_valid_brief():
    db = _db()
    slot = _slot()
    demand = KeywordRecord(keyword="sapa trekking tours", location="US", volume=500, confidence="dfs")
    serp = SERPProfile(keyword="sapa trekking tours", location="US",
                        paa_questions=["Is Sapa trekking safe?"])  # matches atom_a via token overlap

    gap_text = "Competitors cover gear lists we don't."
    with patch("services.acp_produce.research.build_gap_statement", return_value=gap_text) as mock_gap:
        brief = await compile_brief(db, TENANT, slot, demand, serp=serp, top_pages=[{"content": "x"}])

    assert isinstance(brief, Brief)
    assert brief.keyword == "sapa trekking tours"
    assert brief.framework == "hub"  # TOFU/blog -> FRAMEWORK_TABLE
    assert brief.word_range == (900, 1400)  # B13 not fixed -> default
    assert brief.cta_target == slot.cta_target
    assert brief.atoms_by_section  # every atom assigned to a section
    assert brief.gap_statement == gap_text
    db.execute.assert_not_awaited()  # nothing rejected on the happy path
    mock_gap.assert_called_once()


# ---------------------------------------------------------------- gap_statement (Haiku satellite)

def test_build_gap_statement_no_top_pages_returns_none():
    assert build_gap_statement([], [{"atom_id": "a", "text": "x"}], "kw") is None


def test_build_gap_statement_top_pages_with_no_content_returns_none():
    assert build_gap_statement([{"url": "x"}], [{"atom_id": "a", "text": "y"}], "kw") is None


def test_build_gap_statement_happy_path_calls_haiku():
    top_pages = [{"crawled_url": "https://example.com/", "content": "Gear checklist: boots, poncho, headlamp."}]
    atoms = [{"atom_id": "atom_a", "text": "Trek passes 3 villages."}]

    with patch("services.acp_produce.research.invoke_claude") as mock_invoke:
        mock_invoke.return_value = BedrockInvokeResult(
            text="Competitors include a packing/gear checklist our atoms don't cover.",
            model_used="haiku-4-5", latency_ms=120.0, usage={},
        )
        result = build_gap_statement(top_pages, atoms, "sapa trekking tours")

    assert result == "Competitors include a packing/gear checklist our atoms don't cover."
    call_kwargs = mock_invoke.call_args.kwargs
    assert call_kwargs["model"] == "haiku"


def test_build_gap_statement_degrades_to_none_on_bedrock_unavailable():
    top_pages = [{"crawled_url": "https://example.com/", "content": "some content"}]
    atoms = [{"atom_id": "atom_a", "text": "Trek passes 3 villages."}]

    with patch("services.acp_produce.research.invoke_claude", side_effect=BedrockUnavailable("throttled")):
        result = build_gap_statement(top_pages, atoms, "sapa trekking tours")

    assert result is None


# ---------------------------------------------------------------- unknown_ledger write shape

@pytest.mark.asyncio
async def test_log_unknown_upserts_with_dedup_columns():
    db = _db()
    await log_unknown(db, TENANT, "no_demand_evidence", "detail text", slot_id="slot-1", keyword="kw")

    db.execute.assert_awaited_once()
    sql = db.execute.call_args.args[0]
    assert "ON CONFLICT (tenant_id, kind, detail)" in sql
    assert "acp_shared.unknown_ledger" in sql
