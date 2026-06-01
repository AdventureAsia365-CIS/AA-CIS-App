"""
AA-117 — acp_run_context Pydantic guard + atomic jsonb_set tests.

Test coverage:
  1. Schema rejects malformed / NULL required fields
  2. get_run_context_validated raises typed error on bad row (no silent None)
  3. Concurrent write: two writers set different stage keys in parallel -> both persist
  4. Upstream-missing: downstream stage raises RunContextValidationError when upstream absent
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock


# ── 1. Schema validation ──────────────────────────────────────────────────────

class TestS2StagePayloadSchema:
    def test_rejects_confidence_score_above_one(self):
        from pydantic import ValidationError
        from api.schemas.run_context import S2StagePayload

        with pytest.raises(ValidationError, match="s2_confidence_score"):
            S2StagePayload(
                s2_keyword_research={},
                s2_visibility_report={},
                s2_confidence_score=1.5,  # invalid: > 1.0
            )

    def test_rejects_negative_confidence_score(self):
        from pydantic import ValidationError
        from api.schemas.run_context import S2StagePayload

        with pytest.raises(ValidationError, match="s2_confidence_score"):
            S2StagePayload(
                s2_keyword_research={},
                s2_visibility_report={},
                s2_confidence_score=-0.1,
            )

    def test_accepts_valid_s2_payload(self):
        from api.schemas.run_context import S2StagePayload

        p = S2StagePayload(
            s2_keyword_research={"top_opportunities": ["vietnam tours"]},
            s2_visibility_report={"summary": "good"},
            s2_confidence_score=0.90,
        )
        assert p.s2_confidence_score == 0.90

    def test_optional_fields_default_to_none(self):
        from api.schemas.run_context import S2StagePayload

        p = S2StagePayload(
            s2_keyword_research={},
            s2_visibility_report={},
            s2_confidence_score=0.75,
        )
        assert p.s2_keyword_clusters is None
        assert p.s2_market_preference is None
        assert p.s2_aa_tour_matches is None


class TestS0StagePayloadSchema:
    def test_rejects_empty_brand_brief(self):
        from pydantic import ValidationError
        from api.schemas.run_context import S0StagePayload

        with pytest.raises(ValidationError, match="brand_brief"):
            S0StagePayload(brand_brief={})

    def test_accepts_non_empty_brand_brief(self):
        from api.schemas.run_context import S0StagePayload

        p = S0StagePayload(brand_brief={"funnel_mix": {"tofu": 20}})
        assert p.brand_brief["funnel_mix"]["tofu"] == 20


class TestS3StagePayloadSchema:
    def test_rejects_missing_required_fields(self):
        from pydantic import ValidationError
        from api.schemas.run_context import S3StagePayload

        with pytest.raises(ValidationError):
            S3StagePayload(
                s3_content_calendar={"calendar_id": "x"},
                # s3_ads_plan missing
                s3_funnel_mix={"tofu": 20, "mofu": 60, "bofu": 20},
            )

    def test_accepts_valid_s3_payload(self):
        from api.schemas.run_context import S3StagePayload

        p = S3StagePayload(
            s3_content_calendar={"calendar_id": "abc"},
            s3_ads_plan={"ads_plan_id": "def", "campaign_count": 2},
            s3_funnel_mix={"tofu": 20, "mofu": 60, "bofu": 20},
        )
        assert p.s3_ads_plan["campaign_count"] == 2


# ── 2. get_run_context_validated — no silent None ─────────────────────────────

class TestGetRunContextValidated:
    @pytest.mark.asyncio
    async def test_raises_when_row_missing(self):
        from api.schemas.run_context import RunContextValidationError
        from api.services.run_context_db import get_run_context_validated

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # no row

        with pytest.raises(RunContextValidationError) as exc_info:
            await get_run_context_validated(conn, "run-uuid-1")

        assert exc_info.value.missing_path == "<row>"
        assert exc_info.value.run_id == "run-uuid-1"

    @pytest.mark.asyncio
    async def test_returns_validated_context_on_good_row(self):
        from api.services.run_context_db import get_run_context_validated

        row = {
            "run_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "brand_brief": json.dumps({"cadence_weeks": 12}),
            "s1_keywords_used": json.dumps(["vietnam tours"]),
            "s2_keyword_research": json.dumps({"top_opportunities": ["tour"]}),
            "s2_visibility_report": json.dumps({"summary": "good"}),
            "s2_keyword_clusters": None,
            "s2_market_preference": None,
            "s2_aa_tour_matches": None,
            "s2_confidence_score": "0.9000",
            "s3_content_calendar": None,
            "s3_ads_plan": None,
            "s3_funnel_mix": None,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        ctx = await get_run_context_validated(conn, "aaaaaaaa-0000-0000-0000-000000000001")

        assert ctx.s2_confidence_score == pytest.approx(0.9)
        assert ctx.s1_keywords_used == ["vietnam tours"]

    @pytest.mark.asyncio
    async def test_raises_when_required_stage_field_is_null(self):
        from api.schemas.run_context import RunContextValidationError
        from api.services.run_context_db import get_run_context_validated

        row = {
            "run_id": "aaaaaaaa-0000-0000-0000-000000000002",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "brand_brief": None,
            "s1_keywords_used": None,
            "s2_keyword_research": None,  # NULL — required by s2
            "s2_visibility_report": None,
            "s2_keyword_clusters": None,
            "s2_market_preference": None,
            "s2_aa_tour_matches": None,
            "s2_confidence_score": None,
            "s3_content_calendar": None,
            "s3_ads_plan": None,
            "s3_funnel_mix": None,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with pytest.raises(RunContextValidationError) as exc_info:
            await get_run_context_validated(
                conn,
                "aaaaaaaa-0000-0000-0000-000000000002",
                require_stages=("s2",),
            )

        assert "s2_" in exc_info.value.missing_path

    @pytest.mark.asyncio
    async def test_no_error_when_no_stages_required(self):
        """Calling without require_stages should succeed even with all-NULL fields."""
        from api.services.run_context_db import get_run_context_validated

        row = {
            "run_id": "aaaaaaaa-0000-0000-0000-000000000003",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "brand_brief": None,
            "s1_keywords_used": None,
            "s2_keyword_research": None,
            "s2_visibility_report": None,
            "s2_keyword_clusters": None,
            "s2_market_preference": None,
            "s2_aa_tour_matches": None,
            "s2_confidence_score": None,
            "s3_content_calendar": None,
            "s3_ads_plan": None,
            "s3_funnel_mix": None,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        ctx = await get_run_context_validated(conn, "aaaaaaaa-0000-0000-0000-000000000003")
        assert ctx.s2_confidence_score is None


# ── 3. Concurrent write — disjoint columns, no lost update ───────────────────

class TestConcurrentWrite:
    @pytest.mark.asyncio
    async def test_concurrent_stage_writes_do_not_clobber(self):
        """
        Two asyncio tasks write different stages (s2, s3) via write_run_context_stage.
        Each should call execute with only its own columns — no shared state clobbering.
        """
        from api.services.run_context_db import write_run_context_stage

        executed_sqls = []

        async def _fake_execute(sql, *args):
            executed_sqls.append(sql)

        conn_s2 = AsyncMock()
        conn_s2.execute = _fake_execute

        conn_s3 = AsyncMock()
        conn_s3.execute = _fake_execute

        s2_payload = {
            "s2_keyword_research": {"top_opportunities": ["vietnam"]},
            "s2_visibility_report": {"summary": "ok"},
            "s2_confidence_score": 0.88,
        }
        s3_payload = {
            "s3_content_calendar": {"calendar_id": "cal-1"},
            "s3_ads_plan": {"ads_plan_id": "ads-1", "campaign_count": 3},
            "s3_funnel_mix": {"tofu": 20, "mofu": 60, "bofu": 20},
        }

        await asyncio.gather(
            write_run_context_stage(conn_s2, "run-1", "s2", s2_payload),
            write_run_context_stage(conn_s3, "run-1", "s3", s3_payload),
        )

        assert len(executed_sqls) == 2
        s2_sql, s3_sql = executed_sqls[0], executed_sqls[1]

        # Each UPDATE only touches its own columns
        assert "s2_keyword_research" in s2_sql
        assert "s3_content_calendar" not in s2_sql

        assert "s3_content_calendar" in s3_sql
        assert "s2_keyword_research" not in s3_sql

    @pytest.mark.asyncio
    async def test_s2_write_does_not_include_s3_columns(self):
        from api.services.run_context_db import write_run_context_stage

        executed = []

        async def _capture(sql, *args):
            executed.append(sql)

        conn = AsyncMock()
        conn.execute = _capture

        await write_run_context_stage(conn, "run-x", "s2", {
            "s2_keyword_research": {},
            "s2_visibility_report": {},
            "s2_confidence_score": 0.7,
        })

        assert len(executed) == 1
        sql = executed[0]
        assert "s3_content_calendar" not in sql
        assert "s3_ads_plan" not in sql
        assert "s3_funnel_mix" not in sql


# ── 4. Upstream-missing guard ─────────────────────────────────────────────────

class TestUpstreamMissingGuard:
    @pytest.mark.asyncio
    async def test_s2_required_raises_when_s2_absent(self):
        """
        Simulates S3 reading context before S2 completed — should raise RunContextValidationError.
        """
        from api.schemas.run_context import RunContextValidationError
        from api.services.run_context_db import get_run_context_validated

        row = {
            "run_id": "dddddddd-0000-0000-0000-000000000001",
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "brand_brief": json.dumps({"cadence_weeks": 12}),
            "s1_keywords_used": json.dumps(["vietnam tours"]),
            "s2_keyword_research": None,   # S2 not yet run
            "s2_visibility_report": None,
            "s2_keyword_clusters": None,
            "s2_market_preference": None,
            "s2_aa_tour_matches": None,
            "s2_confidence_score": None,
            "s3_content_calendar": None,
            "s3_ads_plan": None,
            "s3_funnel_mix": None,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with pytest.raises(RunContextValidationError) as exc_info:
            await get_run_context_validated(
                conn,
                "dddddddd-0000-0000-0000-000000000001",
                require_stages=("s2",),
            )

        err = exc_info.value
        assert err.run_id == "dddddddd-0000-0000-0000-000000000001"
        assert "s2_" in err.missing_path

    def test_run_context_require_method_raises_for_missing_field(self):
        from api.schemas.run_context import RunContext, RunContextValidationError

        ctx = RunContext(
            run_id="run-abc",
            tenant_id="tenant-1",
            s2_keyword_research=None,  # absent
        )

        with pytest.raises(RunContextValidationError) as exc_info:
            ctx.require("s2_keyword_research")

        assert exc_info.value.missing_path == "s2_keyword_research"

    def test_run_context_require_passes_when_field_present(self):
        from api.schemas.run_context import RunContext

        ctx = RunContext(
            run_id="run-def",
            tenant_id="tenant-1",
            s2_keyword_research={"top_opportunities": ["test"]},
            s2_visibility_report={"summary": "ok"},
            s2_confidence_score=0.85,
        )
        # should not raise
        ctx.require("s2_keyword_research", "s2_visibility_report", "s2_confidence_score")


# ── 5. write_run_context_stage — unknown stage ────────────────────────────────

class TestWriteRunContextStageEdgeCases:
    @pytest.mark.asyncio
    async def test_unknown_stage_raises_value_error(self):
        from api.services.run_context_db import write_run_context_stage

        conn = AsyncMock()
        with pytest.raises(ValueError, match="Unknown stage"):
            await write_run_context_stage(conn, "run-1", "s99", {})

    @pytest.mark.asyncio
    async def test_invalid_s2_payload_raises_pydantic_error(self):
        from pydantic import ValidationError
        from api.services.run_context_db import write_run_context_stage

        conn = AsyncMock()
        with pytest.raises(ValidationError):
            await write_run_context_stage(conn, "run-1", "s2", {
                "s2_keyword_research": {},
                "s2_visibility_report": {},
                "s2_confidence_score": 99.9,  # invalid > 1.0
            })
