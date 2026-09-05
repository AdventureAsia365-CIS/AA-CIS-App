"""AA-526 — atomize moves to A3 (services/export/handler.py::process_export()), owner_scope=
'platform', replacing the removed per-tenant trigger (api/routers/v1_tours.py's now-deleted
atomize_version() endpoint). Covers:

  1. process_export() launches _run_a3_atomize_background() as a real, referenced background
     task (strong-ref pattern) right after a tour is marked 'published' — not awaited inline,
     so a slow multi-day atomize run never adds latency to the admin action that calls
     process_export() directly.
  2. _run_a3_atomize_background() itself: calls run_t5_atomize() with owner_scope='platform'
     (not a tenant UUID) and the right `rewritten` shape built from generated_content's own
     columns. Deliberately does NOT also run Segment-matching here (a real bug this build found
     mid-session and reverted — see run_segment_matching()'s own updated docstring: Segments
     stay a per-tenant product, a real FK to shared.tenants, so a "platform"-scoped Segment is
     both an FK violation and invisible to every tenant's own ranking read either way).
  3. _SingleConnAsPool — the thin adapter that lets run_t5_atomize()'s pool.acquire() calls work
     against a single bare asyncpg.Connection.
  4. _llm_log_tenant_id() (services/acp_produce/tenant_pipeline.py) — the real bug this build
     found: record_call_with_pool()'s tenant_id is cast `$1::uuid`, so passing the literal string
     "platform" straight through (as every pre-AA-526 caller's real tenant UUID always did
     safely) would silently fail that INSERT on every single atomize LLM call.
  5. services/acp_contract/segment_matching.py::run_segment_matching()'s atom-read query — the
     OTHER real bug this build found: it used to read `WHERE owner_scope = $1` (a real tenant
     UUID) only, which would find ZERO atoms for any tour rewritten after atoms moved to
     owner_scope='platform' at A3 — silently breaking Segment/Route/Ranking for all future
     content. Fixed to also match platform-scope atoms whose tour this tenant has actually
     picked/rewritten, and re-wired into _run_ranking_pipeline() (api/routers/v1_tours.py),
     which now runs it FIRST, same ordering the removed atomize_version() endpoint used.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_produce.tenant_pipeline import _llm_log_tenant_id
from services.export import handler as export_handler

TOUR_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
GC_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class TestLlmLogTenantId:
    def test_real_tenant_uuid_passed_through(self):
        real_id = str(uuid.uuid4())
        assert _llm_log_tenant_id(real_id) == real_id

    def test_platform_scope_returns_none(self):
        """The actual gap this build found: "platform" is not a valid ::uuid literal —
        record_call_with_pool() would otherwise silently fail every single A3 atomize LLM
        call's cost/usage log (caught by that function's own try/except, but a real, avoidable
        loss of visibility on a stage that now runs on every published tour)."""
        assert _llm_log_tenant_id("platform") is None

    def test_none_input_returns_none(self):
        assert _llm_log_tenant_id(None) is None


@pytest.mark.asyncio
class TestAtomizeSkipsCompetitorIndexForNonTenantScope:
    """AA-526 — the real bug this build's OWN live-verify caught (unit tests alone missed it,
    since every existing test mocks build_competitor_index rather than exercising its real
    ::uuid cast): services/acp_shared/competitor_index.py's queries cast `tenant_id = $1::uuid`
    — genuinely tenant-only by that module's own docstring (never wired for platform-scope
    atoms). Calling run_t5_atomize("platform", ...) crashed this on every single call, before
    a single atom was ever inserted. Confirmed live (05/09/2026, real HTTP admin approve -> real
    process_export() -> real a3_atomize_failed log: "invalid input for query argument $1:
    'platform' (invalid UUID...)"). Fixed by skipping the fetch for a non-tenant owner_scope."""

    async def test_atomize_per_day_skips_competitor_fetch_for_platform_scope(self):
        from services.acp_produce import tenant_pipeline
        from services.content_generation.itinerary_utils import parse_canonical_itinerary_days

        row = {
            "id": TOUR_ID, "name": "Tour", "aa_summary": "s", "aa_highlights": [],
            "itinerary_source": "Day 1 — Arrive\nWalk around the old town.",
        }
        days = parse_canonical_itinerary_days(row["itinerary_source"])
        assert days  # sanity — real parse, not empty

        conn = AsyncMock()
        conn.fetch.return_value = []  # atomize_day_fingerprint: nothing cached yet
        conn.execute = AsyncMock(return_value="UPDATE 0")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        fake_llm_result = MagicMock(
            text='{"atoms": []}', model_used="sonnet", usage={}, stop_reason="end_turn",
        )
        with patch("services.acp_produce.tenant_pipeline.invoke_claude", return_value=fake_llm_result), \
             patch("services.acp_produce.tenant_pipeline.get_stage_config",
                   AsyncMock(return_value=MagicMock(model_id="sonnet", account_route="acc3"))), \
             patch("services.acp_shared.competitor_index.build_competitor_index", AsyncMock()) as m_build, \
             patch("shared.llm_client.call_log.record_call_with_pool", AsyncMock()):
            result = await tenant_pipeline._atomize_per_day(
                "platform", TOUR_ID, GC_ID, row, days, "somehash", pool, "Vietnam",
            )

        m_build.assert_not_awaited()  # the actual regression guard
        assert result["status"] == "success"

    async def test_atomize_whole_tour_legacy_skips_competitor_fetch_for_platform_scope(self):
        from services.acp_produce import tenant_pipeline

        conn = AsyncMock()
        conn.fetchval.return_value = None  # no prior source_hash
        conn.execute = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        fake_llm_result = MagicMock(
            text='{"atoms": [{"place": "Old town", "action": "walk"}]}',
            model_used="sonnet", usage={}, stop_reason="end_turn",
        )
        row = {"id": TOUR_ID, "name": "Tour", "aa_summary": "s", "aa_highlights": [],
               "itinerary_source": ""}
        with patch("services.acp_produce.tenant_pipeline.invoke_claude", return_value=fake_llm_result), \
             patch("services.acp_produce.tenant_pipeline.get_stage_config",
                   AsyncMock(return_value=MagicMock(model_id="sonnet", account_route="acc3"))), \
             patch("services.acp_shared.competitor_index.build_competitor_index", AsyncMock()) as m_build, \
             patch("shared.llm_client.call_log.record_call_with_pool", AsyncMock()):
            result = await tenant_pipeline._atomize_whole_tour_legacy(
                "platform", TOUR_ID, row, "somehash", pool, "Vietnam",
            )

        m_build.assert_not_awaited()  # the actual regression guard
        assert result["status"] == "success"
        assert result["atom_count"] == 1


@pytest.mark.asyncio
class TestSegmentMatchingReadsSharedAtoms:
    """AA-526 — services/acp_contract/segment_matching.py::run_segment_matching()'s atom-read
    query, the real bug this build found and fixed: it used to read `WHERE owner_scope = $1`
    only (a real tenant UUID) — once atomize moved to A3 (owner_scope='platform'), that query
    would find ZERO atoms for every tour rewritten after this ships, silently breaking Segment/
    Route/Ranking for all future content. Fixed to match legacy owner_scope=tenant_id atoms
    (any pre-AA-526 row, kept working) OR owner_scope='platform' atoms whose tour this tenant
    has actually picked/rewritten (via tenant_tour_versions) — not indiscriminately every
    platform atom for every tenant."""

    async def test_query_matches_legacy_owner_scope_or_platform_scoped_own_tours(self):
        from services.acp_contract import segment_matching

        conn = AsyncMock()
        # Only the atom-read query (this test's real subject) needs a real return — bail out
        # right after via a sentinel on the SECOND conn.fetch call (assigned_rows) so the write
        # phase below (its own transaction/UPSERT machinery, unit-tested elsewhere) never runs.
        conn.fetch.side_effect = [[], RuntimeError("stop here — not under test")]
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=ctx)

        tenant_id = str(uuid.uuid4())
        with pytest.raises(RuntimeError, match="stop here"):
            await segment_matching.run_segment_matching(tenant_id, pool)

        atom_query, *params = conn.fetch.call_args_list[0][0]
        assert "owner_scope = $1" in atom_query
        assert "owner_scope = 'platform'" in atom_query
        assert "tenant_tour_versions" in atom_query  # scoped to THIS tenant's own picked tours
        assert params == [tenant_id]


@pytest.mark.asyncio
class TestSingleConnAsPool:
    async def test_acquire_yields_the_same_connection_every_time(self):
        conn = object()
        pool = export_handler._SingleConnAsPool(conn)
        async with pool.acquire() as c1:
            assert c1 is conn
        async with pool.acquire() as c2:
            assert c2 is conn


@pytest.mark.asyncio
class TestRunA3AtomizeBackground:
    async def test_calls_run_t5_atomize_with_platform_owner_scope(self):
        conn = AsyncMock()
        conn.close = AsyncMock()
        rewritten = {"name": "Tour", "summary": "s", "highlights": "[]", "itineraries": "Day 1..."}

        with patch("services.export.handler.asyncpg.connect", AsyncMock(return_value=conn)), \
             patch("services.export.handler.get_database_url", MagicMock(return_value="postgresql://fake")), \
             patch(
                 "services.acp_produce.tenant_pipeline.run_t5_atomize",
                 AsyncMock(return_value={"status": "success", "atom_count": 3}),
             ) as m_atomize:
            await export_handler._run_a3_atomize_background(
                tour_id=TOUR_ID, rewritten=rewritten, country="Vietnam", version_id=GC_ID,
            )

        m_atomize.assert_awaited_once()
        args, kwargs = m_atomize.call_args
        assert args[0] == "platform"  # owner_scope — NOT a tenant UUID
        assert args[1] == TOUR_ID
        assert args[2] == rewritten
        assert kwargs["country"] == "Vietnam"
        assert kwargs["version_id"] == GC_ID
        conn.close.assert_awaited_once()

    async def test_atomize_failure_is_swallowed_never_raises(self):
        """Best-effort by design — a real atomize/DB error here must never propagate (this task
        is fire-and-forget, launched from process_export() with nothing awaiting it that could
        handle an exception)."""
        conn = AsyncMock()
        conn.close = AsyncMock()

        with patch("services.export.handler.asyncpg.connect", AsyncMock(return_value=conn)), \
             patch("services.export.handler.get_database_url", MagicMock(return_value="postgresql://fake")), \
             patch(
                 "services.acp_produce.tenant_pipeline.run_t5_atomize",
                 AsyncMock(side_effect=RuntimeError("boom")),
             ):
            await export_handler._run_a3_atomize_background(
                tour_id=TOUR_ID, rewritten={}, country="", version_id=GC_ID,
            )  # must not raise

        conn.close.assert_awaited_once()  # connection still cleaned up on the failure path


@pytest.mark.asyncio
class TestRunRankingPipelineRunsSegmentMatchingFirst:
    """AA-526 — api/routers/v1_tours.py::_run_ranking_pipeline() (moved here from the removed
    atomize_version() endpoint) must run Segment-matching FIRST, same ordering the old endpoint
    used — research/ranking below has nothing real to read until this tenant's Segments are
    current for whatever tour they just rewrote."""

    async def test_segment_matching_runs_before_research_and_ranking(self):
        from api.routers import v1_tours

        call_order = []
        pool = MagicMock()

        async def fake_segment_matching(tenant_id, _pool):
            call_order.append("segment_matching")
            return {"status": "success"}

        async def fake_segment_research(tenant_id, market, _pool):
            call_order.append("segment_research")
            return {"status": "success"}

        async def fake_atom_ranking(tenant_id, markets, _pool):
            call_order.append("atom_ranking")
            return {"status": "success"}

        async def fake_route_detection(tenant_id, _pool):
            call_order.append("route_detection")
            return {"status": "success"}

        fake_cfg = MagicMock(target_market={"country": "Vietnam"})
        with patch("services.acp_contract.segment_matching.run_segment_matching", fake_segment_matching), \
             patch("services.acp_contract.segment_research.run_segment_research", fake_segment_research), \
             patch("services.acp_contract.atom_ranking.run_atom_ranking", fake_atom_ranking), \
             patch("services.acp_contract.route_detection.run_route_detection", fake_route_detection), \
             patch("shared.services.tenant_config_service.TenantConfigService") as MockCfgSvc, \
             patch("services.seo_intelligence.seed_builder.resolve_buyer_markets", MagicMock(return_value=[])):
            MockCfgSvc.return_value.get_seo_config = AsyncMock(return_value=fake_cfg)
            await v1_tours._run_ranking_pipeline("some-tenant-id", pool)

        assert call_order == ["segment_matching", "segment_research", "atom_ranking", "route_detection"]


@pytest.mark.asyncio
class TestProcessExportLaunchesAtomize:
    async def test_atomize_task_scheduled_with_strong_ref_after_publish(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
        """process_export() must schedule the A3 atomize task (not await it inline — see the
        module docstring for why) and hold a strong reference to it (same GC-safety guard every
        other fire-and-forget task in this codebase uses)."""
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            {
                "id": GC_ID, "tour_id": TOUR_ID, "tenant_id": TOUR_ID, "batch_id": None,
                "aa_name": "Tour", "aa_subtitle": "s", "aa_summary": "sum", "aa_description": "d",
                "aa_highlights": "[]", "aa_itineraries": "Day 1...", "mobile_card_text": None,
                "seo_title": "t", "seo_meta": "m" * 150, "seo_keywords_used": "[]", "og_tags": "{}",
                "quality_score_id": None, "quality_score": 9.0,
                "country": "Vietnam", "duration": "5 days",
            },
            {"id": GC_ID},
        ]
        conn.execute = AsyncMock()
        conn.close = AsyncMock()

        with patch("services.export.handler.asyncpg.connect", AsyncMock(return_value=conn)), \
             patch("services.export.handler._run_a3_atomize_background", AsyncMock()) as m_atomize_bg:
            before = set(export_handler._background_tasks)
            await export_handler.process_export(GC_ID)
            new_tasks = export_handler._background_tasks - before
            assert len(new_tasks) == 1
            await next(iter(new_tasks))  # drain it so nothing is left pending

        m_atomize_bg.assert_awaited_once()
        kwargs = m_atomize_bg.call_args.kwargs
        assert kwargs["tour_id"] == TOUR_ID
        assert kwargs["version_id"] == GC_ID  # generated_content.id, this tour's real version
        assert kwargs["country"] == "Vietnam"
        assert kwargs["rewritten"]["name"] == "Tour"
