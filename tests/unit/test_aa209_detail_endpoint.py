"""AA-209 PART 3: enriched GET /admin/tours/{id}/detail response shape.

The compare/detail UI needs the 4th sub-score (score_quality, previously SELECTed but dropped) plus
the GPT-4.1 judge object (from generated_content.metadata.judge) and brand_audit_status. These tests
pin the response contract:
  * judge present  → generated.judge populated, score_quality + brand_audit_status returned
  * judge absent   → generated.judge is None, score_quality still returned, no crash
  * metadata stored as a JSON string (asyncpg jsonb default) is parsed, not passed through raw
"""

import json
import pytest
from unittest.mock import patch

from api.routers import admin_pipeline


def _raw_row():
    return {
        "tour_id": "c425194c-e91a-475e-9877-2906eb976749", "src_name": "Seoul Discovery",
        "src_subtitle": None, "src_summary": None, "src_description": None,
        "src_highlights": None, "src_itineraries": None, "country": "South Korea",
        "duration": "8 days", "price_raw": "$3000", "group_size": None, "period": None,
        "provider": "Horizon Voyages", "inclusions": None, "exclusions": None,
        "pipeline_status": "generated", "ingest_at": None,
    }


def _gen_row(metadata, *, score_quality=9.5, brand_audit_status="flagged"):
    return {
        "id": "e46d69a9-6721-4aac-8732-59d863374b94", "version_num": 6, "created_at": None,
        "status": "approved", "aa_name": "Seoul Executive Discovery", "aa_subtitle": "y",
        "aa_summary": "z", "aa_description": "d", "aa_highlights": None, "aa_itineraries": "i",
        "seo_title": "t", "seo_meta": "m", "seo_keywords_used": None, "model_editorial": "haiku",
        "metadata": metadata,
        "score_overall": 7.0, "score_brand": 10.0, "score_seo": 8.5,
        "score_structure": 10.0, "score_quality": score_quality,
        "brand_audit_status": brand_audit_status,
    }


class _FakeConn:
    def __init__(self, raw, gen, pub):
        self.raw, self.gen, self.pub = raw, gen, pub

    async def fetchrow(self, query, *args):
        if "raw_tours" in query:
            return self.raw
        if "generated_content" in query:
            return self.gen
        if "published_tours" in query:
            return self.pub
        raise AssertionError(f"unexpected query: {query[:40]}")


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


async def _call(gen_row):
    conn = _FakeConn(_raw_row(), gen_row, None)
    request = _FakeRequest(_FakePool(conn))
    with patch.object(admin_pipeline, "verify_admin_secret", lambda *_a, **_k: None):
        return await admin_pipeline.get_tour_detail("c425194c", request, "secret")


_JUDGE = {"brand_fit": 8.0, "distinct": 7.0, "mission_present": True,
          "feedback": "Lead with the executive-privacy angle.", "judge_score": 7.0}


@pytest.mark.asyncio
async def test_detail_returns_judge_and_quality_when_present():
    meta = {"brand_name": "AA", "pipeline_version": "v2", "judge": _JUDGE}
    resp = await _call(_gen_row(meta))
    g = resp["generated"]
    assert g["score_quality"] == 9.5
    assert g["brand_audit_status"] == "flagged"
    assert g["judge"]["brand_fit"] == 8.0
    assert g["judge"]["distinct"] == 7.0          # key mapped from judge_cross_brand_distinct in PART 2
    assert g["judge"]["mission_present"] is True
    assert g["judge"]["feedback"].startswith("Lead with")
    assert g["judge"]["judge_score"] == 7.0


@pytest.mark.asyncio
async def test_detail_judge_none_when_metadata_has_no_judge():
    """Older/legacy version: metadata without a judge key → judge None, score_quality still present."""
    meta = {"brand_name": "AA", "pipeline_version": "v2"}
    resp = await _call(_gen_row(meta, score_quality=10.0, brand_audit_status=None))
    g = resp["generated"]
    assert g["judge"] is None
    assert g["score_quality"] == 10.0
    assert g["brand_audit_status"] is None


@pytest.mark.asyncio
async def test_detail_parses_metadata_json_string():
    """asyncpg returns jsonb as a str by default — the endpoint must json.loads it before reading judge."""
    meta_str = json.dumps({"brand_name": "AA", "judge": _JUDGE})
    resp = await _call(_gen_row(meta_str))
    assert resp["generated"]["judge"]["brand_fit"] == 8.0


@pytest.mark.asyncio
async def test_detail_no_crash_on_malformed_metadata():
    """Corrupt metadata string must not 500 the detail view — judge degrades to None."""
    resp = await _call(_gen_row("{not valid json"))
    assert resp["generated"]["judge"] is None
    assert resp["generated"]["score_quality"] == 9.5
