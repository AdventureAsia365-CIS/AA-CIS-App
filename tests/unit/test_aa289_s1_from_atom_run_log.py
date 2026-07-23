"""AA-289 — v1_s1_from_atom router's run-log write (acp_contract.s1_from_atom_runs).

Drives the real generate() endpoint coroutine with a mocked pool (same shape as
test_s1_router.py) and generate_s1_from_atom patched at the router's import site,
so this tests the router's _log_run wiring specifically — the generation logic
itself is already covered by test_aa306_s1_from_atom.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.content_generation.s1_from_atom import GroundingError

TOUR_ID = "11111111-1111-1111-1111-111111111111"


def _make_pool():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"tour_id": TOUR_ID, "src_name": "Delhi Tour", "country": "India"})
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


def _make_request(pool):
    req = MagicMock()
    req.app.state.pool = pool
    return req


def _insert_calls(conn):
    return [c for c in conn.execute.call_args_list if "INSERT INTO acp_contract.s1_from_atom_runs" in c.args[0]]


@pytest.mark.asyncio
async def test_generate_logs_passed_row_on_success():
    from api.routers.v1_s1_from_atom import generate

    pool, conn = _make_pool()
    fake_result = {
        "content": {"aa_summary": "grounded text"},
        "atoms_used": ["atom_aaaaaaaaaa"],
        "atoms_available": 5,
        "gate": {"citation_count": 3, "word_count": 90, "words_per_citation": 30.0,
                  "density_pass": True, "closed_world_pass": True},
        "retries": 0,
        "model_used": "us.writer.palmyra-x5-v1:0",
        "input_tokens": 100,
        "output_tokens": 50,
        "prompt_version": "abcd1234",
    }

    with patch("api.routers.v1_s1_from_atom.generate_s1_from_atom", AsyncMock(return_value=fake_result)):
        await generate(TOUR_ID, _make_request(pool), model_tier="palmyra", tenant={})

    calls = _insert_calls(conn)
    assert len(calls) == 1
    args = calls[0].args
    # (query, tour_id, prompt_version, model_tier, model_used, status, ...)
    assert args[1] == TOUR_ID
    assert args[2] == "abcd1234"
    assert args[3] == "palmyra"
    assert args[5] == "passed"


@pytest.mark.asyncio
async def test_generate_logs_gate_failed_row_when_grounding_error_has_prompt_version():
    from api.routers.v1_s1_from_atom import generate
    from fastapi import HTTPException

    pool, conn = _make_pool()
    err = GroundingError("gate failed after retries", prompt_version="deadbeef",
                          gate={"density_pass": False, "closed_world_pass": True}, retries=2)

    with patch("api.routers.v1_s1_from_atom.generate_s1_from_atom", AsyncMock(side_effect=err)):
        with pytest.raises(HTTPException) as exc_info:
            await generate(TOUR_ID, _make_request(pool), model_tier="palmyra", tenant={})

    assert exc_info.value.status_code == 502
    calls = _insert_calls(conn)
    assert len(calls) == 1
    args = calls[0].args
    assert args[2] == "deadbeef"
    assert args[5] == "gate_failed"


@pytest.mark.asyncio
async def test_generate_skips_log_when_no_curated_atoms():
    """GroundingError.prompt_version is None for the "no curated atoms" case (raised before
    any system prompt is built) — _log_run must skip the INSERT entirely, not write a row
    with an empty/garbage prompt_version."""
    from api.routers.v1_s1_from_atom import generate
    from fastapi import HTTPException

    pool, conn = _make_pool()
    err = GroundingError(f"No curated atoms for tour {TOUR_ID} — nothing to assemble from")

    with patch("api.routers.v1_s1_from_atom.generate_s1_from_atom", AsyncMock(side_effect=err)):
        with pytest.raises(HTTPException) as exc_info:
            await generate(TOUR_ID, _make_request(pool), model_tier="palmyra", tenant={})

    assert exc_info.value.status_code == 422
    assert _insert_calls(conn) == []


@pytest.mark.asyncio
async def test_generate_log_failure_does_not_break_the_response():
    """A DB error while writing the observability row must not turn a successful
    generation into a 500 for the caller."""
    from api.routers.v1_s1_from_atom import generate

    pool, conn = _make_pool()
    conn.execute = AsyncMock(side_effect=RuntimeError("db write failed"))
    fake_result = {
        "content": {"aa_summary": "grounded text"},
        "atoms_used": ["atom_aaaaaaaaaa"],
        "atoms_available": 5,
        "gate": {"citation_count": 3, "word_count": 90, "words_per_citation": 30.0,
                  "density_pass": True, "closed_world_pass": True},
        "retries": 0,
        "model_used": "us.writer.palmyra-x5-v1:0",
        "input_tokens": 100,
        "output_tokens": 50,
        "prompt_version": "abcd1234",
    }

    with patch("api.routers.v1_s1_from_atom.generate_s1_from_atom", AsyncMock(return_value=fake_result)):
        response = await generate(TOUR_ID, _make_request(pool), model_tier="palmyra", tenant={})

    assert response["tour_id"] == TOUR_ID
    assert response["content"] == {"aa_summary": "grounded text"}
