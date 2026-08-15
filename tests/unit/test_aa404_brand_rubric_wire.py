"""
tests/unit/test_aa404_brand_rubric_wire.py — F9 fix #1
(services/acp_produce/slot_runner.py::fetch_brand_rubric_text()).

Real per-tenant brand voice from `shared.tenant_brand_rules`, replacing the previously
hardcoded `AA_BRAND_IDENTITY_PROMPT` constant that every F9 call used until this fix. Mocks
`db.fetchrow()` directly (this function IS the DB-touching unit, unlike slot_runner.py's other
helpers which are themselves mocked away in test_aa375_slot_runner.py) — same "mock the DB,
exercise the real logic" convention as every other DB-wiring test in this repo.
"""
import json
from unittest.mock import AsyncMock

import pytest

from services.content_generation.brand_standards import AA_BRAND_IDENTITY_PROMPT
from services.acp_produce.slot_runner import fetch_brand_rubric_text

TENANT = "00000000-0000-0000-0000-000000000001"


def _row(**over):
    base = {
        "system_prompt": "You are writing for Adventure Asia.",
        "style_guide": "Voice attributes, what each means in a real sentence:\n- CALM — ...",
        "forbidden_words": ["book now", "hidden gem", "unforgettable"],
        "good_examples": "A bullet train departing Seoul southward delivers you to Gyeongju...",
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_returns_formatted_rubric_from_real_default_row():
    db = AsyncMock()
    db.fetchrow.return_value = _row()

    result = await fetch_brand_rubric_text(db, TENANT)

    assert "You are writing for Adventure Asia." in result
    assert "STYLE GUIDE:" in result
    assert "Voice attributes" in result
    assert "FORBIDDEN WORDS/PHRASES: book now, hidden gem, unforgettable" in result
    assert "GOOD EXAMPLES" in result
    assert "A bullet train departing Seoul" in result
    assert result != AA_BRAND_IDENTITY_PROMPT


@pytest.mark.asyncio
async def test_queries_the_default_active_row_for_this_tenant():
    """Same resolution shape as admin_pipeline.py::_resolve_brand_rule()'s no-id/no-name
    branch — tenant_id + brand_name='default' + is_active=true. Confirms the real call, not
    just that SOME query happened."""
    db = AsyncMock()
    db.fetchrow.return_value = _row()

    await fetch_brand_rubric_text(db, TENANT)

    db.fetchrow.assert_awaited_once()
    query, *params = db.fetchrow.await_args.args
    assert "shared.tenant_brand_rules" in query
    assert "brand_name = 'default'" in query
    assert "is_active = true" in query
    assert params == [TENANT]


@pytest.mark.asyncio
async def test_falls_back_to_generic_when_no_active_default_row():
    db = AsyncMock()
    db.fetchrow.return_value = None

    result = await fetch_brand_rubric_text(db, TENANT)

    assert result == AA_BRAND_IDENTITY_PROMPT


@pytest.mark.asyncio
async def test_falls_back_to_generic_when_system_prompt_empty():
    """A tenant whose 'default' row exists but was never populated — the exact real state
    aa_internal's own row was in before this fix (docs/implementation-notes/AA-404.md)."""
    db = AsyncMock()
    db.fetchrow.return_value = _row(system_prompt=None, style_guide=None,
                                     forbidden_words=[], good_examples=None)

    result = await fetch_brand_rubric_text(db, TENANT)

    assert result == AA_BRAND_IDENTITY_PROMPT


@pytest.mark.asyncio
async def test_falls_back_when_system_prompt_is_whitespace_only():
    db = AsyncMock()
    db.fetchrow.return_value = _row(system_prompt="   \n  ")

    result = await fetch_brand_rubric_text(db, TENANT)

    assert result == AA_BRAND_IDENTITY_PROMPT


@pytest.mark.asyncio
async def test_forbidden_words_as_json_string_is_parsed():
    """asyncpg jsonb gap (no codec registered, AA-300/AA-314) — real prod behavior returns
    JSON text, not a Python list, for every jsonb column including this one."""
    db = AsyncMock()
    db.fetchrow.return_value = _row(forbidden_words=json.dumps(["book now", "epic"]))

    result = await fetch_brand_rubric_text(db, TENANT)

    assert "FORBIDDEN WORDS/PHRASES: book now, epic" in result


@pytest.mark.asyncio
async def test_forbidden_words_as_python_list_still_works():
    """If a jsonb codec ever IS registered on this connection, forbidden_words arrives
    already-decoded — must not double-json.loads() a list and crash."""
    db = AsyncMock()
    db.fetchrow.return_value = _row(forbidden_words=["book now", "epic"])

    result = await fetch_brand_rubric_text(db, TENANT)

    assert "FORBIDDEN WORDS/PHRASES: book now, epic" in result


@pytest.mark.asyncio
async def test_omits_optional_sections_when_absent():
    """Only system_prompt is required — style_guide/forbidden_words/good_examples are each
    optional and must not leave a dangling empty header when absent."""
    db = AsyncMock()
    db.fetchrow.return_value = _row(style_guide=None, forbidden_words=[], good_examples=None)

    result = await fetch_brand_rubric_text(db, TENANT)

    assert "You are writing for Adventure Asia." in result
    assert "STYLE GUIDE:" not in result
    assert "FORBIDDEN WORDS/PHRASES:" not in result
    assert "GOOD EXAMPLES" not in result
