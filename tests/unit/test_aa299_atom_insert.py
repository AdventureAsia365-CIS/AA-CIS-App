"""AA-299 — _decompose_inline() atom insert + source_hash idempotency (inline <100-tour path only).

Drives the REAL coroutine (api.routers.v1_atoms._decompose_inline), not a
re-implemented copy. No live DB / no Bedrock: asyncpg is mocked via the same
pool.acquire() context-manager shape used in test_aa242_regenerate_supersede.py;
invoke_claude is patched at api.routers.v1_atoms.invoke_claude (module-level
import site, per unittest.mock convention).

Idempotency is keyed on (tour_id, source_hash) since migration 084 — conn.fetchval
stands in for "SELECT source_hash FROM tour_atoms WHERE tour_id=... ORDER BY
created_at DESC LIMIT 1", so its return_value IS the DB's most-recent source_hash
for that tour (None = no prior atoms, or none re: recorded before migration 084).
"""
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.routers import v1_atoms

TOUR_ID = "11111111-1111-1111-1111-111111111111"


def _make_pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _fake_conn(latest_source_hash=None):
    conn = AsyncMock()
    conn.fetchval.return_value = latest_source_hash
    return conn


def _row(**over):
    base = {
        "id": TOUR_ID,
        "name": "Sapa Trek",
        "aa_summary": "A trek through Sapa.",
        "aa_highlights": ["Crossing the bamboo bridge at Ta Van village"],
        "itinerary_source": "Day 1: cross the bamboo bridge at Ta Van village before breakfast.",
        "inclusions": None,
        "exclusions": None,
    }
    base.update(over)
    return base


def _fake_llm_result(atoms):
    result = MagicMock()
    result.text = json.dumps({"atoms": atoms})
    return result


ONE_ATOM = [{
    "text": "Crossing the bamboo bridge at Ta Van village before breakfast",
    "activity_type": "trek",
    "emotional_hook": "quiet awe",
    "visual_potential": 3,
    "persona_fit": ["adventurer"],
    "season_note": "dry season only",
}]


def _insert_calls(conn):
    return [c for c in conn.execute.call_args_list if "INSERT INTO acp_contract.tour_atoms" in c.args[0]]


# ── insert maps fields correctly (incl. source_hash), atom_id format ───────

@pytest.mark.asyncio
async def test_decompose_inline_inserts_atom_with_correct_fields():
    row = _row()
    expected_hash = v1_atoms._source_hash(row)
    conn = _fake_conn(latest_source_hash=None)  # no prior atoms for this tour
    pool = _make_pool(conn)

    with patch("api.routers.v1_atoms.invoke_claude", return_value=_fake_llm_result(ONE_ATOM)):
        result = await v1_atoms._decompose_inline([row], pool)

    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert result["skipped"] == 0
    assert result["atoms_created"] == 1

    insert_calls = _insert_calls(conn)
    assert len(insert_calls) == 1

    sql, atom_id, tour_id, owner_scope, text, activity_type, emotional_hook, \
        visual_potential, persona_fit, season_note, starred, deleted, weight, \
        source_hash = insert_calls[0].args

    assert re.match(r"^atom_[0-9a-f]{10}$", atom_id)
    assert tour_id == TOUR_ID
    assert owner_scope == "platform"
    assert text == ONE_ATOM[0]["text"]
    assert activity_type == "trek"
    assert emotional_hook == "quiet awe"
    assert visual_potential == 3
    assert json.loads(persona_fit) == ["adventurer"]
    assert season_note == "dry season only"
    assert starred is False
    assert deleted is False
    assert weight == 1.0
    assert source_hash == expected_hash

    # distinctiveness/media/usage_log/cooldown_until/human_seam_notes must NOT
    # be set explicitly — they stay at migration-079 DB defaults.
    assert "distinctiveness" not in sql
    assert "media" not in sql


@pytest.mark.asyncio
async def test_decompose_inline_thin_trip_flag():
    """< THIN_TRIP_ATOM_MIN (5) atoms ⇒ thin_trip: true, no blocking."""
    conn = _fake_conn(latest_source_hash=None)
    pool = _make_pool(conn)

    with patch("api.routers.v1_atoms.invoke_claude", return_value=_fake_llm_result(ONE_ATOM)):
        result = await v1_atoms._decompose_inline([_row()], pool)

    assert result["succeeded"] == 1
    assert result["status"] == "completed"  # never auto-blocked


# ── (b) source_hash giống ⇒ skip đúng ───────────────────────────────────────

@pytest.mark.asyncio
async def test_decompose_inline_skips_tour_with_matching_source_hash():
    row = _row()
    same_hash = v1_atoms._source_hash(row)
    conn = _fake_conn(latest_source_hash=same_hash)  # most recent atom row has the SAME hash
    pool = _make_pool(conn)

    with patch("api.routers.v1_atoms.invoke_claude") as mock_invoke:
        result = await v1_atoms._decompose_inline([row], pool)

    mock_invoke.assert_not_called()
    assert result["skipped"] == 1
    assert result["succeeded"] == 0
    assert result["skipped_tours"] == [{"tour_id": TOUR_ID, "reason": "source unchanged (hash match)"}]
    assert len(_insert_calls(conn)) == 0


# ── (a) source_hash đổi ⇒ KHÔNG skip, decompose lại ─────────────────────────

@pytest.mark.asyncio
async def test_decompose_inline_reruns_when_source_hash_differs():
    row = _row(itinerary_source="Day 1: NEW itinerary text, source has changed.")
    stale_hash = "0" * 64  # simulates a prior decompose of the OLD source text
    assert stale_hash != v1_atoms._source_hash(row)
    conn = _fake_conn(latest_source_hash=stale_hash)
    pool = _make_pool(conn)

    with patch("api.routers.v1_atoms.invoke_claude", return_value=_fake_llm_result(ONE_ATOM)) as mock_invoke:
        result = await v1_atoms._decompose_inline([row], pool)

    mock_invoke.assert_called_once()
    assert result["succeeded"] == 1
    assert result["skipped"] == 0
    assert len(_insert_calls(conn)) == 1


@pytest.mark.asyncio
async def test_decompose_inline_reruns_when_no_prior_hash_recorded():
    """Legacy row with source_hash IS NULL (pre-migration-084) must never false-skip."""
    row = _row()
    conn = _fake_conn(latest_source_hash=None)
    pool = _make_pool(conn)

    with patch("api.routers.v1_atoms.invoke_claude", return_value=_fake_llm_result(ONE_ATOM)) as mock_invoke:
        result = await v1_atoms._decompose_inline([row], pool)

    mock_invoke.assert_called_once()
    assert result["succeeded"] == 1
    assert result["skipped"] == 0


@pytest.mark.asyncio
async def test_decompose_inline_second_call_same_source_is_noop():
    """Calling decompose twice with the SAME source: 1st inserts, 2nd skips, no duplicate."""
    row = _row()
    conn_first = _fake_conn(latest_source_hash=None)
    pool_first = _make_pool(conn_first)
    with patch("api.routers.v1_atoms.invoke_claude", return_value=_fake_llm_result(ONE_ATOM)):
        first = await v1_atoms._decompose_inline([row], pool_first)
    assert first["succeeded"] == 1

    # Second call: DB now reports the tour's latest atom row has this exact
    # source_hash (as the first call would have written), so the idempotency
    # check must skip it.
    conn_second = _fake_conn(latest_source_hash=v1_atoms._source_hash(row))
    pool_second = _make_pool(conn_second)
    with patch("api.routers.v1_atoms.invoke_claude") as mock_invoke_second:
        second = await v1_atoms._decompose_inline([row], pool_second)

    mock_invoke_second.assert_not_called()
    assert second["skipped"] == 1
    assert second["succeeded"] == 0
    assert len(_insert_calls(conn_second)) == 0


# ── (c) toàn bộ batch skip ⇒ status KHÔNG phải "failed" ─────────────────────

@pytest.mark.asyncio
async def test_decompose_inline_all_skipped_status_not_failed():
    row = _row()
    same_hash = v1_atoms._source_hash(row)
    conn = _fake_conn(latest_source_hash=same_hash)
    pool = _make_pool(conn)

    with patch("api.routers.v1_atoms.invoke_claude") as mock_invoke:
        result = await v1_atoms._decompose_inline([row], pool)

    mock_invoke.assert_not_called()
    assert result["skipped"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["status"] == "completed"
    assert result["status"] != "failed"


@pytest.mark.asyncio
async def test_decompose_inline_all_real_failures_status_failed():
    """Boundary check: status is 'failed' ONLY when every tour failed for real (no skips)."""
    conn = _fake_conn(latest_source_hash=None)
    pool = _make_pool(conn)

    with patch("api.routers.v1_atoms.invoke_claude", side_effect=RuntimeError("boom")):
        result = await v1_atoms._decompose_inline([_row()], pool)

    assert result["failed"] == 1
    assert result["succeeded"] == 0
    assert result["skipped"] == 0
    assert result["status"] == "failed"


# ── (d) zero-atom result ⇒ marker row written (migration 085) ──────────────

@pytest.mark.asyncio
async def test_decompose_inline_zero_atoms_writes_marker_row():
    """A genuine never-pad empty result must still leave a source_hash-bearing
    row behind, or the next call's idempotency check has nothing to compare
    against (AA-299, live-observed gap: Yaksa Trek call #1 -> 0 atoms, call #2
    re-ran Bedrock instead of skipping)."""
    row = _row()
    expected_hash = v1_atoms._source_hash(row)
    conn = _fake_conn(latest_source_hash=None)
    pool = _make_pool(conn)

    with patch("api.routers.v1_atoms.invoke_claude", return_value=_fake_llm_result([])):
        result = await v1_atoms._decompose_inline([row], pool)

    assert result["succeeded"] == 1
    assert result["atoms_created"] == 0

    insert_calls = _insert_calls(conn)
    assert len(insert_calls) == 1

    sql, marker_id, tour_id, owner_scope, text, starred, deleted, \
        is_empty_marker, weight, source_hash = insert_calls[0].args

    assert re.match(r"^atom_marker_[0-9a-f]{10}$", marker_id)
    assert tour_id == TOUR_ID
    assert owner_scope == "platform"
    assert starred is False
    # deleted stays False on purpose: `deleted` means "a real atom existed and
    # was removed" (audit/GDPR/veto-stats meaning) -- a marker row was never a
    # real atom in the first place, a distinct fact is_empty_marker captures.
    assert deleted is False
    assert is_empty_marker is True
    assert weight == 1.0
    assert source_hash == expected_hash


@pytest.mark.asyncio
async def test_decompose_inline_skips_after_prior_zero_atom_marker():
    """A prior zero-atom marker row's source_hash must be honored by the
    idempotency check the same as a real atom row's would be -- no re-run,
    no re-invoking Bedrock, when the source is unchanged."""
    row = _row()
    marker_hash = v1_atoms._source_hash(row)
    conn = _fake_conn(latest_source_hash=marker_hash)  # marker row IS the "latest" row
    pool = _make_pool(conn)

    with patch("api.routers.v1_atoms.invoke_claude") as mock_invoke:
        result = await v1_atoms._decompose_inline([row], pool)

    mock_invoke.assert_not_called()
    assert result["skipped"] == 1
    assert result["succeeded"] == 0
    assert result["skipped_tours"] == [{"tour_id": TOUR_ID, "reason": "source unchanged (hash match)"}]
    assert len(_insert_calls(conn)) == 0


@pytest.mark.asyncio
async def test_decompose_pending_tours_query_excludes_empty_markers():
    """The pending-tours auto-sweep (POST /v1/atoms/decompose with no tour_ids)
    must not treat a zero-atom marker row as "this tour already has a real
    atom" -- otherwise a thin tour that only ever produced a marker would
    silently vanish from the sweep forever, despite having zero real,
    displayable atoms. Asserts on the actual SQL string sent to conn.fetch."""
    conn = AsyncMock()
    conn.fetch.return_value = []  # short-circuits decompose() to the early return

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)

    request = MagicMock()
    request.app.state.pool = pool

    body = v1_atoms.DecomposeRequest(tour_ids=None)
    result = await v1_atoms.decompose(body, request, tenant={"sub": "test", "role": "admin"})

    assert result == {"message": "no tours pending decompose", "tour_count": 0}

    pending_query_calls = [c for c in conn.fetch.call_args_list if "v_trip_registry" in c.args[0]]
    assert len(pending_query_calls) == 1
    query_sql = pending_query_calls[0].args[0]
    assert "AND NOT ta.deleted AND NOT ta.is_empty_marker" in query_sql
