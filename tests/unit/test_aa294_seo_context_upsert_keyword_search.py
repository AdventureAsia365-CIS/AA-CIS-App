"""AA-294: seo_context upsert dropped keyword_search from its SET list.

Root cause: `INSERT ... ON CONFLICT (tour_id) DO UPDATE SET` (seo_context_repository.py)
listed cache_key/keyword_ideas/top_keywords/etc. but never `keyword_search`. Any tour
re-run after its first (e.g. AA-251 re-generation) kept the ORIGINAL seed string in
keyword_search forever, even though cache_key/top_keywords correctly reflected the new
seed — confirmed live: a tour's seo_context row from before AA-251 shipped still showed
keyword_search="South Korea tours" after a fresh run whose actual seed (per cache_key/
top_keywords) was the new, specific "<tour name> South Korea".

A plain AsyncMock (the AA-249 test convention) can't catch this class of bug — it
returns a fixed value regardless of what SQL/params were sent, so it can't tell you
whether a column's post-upsert value is old or new. FakeSeoContextConn below is a
minimal in-memory table that actually applies ON CONFLICT semantics by parsing which
columns the SET clause self-assigns from EXCLUDED — it updates only what the SQL text
says to update, same as real Postgres would.
"""

import re

import pytest

from shared.repository.seo_context_repository import SeoContextRepository

_COLUMNS = [
    "tour_id", "tenant_id", "keyword_search", "provider",
    "keyword_ideas", "demographics", "trends", "top_keywords",
    "cache_key", "expires_at", "people_also_ask", "related_keywords",
]


def _set_clause_columns(sql: str) -> set:
    """Columns the SET clause self-assigns from EXCLUDED (col = EXCLUDED.col)."""
    return set(re.findall(r"(\w+)\s*=\s*EXCLUDED\.\1", sql))


class FakeSeoContextConn:
    """In-memory tour_id-keyed table honoring ON CONFLICT (tour_id) DO UPDATE SET
    exactly as the real SQL text dictates — a column only survives a 2nd upsert if
    the SET clause names it."""

    def __init__(self):
        self.rows_by_tour_id = {}

    async def fetchrow(self, sql, *params):
        row = dict(zip(_COLUMNS, params))
        tour_id = row["tour_id"]
        if tour_id not in self.rows_by_tour_id:
            self.rows_by_tour_id[tour_id] = dict(row)
        else:
            for col in _set_clause_columns(sql):
                self.rows_by_tour_id[tour_id][col] = row[col]
        return {"id": "fake-id"}


def _make_repo():
    conn = FakeSeoContextConn()
    return conn, SeoContextRepository(conn, tenant_slug="aa_internal")


@pytest.mark.asyncio
async def test_upsert_refreshes_keyword_search_on_second_call():
    """The bug, reproduced: insert once with an old seed, upsert again (same
    tour_id) with a new seed — the row must reflect the NEW seed afterward.
    Pre-fix this assertion fails (old seed sticks); post-fix it passes."""
    conn, repo = _make_repo()
    tour_id = "11111111-1111-1111-1111-111111111111"

    await repo.insert({
        "tour_id": tour_id,
        "keyword_search": "South Korea tours",
        "cache_key": "seo:south_korea_tours:2840",
    })
    await repo.insert({
        "tour_id": tour_id,
        "keyword_search": "Explore South Korea on Foot South Korea",
        "cache_key": "seo:explore_south_korea_on_foot_south_korea:2840",
    })

    assert conn.rows_by_tour_id[tour_id]["keyword_search"] == \
        "Explore South Korea on Foot South Korea"


@pytest.mark.asyncio
async def test_set_clause_includes_keyword_search():
    """Belt & suspenders against a future refactor that keeps behavior correct
    but renames columns oddly — pins the literal SQL text (AA-249 test convention)."""
    from unittest.mock import AsyncMock, MagicMock

    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value={"id": "fake-id"})
    mock_repo = SeoContextRepository(mock_conn, tenant_slug="aa_internal")
    await mock_repo.insert({
        "tour_id": "11111111-1111-1111-1111-111111111111",
        "keyword_search": "South Korea tours",
    })
    sql_text = mock_conn.fetchrow.await_args.args[0]
    assert "keyword_search   = EXCLUDED.keyword_search" in sql_text
