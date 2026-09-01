"""AA-508 — atom_id content-hash + per-day fingerprint-skip + real UPSERT.

STEP0 (docs/claude_audit/AA-508-step0-atom-identity-investigation.md) found run_t5_atomize()
atomized a whole tenant tour version in ONE LLM call, keyed to skip-or-not by ONE source_hash over
the whole itinerary — a single day's edit re-atomized (and re-randomized every atom_id of) the
entire tour. STEP0b cross-checked the reference repo (aa-social-media) directly: content-hash
atom_id + a real ON CONFLICT UPSERT, gated per DAY by a fingerprint that BLOCKS the LLM call
(not just logged after one).

Drives the real coroutine (services.acp_produce.tenant_pipeline.run_t5_atomize), same mocking
shape as test_aa445_t5_distinctiveness.py (pool.acquire() fake, invoke_claude patched at its
import site) — `itineraries` here is in the canonical "Day N — Title\\nBody" format (T4 reuses
T2's engine, graph.py's generate_node/_process_itineraries, which always emits this) so these
tests exercise _atomize_per_day(), not the legacy whole-tour fallback
(test_aa445_t5_distinctiveness.py's empty-string `itineraries` already covers that path and is
untouched by this change).
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_produce import tenant_pipeline
from services.acp_shared.atom_extraction import content_hash_atom_id, day_fingerprint, normalise
from services.acp_shared.competitor_index import CompetitorIndex

TENANT_ID = "33333333-3333-3333-3333-333333333333"
TOUR_ID = "44444444-4444-4444-4444-444444444444"
VERSION_ID = "77777777-7777-7777-7777-777777777777"

TWO_DAY_ITINERARY = (
    "Day 1 — Arrival in Hanoi\n"
    "Walk through the Old Quarter and try street food.\n\n"
    "Day 2 — Halong Bay Cruise\n"
    "Board a traditional junk boat and kayak through limestone caves."
)


def _pool_ctx(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _fake_conn(existing_fingerprints=None):
    """`existing_fingerprints`: list of {"day_number":..., "fingerprint_hash":...} rows
    returned by the ONE `SELECT ... FROM acp_contract.atomize_day_fingerprint` fetch()."""
    conn = AsyncMock()
    conn.fetch.return_value = existing_fingerprints or []
    return conn


class _FakeLLMResult:
    def __init__(self, text):
        self.text = text


def _day1_atoms_json(text="Walk through the Old Quarter"):
    return json.dumps({"atoms": [{"text": text, "activity_type": "culture"}]})


def _day2_atoms_json(text="Kayak through limestone caves at Halong Bay"):
    return json.dumps({"atoms": [{"text": text, "activity_type": "trek"}]})


@pytest.mark.asyncio
async def test_first_atomize_reads_every_day_content_hash_ids():
    """N days, first run: no fingerprint rows exist yet, so both days are read; every atom_id
    matches content_hash_atom_id(tour_id, tenant_id, day_number, text) exactly — the real
    formula, not a random UUID."""
    conn = _fake_conn(existing_fingerprints=[])
    pool = _pool_ctx(conn)

    day1_text = "Walk through the Old Quarter"
    day2_text = "Kayak through limestone caves at Halong Bay"

    with patch("services.acp_produce.tenant_pipeline.invoke_claude",
               side_effect=[_FakeLLMResult(_day1_atoms_json(day1_text)),
                            _FakeLLMResult(_day2_atoms_json(day2_text))]), \
         patch("services.acp_shared.competitor_index.build_competitor_index",
               new=AsyncMock(return_value=CompetitorIndex())):
        result = await tenant_pipeline.run_t5_atomize(
            TENANT_ID, TOUR_ID,
            {"name": "Sapa Trek", "summary": "s", "highlights": [], "itineraries": TWO_DAY_ITINERARY},
            pool, country="Vietnam", version_id=VERSION_ID,
        )

    assert result["status"] == "success"
    assert result["atom_count"] == 2
    assert result["days_total"] == 2
    assert result["days_read"] == 2
    assert result["days_skipped"] == 0

    insert_calls = [c for c in conn.execute.call_args_list
                     if "INSERT INTO acp_contract.tour_atoms" in c.args[0]]
    assert len(insert_calls) == 2

    expected_id_day1 = content_hash_atom_id(TOUR_ID, TENANT_ID, 1, day1_text)
    expected_id_day2 = content_hash_atom_id(TOUR_ID, TENANT_ID, 2, day2_text)
    actual_ids = {c.args[1] for c in insert_calls}  # atom_id is the 1st bind param ($1)
    assert actual_ids == {expected_id_day1, expected_id_day2}

    # ON CONFLICT UPSERT, not a plain INSERT
    assert all("ON CONFLICT (atom_id) DO UPDATE" in c.args[0] for c in insert_calls)

    # itinerary_day bound correctly per day (14th positional param, index 13)
    itinerary_days = {c.args[14] for c in insert_calls}
    assert itinerary_days == {1, 2}

    # fingerprint rows written for both days
    fp_calls = [c for c in conn.execute.call_args_list
                 if "INSERT INTO acp_contract.atomize_day_fingerprint" in c.args[0]]
    assert len(fp_calls) == 2
    fp_versions = {c.args[1] for c in fp_calls}
    assert fp_versions == {VERSION_ID}


@pytest.mark.asyncio
async def test_rerun_unchanged_skips_every_day_zero_llm_calls():
    """Re-atomizing with identical days (fingerprints already on file) reads nothing — zero
    invoke_claude() calls, atom_count=0, status='skipped'."""
    day1_text = "Walk through the Old Quarter"
    day2_text = "Kayak through limestone caves at Halong Bay"
    fp1 = day_fingerprint("Arrival in Hanoi",
                           "Walk through the Old Quarter and try street food.",
                           tenant_pipeline._T5_MODEL_TIER)
    fp2 = day_fingerprint("Halong Bay Cruise",
                           "Board a traditional junk boat and kayak through limestone caves.",
                           tenant_pipeline._T5_MODEL_TIER)
    conn = _fake_conn(existing_fingerprints=[
        {"day_number": 1, "fingerprint_hash": fp1},
        {"day_number": 2, "fingerprint_hash": fp2},
    ])
    pool = _pool_ctx(conn)

    with patch("services.acp_produce.tenant_pipeline.invoke_claude") as m_llm:
        result = await tenant_pipeline.run_t5_atomize(
            TENANT_ID, TOUR_ID,
            {"name": "Sapa Trek", "summary": "s", "highlights": [], "itineraries": TWO_DAY_ITINERARY},
            pool, country="Vietnam", version_id=VERSION_ID,
        )

    m_llm.assert_not_called()
    assert result == {
        "status": "skipped", "atom_count": 0,
        "days_total": 2, "days_read": 0, "days_skipped": 2,
    }
    # No atom/fingerprint writes at all when every day is skipped
    assert not any("INSERT INTO acp_contract.tour_atoms" in c.args[0]
                   for c in conn.execute.call_args_list)
    assert not any("acp_contract.atomize_day_fingerprint" in c.args[0]
                   for c in conn.execute.call_args_list)
    assert day1_text and day2_text  # sample text kept for readability, unused otherwise


@pytest.mark.asyncio
async def test_one_day_changed_only_that_day_reatomizes_other_kept():
    """Day 1's fingerprint is stale (content changed); Day 2's still matches. Only Day 1 calls
    the LLM and gets a new content-hash atom_id; Day 2 is never touched — no INSERT, no
    fingerprint re-write, no invoke_claude() call for it."""
    fp2_current = day_fingerprint("Halong Bay Cruise",
                                   "Board a traditional junk boat and kayak through limestone caves.",
                                   tenant_pipeline._T5_MODEL_TIER)
    conn = _fake_conn(existing_fingerprints=[
        {"day_number": 1, "fingerprint_hash": "stale-hash-from-a-prior-different-day-1-wording"},
        {"day_number": 2, "fingerprint_hash": fp2_current},
    ])
    pool = _pool_ctx(conn)

    new_day1_text = "Visit the reconstructed Old Quarter market at dawn"

    with patch("services.acp_produce.tenant_pipeline.invoke_claude",
               return_value=_FakeLLMResult(_day1_atoms_json(new_day1_text))) as m_llm, \
         patch("services.acp_shared.competitor_index.build_competitor_index",
               new=AsyncMock(return_value=CompetitorIndex())):
        result = await tenant_pipeline.run_t5_atomize(
            TENANT_ID, TOUR_ID,
            {"name": "Sapa Trek", "summary": "s", "highlights": [], "itineraries": TWO_DAY_ITINERARY},
            pool, country="Vietnam", version_id=VERSION_ID,
        )

    m_llm.assert_called_once()  # exactly 1 day re-read, not 2
    assert result["status"] == "success"
    assert result["days_read"] == 1
    assert result["days_skipped"] == 1

    insert_calls = [c for c in conn.execute.call_args_list
                     if "INSERT INTO acp_contract.tour_atoms" in c.args[0]]
    assert len(insert_calls) == 1
    assert insert_calls[0].args[14] == 1  # itinerary_day
    assert insert_calls[0].args[1] == content_hash_atom_id(TOUR_ID, TENANT_ID, 1, new_day1_text)

    fp_calls = [c for c in conn.execute.call_args_list
                 if "INSERT INTO acp_contract.atomize_day_fingerprint" in c.args[0]]
    assert len(fp_calls) == 1
    assert fp_calls[0].args[2] == 1  # day_number


@pytest.mark.asyncio
async def test_llm_failure_on_one_day_keeps_other_days_committed():
    """Day 1 fails (LLM raises); Day 2 succeeds. Prior days' work is not rolled back —
    result reports 'failed' overall (so the tenant/A4 sees it) but atom_count/fingerprint for
    Day 2 are still real, committed writes, and Day 1's failure is named specifically."""
    conn = _fake_conn(existing_fingerprints=[])
    pool = _pool_ctx(conn)

    with patch("services.acp_produce.tenant_pipeline.invoke_claude",
               side_effect=[RuntimeError("BedrockError: throttled"),
                            _FakeLLMResult(_day2_atoms_json())]), \
         patch("services.acp_shared.competitor_index.build_competitor_index",
               new=AsyncMock(return_value=CompetitorIndex())):
        result = await tenant_pipeline.run_t5_atomize(
            TENANT_ID, TOUR_ID,
            {"name": "Sapa Trek", "summary": "s", "highlights": [], "itineraries": TWO_DAY_ITINERARY},
            pool, country="Vietnam", version_id=VERSION_ID,
        )

    assert result["status"] == "failed"
    assert result["days_failed"] == [1]
    assert result["days_read"] == 1
    assert result["atom_count"] == 1

    insert_calls = [c for c in conn.execute.call_args_list
                     if "INSERT INTO acp_contract.tour_atoms" in c.args[0]]
    assert len(insert_calls) == 1
    assert insert_calls[0].args[14] == 2  # only Day 2 got written

    fp_calls = [c for c in conn.execute.call_args_list
                 if "INSERT INTO acp_contract.atomize_day_fingerprint" in c.args[0]]
    assert len(fp_calls) == 1
    assert fp_calls[0].args[2] == 2  # Day 1 has no fingerprint row -> retried next call


@pytest.mark.asyncio
async def test_zero_atom_day_writes_deterministic_marker_not_random():
    """A day the model reads as truly empty still gets a marker row, but the marker's atom_id
    is content-hash-deterministic (tour_id, owner_scope, day, '__empty__'), not
    uuid4()-random — so a repeat empty-day read UPSERTs the same marker instead of piling up a
    new random one every time it's forced to re-run."""
    conn = _fake_conn(existing_fingerprints=[])
    pool = _pool_ctx(conn)

    with patch("services.acp_produce.tenant_pipeline.invoke_claude",
               side_effect=[_FakeLLMResult(json.dumps({"atoms": []})),
                            _FakeLLMResult(_day2_atoms_json())]), \
         patch("services.acp_shared.competitor_index.build_competitor_index",
               new=AsyncMock(return_value=CompetitorIndex())):
        result = await tenant_pipeline.run_t5_atomize(
            TENANT_ID, TOUR_ID,
            {"name": "Sapa Trek", "summary": "s", "highlights": [], "itineraries": TWO_DAY_ITINERARY},
            pool, country="Vietnam", version_id=VERSION_ID,
        )

    assert result["status"] == "success"
    marker_calls = [c for c in conn.execute.call_args_list
                     if "INSERT INTO acp_contract.tour_atoms" in c.args[0]
                     and "is_empty_marker" in c.args[0]]
    assert len(marker_calls) == 1
    expected_marker_id = content_hash_atom_id(TOUR_ID, TENANT_ID, 1, "__empty__")
    assert marker_calls[0].args[1] == expected_marker_id


def test_content_hash_atom_id_stable_and_tenant_scoped():
    """Same (tour_id, tenant, day, text) -> same id across calls (re-run stability); a
    different tenant on the same tour/day/text -> a different id (no cross-tenant PK collision
    on tour_atoms' single global atom_id primary key)."""
    id_a = content_hash_atom_id(TOUR_ID, TENANT_ID, 3, "Cross the historic bamboo bridge at dawn")
    id_b = content_hash_atom_id(TOUR_ID, TENANT_ID, 3, "Cross the historic bamboo bridge at dawn")
    assert id_a == id_b

    other_tenant = "99999999-9999-9999-9999-999999999999"
    id_c = content_hash_atom_id(TOUR_ID, other_tenant, 3, "Cross the historic bamboo bridge at dawn")
    assert id_c != id_a

    # normalise() is what absorbs cosmetic wording differences (case/punctuation), not the
    # hash itself skipping normalisation
    id_d = content_hash_atom_id(TOUR_ID, TENANT_ID, 3, "CROSS the Historic Bamboo-Bridge at dawn!!")
    assert id_d == id_a


def test_normalise_matches_reference_repo_formula():
    assert normalise("CROSS the Historic Bamboo-Bridge at dawn!!") == "cross the historic bamboo bridge at dawn"
    assert normalise("") == ""
    assert normalise(None) == ""
