"""AA-219: get_tour_version_detail must surface judge / quality / brand-audit /
fix-pass / failure-codes / revalidate + full DFS (keyword_ideas/PAA/related/seed).

Pins the response contract and exercises the local _as_list guard on BOTH driver
shapes (jsonb-as-str AND jsonb-as-list), since asyncpg returns either.
"""

import json
import pytest
from unittest.mock import patch

from api.routers import admin_pipeline


_JUDGE = {"brand_fit": 8.0, "distinct": 7.0, "mission_present": True,
          "feedback": "Lead with the executive-privacy angle.", "judge_score": 7.0}


def _row(**over):
    base = {
        "id": "e46d69a9-6721-4aac-8732-59d863374b94",
        "version_num": 6, "model_id": "haiku",
        "quality_score": 7.0, "score_brand": 10.0, "score_seo": 8.5, "score_structure": 10.0,
        "score_quality": 9.5,
        # failure_codes + brand_audit_codes arrive as JSON STRINGS (one driver path)
        "failure_codes": json.dumps(["SEO_META_SHORT"]),
        "brand_audit_status": "flagged",
        "brand_audit_codes": json.dumps(["FORBIDDEN_WORD"]),
        # brand_audit_issues arrives as a native LIST (other driver path)
        "brand_audit_issues": [{"field": "seo_meta", "msg": "contains 'cheap'"}],
        "fix_pass_applied": True,
        "fix_pass_fields": json.dumps(["seo_meta"]),
        "created_at": None,
        "aa_name": "Seoul Executive Discovery", "aa_subtitle": "y", "aa_summary": "z",
        "aa_description": "d", "aa_highlights": json.dumps(["h1", "h2"]),
        "aa_itineraries": "i", "seo_title": "t", "seo_meta": "m",
        "metadata": json.dumps({"judge": _JUDGE, "revalidate_ran": True, "revalidate_passed": True}),
        "brand_name": "AA",
        "top_keywords": json.dumps(["korea tours"]),
        # keyword_ideas as native LIST; related_keywords as native LIST; PAA as STRING
        "keyword_ideas": [{"keyword": "korea trek", "search_volume": 320,
                           "competition": "LOW", "competition_index": 5, "cpc": 0.93}],
        "people_also_ask": json.dumps(["is korea safe?"]),
        "related_keywords": ["korea tours", "seoul trip"],
        "keyword_search": "South Korea tours",
        "country": "South Korea", "duration": "8 days", "group_size": None,
        "price_raw": "$3000", "period": None, "provider": "Horizon Voyages",
        "inclusions": None, "exclusions": None,
    }
    base.update(over)
    return base


class _FakeConn:
    def __init__(self, row):
        self._row = row

    async def fetchrow(self, query, *args):
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


async def _call(row):
    request = _FakeRequest(_FakePool(_FakeConn(row)))
    with patch.object(admin_pipeline, "verify_admin_secret", lambda *_a, **_k: None):
        return await admin_pipeline.get_tour_version_detail(
            "11111111-1111-1111-1111-111111111111", 6, request, "secret"
        )


@pytest.mark.asyncio
async def test_surfaces_judge_quality_audit_fix_failure_revalidate_and_dfs():
    resp = await _call(_row())

    # judge object straight from metadata
    assert resp["judge"] == _JUDGE
    assert resp["score_quality"] == 9.5

    # brand audit
    assert resp["brand_audit_status"] == "flagged"
    assert resp["brand_audit_codes"] == ["FORBIDDEN_WORD"]          # parsed from str
    assert resp["brand_audit_issues"] == [{"field": "seo_meta", "msg": "contains 'cheap'"}]  # native list

    # fix pass + failure codes
    assert resp["fix_pass_applied"] is True
    assert resp["fix_pass_fields"] == ["seo_meta"]
    assert resp["failure_codes"] == ["SEO_META_SHORT"]

    # revalidate from metadata
    assert resp["revalidate_ran"] is True
    assert resp["revalidate_passed"] is True

    # full DFS
    assert resp["seed"] == "South Korea tours"
    assert resp["keyword_ideas"][0]["keyword"] == "korea trek"     # native list
    assert resp["people_also_ask"] == ["is korea safe?"]           # parsed from str
    assert resp["related_keywords"] == ["korea tours", "seoul trip"]  # native list


@pytest.mark.asyncio
async def test_as_list_handles_both_str_and_list_to_list():
    # every jsonb-ish field must come back as a list regardless of driver shape
    resp = await _call(_row())
    for key in ("brand_audit_codes", "brand_audit_issues", "fix_pass_fields",
                "failure_codes", "keyword_ideas", "people_also_ask", "related_keywords"):
        assert isinstance(resp[key], list), f"{key} must be a list, got {type(resp[key])}"


@pytest.mark.asyncio
async def test_judge_none_when_metadata_lacks_judge():
    resp = await _call(_row(metadata=json.dumps({"revalidate_ran": False})))
    assert resp["judge"] is None
    assert resp["revalidate_ran"] is False
    assert resp["revalidate_passed"] is False


@pytest.mark.asyncio
async def test_null_quality_scores_degrade_to_none_and_empty_lists():
    resp = await _call(_row(
        score_quality=None, failure_codes=None, brand_audit_status=None,
        brand_audit_codes=None, brand_audit_issues=None,
        fix_pass_applied=None, fix_pass_fields=None,
        keyword_ideas=None, people_also_ask=None, related_keywords=None,
        keyword_search=None, metadata=None,
    ))
    assert resp["score_quality"] is None
    assert resp["brand_audit_status"] is None
    assert resp["brand_audit_codes"] == []
    assert resp["brand_audit_issues"] == []
    assert resp["failure_codes"] == []
    assert resp["fix_pass_applied"] is False
    assert resp["fix_pass_fields"] == []
    assert resp["keyword_ideas"] == []
    assert resp["people_also_ask"] == []
    assert resp["related_keywords"] == []
    assert resp["seed"] is None
    assert resp["judge"] is None
    assert resp["revalidate_ran"] is False
