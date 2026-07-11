"""AA-276: metadata.brand_rule_id = "" must not 500 the export/detail routes.

Root cause: `_execute_run_tour` used to default brand_rule_id to "" (not None) when
_resolve_brand_rule() found no match, and 3 routes joined tenant_brand_rules with a
bare `(gc.metadata->>'brand_rule_id')::uuid` cast — Postgres raises
asyncpg.exceptions.InvalidTextRepresentationError on `''::uuid`, which FastAPI turns
into an unhandled 500. Confirmed by a real CloudWatch traceback + DB row
(tour 7f57ba60-7fa5-4842-918f-79e823c6f380 v1, metadata.brand_rule_id == "").

Two independent fixes are pinned here:
  Part 1 (defensive): all 3 affected queries now use
    NULLIF(gc.metadata->>'brand_rule_id', '')::uuid — verified by capturing the
    literal SQL text sent to fetch/fetchrow (same pattern as test_aa220_export.py
    Stage D), so a future edit that drops the guard fails this test.
  Part 2 (root cause): brand_rule_id defaults to None (not ""), and json.dumps(None)
    serializes to JSON null, not the empty string that caused the crash.

Calls the real, compiled endpoint functions (export_tour_version_docx,
get_tour_version_detail, export_tour_versions) with a fake pool/conn — not a helper
extracted in isolation — per this repo's convention that this class of bug only
surfaces through the full request path.
"""

import json
import pytest
from unittest.mock import patch

from api.routers import admin_pipeline


class _FakeConn:
    def __init__(self, *, rows=None, row=None, capture=None):
        self._rows = rows
        self._row = row
        self._capture = capture

    async def fetch(self, query, *args):
        if self._capture is not None:
            self._capture.append((query, args))
        return self._rows if self._rows is not None else []

    async def fetchrow(self, query, *args):
        if self._capture is not None:
            self._capture.append((query, args))
        return self._row


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


class _FakeRequest:
    def __init__(self, pool):
        self.app = type("A", (), {"state": type("S", (), {"pool": pool})()})()


def _request(conn):
    return _FakeRequest(_FakePool(conn))


async def _read_body(resp):
    out = b""
    async for chunk in resp.body_iterator:
        out += chunk if isinstance(chunk, (bytes, bytearray)) else chunk.encode("utf-8")
    return out


_NOSECRET = patch.object(admin_pipeline, "verify_admin_secret", lambda *_a, **_k: None)
_NULLIF_GUARD = "NULLIF(gc.metadata->>'brand_rule_id', '')::uuid"
TOUR = "7f57ba60-7fa5-4842-918f-79e823c6f380"

# The exact bad metadata this tour actually has in prod (S102 investigation).
_BROKEN_METADATA = json.dumps({
    "brand_rule_id": "", "brand_name": "", "model_used": "gpt-4.1",
    "fallback_used": True, "revalidate_ran": True, "revalidate_passed": True,
})


def _detail_row(**over):
    base = {
        "id": "c9aafea0-3c21-489b-8bb0-a1b3ccab83dd",
        "version_num": 1, "model_id": "gpt-4.1",
        "quality_score": 9.75, "score_brand": 10.0, "score_seo": 9.0, "score_structure": 10.0,
        "score_quality": 10.0,
        "failure_codes": json.dumps(["DFS_INTENT_UNDERUSED"]),
        "brand_audit_status": "fixed",
        "brand_audit_codes": json.dumps([]),
        "brand_audit_issues": [],
        "fix_pass_applied": True,
        "fix_pass_fields": json.dumps(["itineraries"]),
        "created_at": None,
        "aa_name": "Explore South Korea on Foot", "aa_subtitle": "sub", "aa_summary": "z",
        "aa_description": "d", "aa_highlights": json.dumps(["Gyeongbokgung Palace"]),
        "aa_itineraries": "Day 1: Seoul", "seo_title": "t", "seo_meta": "m",
        "metadata": _BROKEN_METADATA,
        "brand_name": None,  # tbr.brand_name — NULL, the LEFT JOIN found no row
        "top_keywords": json.dumps([]),
        "keyword_ideas": [],
        "people_also_ask": json.dumps([]),
        "related_keywords": [],
        "keyword_search": "south korea tours",
        "country": "South Korea", "duration": "8 days", "group_size": None,
        "price_raw": None, "period": None, "provider": None,
        "inclusions": None, "exclusions": None,
    }
    base.update(over)
    return base


def _docx_row(**over):
    base = dict(_detail_row(**over))
    base.pop("quality_score", None)
    base["score_overall"] = 9.75
    base["tenant_id"] = "00000000-0000-0000-0000-000000000001"
    return base


_VERSIONS_EXPORT_DROP_KEYS = (
    "id", "tenant_id", "country", "duration", "group_size", "price_raw", "period",
    "provider", "inclusions", "exclusions", "top_keywords", "keyword_ideas",
    "people_also_ask", "related_keywords", "keyword_search",
)


def _versions_export_row(**over):
    base = dict(_docx_row(**over))
    for key in _VERSIONS_EXPORT_DROP_KEYS:
        base.pop(key, None)
    return base


@pytest.mark.asyncio
async def test_export_docx_guarded_sql_and_no_crash_on_broken_metadata():
    cap = []
    with _NOSECRET:
        resp = await admin_pipeline.export_tour_version_docx(
            TOUR, 1, _request(_FakeConn(row=_docx_row(), capture=cap)), x_admin_secret="s",
        )
    query, _args = cap[0]
    assert _NULLIF_GUARD in query
    assert "wordprocessingml.document" in resp.media_type  # 200, not 500


@pytest.mark.asyncio
async def test_version_detail_guarded_sql_and_no_crash_on_broken_metadata():
    cap = []
    with _NOSECRET:
        result = await admin_pipeline.get_tour_version_detail(
            TOUR, 1, _request(_FakeConn(row=_detail_row(), capture=cap)), x_admin_secret="s",
        )
    query, _args = cap[0]
    assert _NULLIF_GUARD in query
    assert result["aa_name"] == "Explore South Korea on Foot"  # 200, not 500
    assert result["brand_name"] == "default"  # falls back cleanly (tbr.brand_name is None)


@pytest.mark.asyncio
async def test_versions_export_guarded_sql_and_no_crash_on_broken_metadata():
    cap = []
    with _NOSECRET:
        resp = await admin_pipeline.export_tour_versions(
            TOUR, _request(_FakeConn(rows=[_versions_export_row()], capture=cap)),
            versions="1", format="csv", x_admin_secret="s",
        )
    query, _args = cap[0]
    assert _NULLIF_GUARD in query
    body = (await _read_body(resp)).decode("utf-8")
    assert "field,v1" in body  # 200, not 500


def test_root_cause_fix_serializes_missing_brand_rule_id_as_json_null_not_empty_string():
    """Part 2: brand_rule_id defaults to None, and json.dumps(None) round-trips to
    JSON null (Postgres NULL via ->>), never the "" that caused the crash."""
    meta = admin_pipeline._build_generated_metadata(
        {}, brand_rule_id=None, brand_name="", seo_mode="standard",
        model_used="gpt-4.1", llm_cost_usd=0.01, dataforseo_used=False,
    )
    metadata_val = json.dumps(meta, default=str)
    round_tripped = json.loads(metadata_val)
    assert round_tripped["brand_rule_id"] is None
    assert round_tripped["brand_rule_id"] != ""
