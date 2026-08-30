"""
tests/unit/test_aa469_viec5_a4_feedback_loop.py — AA-469 Việc 5: A4 feedback loop for T5/T9/T10.

Two real gaps closed, per docs/claude_audit/AA-469-viec5-step0-a4-feedback-loop-investigation.md:
- T5 (atomize) failures now persist to silver_aa_internal.review_queue (same table/shape T3's
  escalate_t3_failure() already writes to and A4's existing GET /admin/a4/review-log already
  reads) — services/acp_produce/tenant_pipeline.py::escalate_t5_atomize_failure(). No new A4
  endpoint needed for this half.
- T9/T10 (content_piece.gate_ledger/held_reason) gets its first-ever A4 read route —
  api/routers/admin_a4.py::get_content_log(), new GET /admin/a4/content-log.

T2 (already A4-reachable) and T6/T7 (confirmed not LLM-related) are untouched — this file covers
only the 2 real gaps this pass closed.
"""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

_TEST_SECRET = "test-admin-secret"


@pytest.fixture(autouse=True)
def _admin_secret(monkeypatch):
    monkeypatch.setattr("api.routers.admin.ADMIN_SECRET", _TEST_SECRET)


def _make_pool(fetch=None, execute=None):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=fetch or [])
    conn.execute = AsyncMock(return_value=execute or "INSERT 0 1")

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


TENANT_ID = str(uuid.uuid4())
TOUR_ID = str(uuid.uuid4())
VERSION_ID = str(uuid.uuid4())
PIECE_ID = str(uuid.uuid4())
REQUEST_ID = str(uuid.uuid4())


# ── services.acp_produce.tenant_pipeline.escalate_t5_atomize_failure ────────────

@pytest.mark.asyncio
class TestEscalateT5AtomizeFailure:
    async def test_writes_same_shape_as_t3_escalate(self):
        """Same table, same 5 columns, same escalate_detail item shape as escalate_t3_failure()
        — confirmed by direct comparison, not just asserted separately."""
        from services.acp_produce.tenant_pipeline import escalate_t5_atomize_failure

        pool, conn = _make_pool()
        await escalate_t5_atomize_failure(
            pool, TENANT_ID, TOUR_ID, VERSION_ID, "BedrockError: boom",
        )

        conn.execute.assert_awaited_once()
        sql, *params = conn.execute.call_args[0]
        assert "INSERT INTO silver_aa_internal.review_queue" in sql
        assert "(tour_id, tenant_id, tenant_tour_version_id, failure_summary, escalate_detail)" in sql
        assert params[0] == TOUR_ID
        assert params[1] == TENANT_ID
        assert params[2] == VERSION_ID
        assert "T5 atomize failed" in params[3]

        detail = json.loads(params[4])
        assert len(detail) == 1
        item = detail[0]
        assert set(item.keys()) == {"check_id", "field", "description", "source_span", "suggested_fix"}
        assert item["check_id"] == "t5_atomize:BedrockError"
        assert item["description"] == "BedrockError: boom"

    async def test_check_id_falls_back_to_failed_when_no_colon(self):
        """A T5 error string with no ':' (not the usual f'{type}: {msg}' shape) must not crash
        the check_id extraction — falls back to a generic category."""
        from services.acp_produce.tenant_pipeline import escalate_t5_atomize_failure

        pool, conn = _make_pool()
        await escalate_t5_atomize_failure(pool, TENANT_ID, TOUR_ID, VERSION_ID, "something broke")

        _sql, *params = conn.execute.call_args[0]
        detail = json.loads(params[4])
        assert detail[0]["check_id"] == "t5_atomize:failed"

    async def test_this_is_the_exact_table_a4_review_log_already_reads(self):
        """Confirms the join key (tenant_tour_version_id) is populated — GET /admin/a4/review-log
        filters WHERE tenant_tour_version_id IS NOT NULL, so a NULL here would silently exclude
        a T5 row from A4 even though the INSERT itself succeeded."""
        from services.acp_produce.tenant_pipeline import escalate_t5_atomize_failure

        pool, conn = _make_pool()
        await escalate_t5_atomize_failure(pool, TENANT_ID, TOUR_ID, VERSION_ID, "X: y")

        _sql, *params = conn.execute.call_args[0]
        assert params[2] == VERSION_ID  # tenant_tour_version_id — never None


# ── api.routers.admin_a4.get_content_log ────────────────────────────────────────

@pytest.mark.asyncio
class TestGetContentLog:
    async def test_requires_admin_secret(self):
        from api.routers.admin_a4 import get_content_log

        pool, _ = _make_pool(fetch=[])
        req = _make_request(pool)

        with pytest.raises(HTTPException) as exc_info:
            await get_content_log(req, tenant_id=None, limit=200, x_admin_secret="wrong")
        assert exc_info.value.status_code == 403

    @staticmethod
    def _full_row(**over):
        """AA-501 — every column the widened SELECT now returns. Held/failed rows are no longer
        the only rows this endpoint returns (see test_returns_every_status_not_just_held_failed
        below) — this fixture covers a 'held' row with a full angle/atom/tour/DFS-PAA context so
        every new field has real coverage."""
        base = {
            "piece_id": PIECE_ID, "tenant_id": TENANT_ID, "tenant_name": "WanderLux",
            "tenant_slug": "wanderlux-travel", "angle_gate_request_id": REQUEST_ID,
            "atom_id": "atom_abc123", "goal": "engagement_conversation", "cta": "Book now",
            "dfs_paa_snapshot": json.dumps(
                {"relevance": "HIGH", "people_also_ask": ["q1"], "related_keywords": ["k1"]}
            ),
            "trip_id": TOUR_ID, "channel": "tiktok",
            "status": "held", "held_reason": "F1_grounding: unsupported claim",
            "gate_ledger": json.dumps([
                {"gate": "F1_grounding", "passed": False, "violations": ["unsupported claim"]},
                {"gate": "F6_cta_present", "passed": True, "violations": []},
            ]),
            "repair_log": json.dumps([{"round": 1, "feedback": "add a source"}]),
            "attempt_number": 2, "content_preview": "Some real content...",
            "angle_name": "Behind the Scenes", "angle_why_it_works": "curiosity",
            "angle_formula_fit": "AIDA", "angle_best_final_style": "warm",
            "atom_text": "Cross the bamboo bridge", "atom_activity_type": "adventure",
            "atom_emotional_hook": "awe", "atom_season_note": "dry season best",
            "tour_name": "Sapa Trek", "tour_destination": "Vietnam",
            "publish_id": None,
            "created_at": datetime(2026, 8, 30, tzinfo=timezone.utc),
        }
        base.update(over)
        return base

    async def test_returns_full_context_and_gate_detail(self):
        from api.routers.admin_a4 import get_content_log

        pool, conn = _make_pool(fetch=[self._full_row()])
        req = _make_request(pool)

        result = await get_content_log(req, tenant_id=None, limit=200, x_admin_secret=_TEST_SECRET)

        assert result["total"] == 1
        item = result["data"][0]
        assert item["status"] == "held"
        assert item["channel"] == "tiktok"
        assert len(item["gate_ledger"]) == 2
        assert item["gate_ledger"][0]["gate"] == "F1_grounding"
        assert item["gate_pass_count"] == 1
        assert item["gate_total_count"] == 2
        assert item["repair_log"] == [{"round": 1, "feedback": "add a source"}]
        assert item["angle"] == {
            "name": "Behind the Scenes", "why_it_works": "curiosity",
            "formula_fit": "AIDA", "best_final_style": "warm",
        }
        assert item["atom"] == {
            "text": "Cross the bamboo bridge", "activity_type": "adventure",
            "emotional_hook": "awe", "season_note": "dry season best",
        }
        assert item["tour"] == {"name": "Sapa Trek", "destination": "Vietnam"}
        assert item["dfs_paa_snapshot"] == {
            "relevance": "HIGH", "people_also_ask": ["q1"], "related_keywords": ["k1"],
        }
        assert item["cta"] == "Book now"
        assert item["publish_status"] == "n/a"  # held — not ready to publish at all

    async def test_query_no_longer_hardcodes_held_failed_filter(self):
        """AA-501 — widened from held/failed-only to every content_piece row (Nghiệp: 'AA cần
        thấy MỌI THỨ tenant thấy, CỘNG THÊM chi tiết kỹ thuật' — not a different subset)."""
        from api.routers.admin_a4 import get_content_log

        pool, conn = _make_pool(fetch=[])
        req = _make_request(pool)
        await get_content_log(req, tenant_id=None, limit=200, x_admin_secret=_TEST_SECRET)

        sql = conn.fetch.call_args[0][0]
        assert "cp.status IN ('held', 'failed')" not in sql

    async def test_publish_status_published_when_publish_log_row_exists(self):
        from api.routers.admin_a4 import get_content_log

        row = self._full_row(status="approved", held_reason=None, publish_id=str(uuid.uuid4()))
        pool, conn = _make_pool(fetch=[row])
        req = _make_request(pool)

        result = await get_content_log(req, tenant_id=None, limit=200, x_admin_secret=_TEST_SECRET)
        assert result["data"][0]["publish_status"] == "published"

    async def test_publish_status_pending_when_approved_and_unpublished(self):
        from api.routers.admin_a4 import get_content_log

        row = self._full_row(status="approved", held_reason=None, publish_id=None)
        pool, conn = _make_pool(fetch=[row])
        req = _make_request(pool)

        result = await get_content_log(req, tenant_id=None, limit=200, x_admin_secret=_TEST_SECRET)
        assert result["data"][0]["publish_status"] == "pending_publish"

    async def test_no_llm_cost_or_token_fields(self):
        """AA-501 build task explicitly excludes cost/token tracking (split to AA-505) — this
        endpoint must not fabricate or expose any such field."""
        from api.routers.admin_a4 import get_content_log

        pool, conn = _make_pool(fetch=[self._full_row()])
        req = _make_request(pool)

        result = await get_content_log(req, tenant_id=None, limit=200, x_admin_secret=_TEST_SECRET)
        keys = set(result["data"][0].keys())
        assert not any("cost" in k or "token" in k for k in keys)

    async def test_channel_reads_content_piece_first_coalesce_pattern(self):
        """Same COALESCE(cp.channel, agr.channel) fix AA-469 Việc 4 already applied to
        v1_publish.py's two queries on this same table, for the same reason: angle_gate_request.
        channel is no longer stable after a piece is written (set_channel() can be called again
        before the request's NEXT write)."""
        from api.routers.admin_a4 import get_content_log

        pool, conn = _make_pool(fetch=[])
        req = _make_request(pool)
        await get_content_log(req, tenant_id=None, limit=200, x_admin_secret=_TEST_SECRET)

        sql = conn.fetch.call_args[0][0]
        assert "COALESCE(cp.channel, agr.channel)" in sql

    async def test_tenant_filter_scopes_query_cross_tenant_by_default(self):
        """Same cross-tenant-by-default shape as review-log/publish-log: an optional filter,
        not a hard tenant scope — A4 is cross-tenant oversight by design."""
        from api.routers.admin_a4 import get_content_log

        pool, conn = _make_pool(fetch=[])
        req = _make_request(pool)

        # No filter — every tenant's held/failed pieces are visible.
        await get_content_log(req, tenant_id=None, limit=200, x_admin_secret=_TEST_SECRET)
        sql_unfiltered = conn.fetch.call_args[0][0]
        assert "cp.tenant_id = $" not in sql_unfiltered

        # With a filter — scoped to just that tenant.
        await get_content_log(req, tenant_id=TENANT_ID, limit=200, x_admin_secret=_TEST_SECRET)
        sql_filtered, *params = conn.fetch.call_args[0]
        assert "cp.tenant_id = $" in sql_filtered
        assert TENANT_ID in params

    async def test_empty_result_is_not_an_error(self):
        from api.routers.admin_a4 import get_content_log

        pool, _ = _make_pool(fetch=[])
        req = _make_request(pool)

        result = await get_content_log(req, tenant_id=None, limit=200, x_admin_secret=_TEST_SECRET)
        assert result["data"] == []
        assert result["total"] == 0
