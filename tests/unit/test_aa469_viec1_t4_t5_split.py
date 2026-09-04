"""AA-469 Việc 1 — split T4 (save to My Catalog) / T5 (atomize) into 2 independent triggers.

STEP0 (docs/claude_audit/AA-469-viec1-step0-t4-t5-split-investigation.md) confirmed the real
bug: run_t5_atomize() used to run UNCONDITIONALLY right after T4's UPDATE inside
trigger_rewrite()'s _do_rewrite_and_save() closure (api/routers/v1_tours.py) — including when
T3's QA gate failed both repair rounds and got auto-passed (qa_auto_passed=True, AA-436). This
file covers both halves of the fix:

  1. The closure no longer calls run_t5_atomize() at all, on EITHER the real-pass or the
     auto-pass path — driven end-to-end (mocks only at the LLM/DB boundary, same shape as
     test_aa445_t5_distinctiveness.py's pool fake) rather than asserted via source inspection,
     since the call site is a nested closure with no other seam to test through.
  2. The new standalone trigger, POST /v1/tours/versions/{version_id}/atomize
     (v1_tours.atomize_version), correctly reconstructs `rewritten`/`country` from just a
     version_id + tenant (the adapter STEP0 said was still needed — run_t5_atomize() itself is
     parameter-pure and unchanged, see test_aa445_t5_distinctiveness.py for its own coverage),
     gates on status, and is idempotent on a repeat call (inherits run_t5_atomize()'s own
     source_hash skip — no new dedupe logic needed at the endpoint level).
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.routers import v1_tours

TENANT_ID = "33333333-3333-3333-3333-333333333333"
TOUR_ID = "44444444-4444-4444-4444-444444444444"
PUBLISHED_TOUR_ID = "55555555-5555-5555-5555-555555555555"
VERSION_ID = "66666666-6666-6666-6666-666666666666"


def _pool_ctx(conn):
    """Same shape as test_aa445_t5_distinctiveness.py's _pool_ctx — pool.acquire() always
    returns the same async-context-manager wrapping the same conn (single-threaded asyncio,
    no concurrent acquires in this code path, so reusing one conn across every `async with
    pool.acquire()` block is faithful to real execution order)."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


class _FakeRequest:
    def __init__(self, pool):
        self.app = SimpleNamespace(state=SimpleNamespace(pool=pool))


PT_ROW = {
    "id": PUBLISHED_TOUR_ID, "tour_id": TOUR_ID, "aa_name": "Sapa Trek",
    "aa_subtitle": "Original subtitle", "aa_summary": "Original summary",
    "aa_description": "desc", "aa_highlights": [], "aa_itineraries": "",
    "seo_title": "st", "seo_meta": "sm", "seo_keywords_used": None,
    "country": "Vietnam", "duration": "3D2N",
}
EXISTING_SEO_ROW = {"top_keywords": "[]", "keyword_ideas": "[]", "people_also_ask": "[]"}
REWRITE_RESULT = {
    "status": "success",
    "generated": {
        "name": "Sapa Trek Reimagined", "subtitle": "New subtitle", "summary": "New summary",
        "highlights": ["h1"], "itineraries": "Day 1...", "seo_title": "New st",
        "seo_meta": "New sm", "trip_type": "trek",
    },
}


async def _drive_trigger_rewrite(qa_result: dict):
    """Calls the real trigger_rewrite() endpoint function, then awaits its fire-and-forget
    background task to completion — the only way to actually exercise
    _do_rewrite_and_save()'s closure body from outside."""
    conn = AsyncMock()
    conn.fetchrow.side_effect = [PT_ROW, None, EXISTING_SEO_ROW]        # pt, brand_rules(_br), seo(_existing)
    # AA-489: trigger_rewrite() now does 2 fetchval calls up front for the quota check
    # (_get_tenant_plan_limit's plan_tier SELECT, then the quota INSERT..RETURNING) before
    # any of the pre-existing calls below.
    conn.fetchval.side_effect = ["starter", 1, 1, VERSION_ID, 5.0]      # plan_tier, quota used,
    #                                                                     next_ver, INSERT id, source_score
    pool = _pool_ctx(conn)
    request = _FakeRequest(pool)
    tenant = {"sub": TENANT_ID}
    body = v1_tours.RewriteRequest(rewrite_language="en-US", seo_mode="standard")

    with patch("api.routers.v1_pipeline._rewrite_tour", AsyncMock(return_value=REWRITE_RESULT)) as m_rewrite, \
         patch("services.acp_produce.tenant_pipeline.run_t3_qa_gate", AsyncMock(return_value=qa_result)) as m_qa, \
         patch("services.acp_produce.tenant_pipeline.escalate_t3_failure", AsyncMock()) as m_escalate, \
         patch("services.acp_produce.tenant_pipeline.run_t5_atomize", AsyncMock()) as m_atomize:

        before = set(v1_tours._background_tasks)
        resp = await v1_tours.trigger_rewrite(PUBLISHED_TOUR_ID, body, request, tenant)
        new_tasks = v1_tours._background_tasks - before
        assert len(new_tasks) == 1, "trigger_rewrite() should schedule exactly 1 background task"
        await next(iter(new_tasks))

    return resp, conn, m_rewrite, m_qa, m_escalate, m_atomize


@pytest.mark.asyncio
async def test_real_qa_pass_does_not_auto_atomize():
    """Baseline: even a clean T3 pass no longer triggers T5 automatically — T4 (the UPDATE) is
    the real stopping point now."""
    qa_result = {
        "result": {**REWRITE_RESULT, "quality_score": 8.5},
        "passed": True, "attempts": 0, "structural_issues": [], "grounding_issues": [],
    }
    resp, conn, m_rewrite, m_qa, m_escalate, m_atomize = await _drive_trigger_rewrite(qa_result)

    assert resp["status"] == "pending"
    m_rewrite.assert_awaited_once()
    m_qa.assert_awaited_once()
    m_escalate.assert_not_awaited()
    m_atomize.assert_not_awaited()  # <- the actual AA-469 Việc 1 regression guard

    execute_calls = [c for c in conn.execute.call_args_list
                      if "UPDATE gold_aa_internal.tenant_tour_versions" in c.args[0]]
    assert len(execute_calls) == 1
    args = execute_calls[0].args
    assert args[2] == "ai_generated"   # new_status (score >= 7.0)
    assert args[6] is False            # qa_auto_passed


@pytest.mark.asyncio
async def test_qa_auto_pass_does_not_auto_atomize():
    """THE original bug's exact repro condition (STEP0): T3 exhausts both repair rounds
    (passed=False) and gets auto-passed (AA-436) — escalate_t3_failure() still fires (A4 must
    still see it), but run_t5_atomize() must NOT."""
    qa_result = {
        "result": {**REWRITE_RESULT, "quality_score": 6.0},
        "passed": False, "attempts": 2,
        "structural_issues": ["FORBIDDEN_WORD"], "grounding_issues": [],
    }
    resp, conn, m_rewrite, m_qa, m_escalate, m_atomize = await _drive_trigger_rewrite(qa_result)

    assert resp["status"] == "pending"
    m_escalate.assert_awaited_once()   # review_queue / A4 path unaffected by this fix
    m_atomize.assert_not_awaited()     # <- was unconditionally called pre-fix; must not be now

    execute_calls = [c for c in conn.execute.call_args_list
                      if "UPDATE gold_aa_internal.tenant_tour_versions" in c.args[0]]
    args = execute_calls[0].args
    assert args[2] == "needs_review"
    assert args[6] is True             # qa_auto_passed=True — the exact flag the bug ignored


# ── POST /versions/{id}/atomize — the new standalone trigger ──────────────────

def _atomize_row(status="ai_generated", inner_status="done", country="Vietnam"):
    return {
        "status": status,
        "rewritten_content": json.dumps({
            "name": "Sapa Trek Reimagined", "summary": "New summary",
            "highlights": ["h1"], "itineraries": "Day 1...", "status": inner_status,
        }),
        "tour_id": TOUR_ID, "country": country,
    }


@pytest.mark.asyncio
async def test_atomize_endpoint_success_calls_t5_with_reconstructed_args():
    conn = AsyncMock()
    conn.fetchrow.return_value = _atomize_row()
    pool = _pool_ctx(conn)
    request = _FakeRequest(pool)
    tenant = {"sub": TENANT_ID}

    with patch("services.acp_produce.tenant_pipeline.run_t5_atomize",
               AsyncMock(return_value={"status": "success", "atom_count": 3})) as m_atomize:
        resp = await v1_tours.atomize_version(VERSION_ID, request, tenant)

    m_atomize.assert_awaited_once()
    call_args = m_atomize.call_args.args
    assert call_args[0] == TENANT_ID
    assert call_args[1] == TOUR_ID
    assert call_args[2]["name"] == "Sapa Trek Reimagined"   # reconstructed `rewritten` dict
    assert m_atomize.call_args.kwargs["country"] == "Vietnam"
    assert resp["status"] == "success"
    assert resp["atom_count"] == 3
    assert resp["tour_id"] == TOUR_ID
    assert "atomized_at" in resp


@pytest.mark.asyncio
async def test_atomize_endpoint_404_when_not_owned_or_missing():
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    pool = _pool_ctx(conn)
    request = _FakeRequest(pool)
    tenant = {"sub": TENANT_ID}

    with pytest.raises(HTTPException) as exc_info:
        await v1_tours.atomize_version(VERSION_ID, request, tenant)
    assert exc_info.value.status_code == 404


@pytest.mark.parametrize("status", ["pending", "rejected"])
@pytest.mark.asyncio
async def test_atomize_endpoint_rejects_unfinished_or_discarded_status(status):
    conn = AsyncMock()
    conn.fetchrow.return_value = _atomize_row(status=status)
    pool = _pool_ctx(conn)
    request = _FakeRequest(pool)
    tenant = {"sub": TENANT_ID}

    with patch("services.acp_produce.tenant_pipeline.run_t5_atomize", AsyncMock()) as m_atomize:
        with pytest.raises(HTTPException) as exc_info:
            await v1_tours.atomize_version(VERSION_ID, request, tenant)
    assert exc_info.value.status_code == 409
    m_atomize.assert_not_awaited()


@pytest.mark.asyncio
async def test_atomize_endpoint_guards_against_placeholder_content():
    """Defense-in-depth: trigger_rewrite()'s except-block can leave status='needs_review'
    while rewritten_content is still the INITIAL placeholder (inner status='generating',
    written before T2 ever ran) — this must 409, not atomize garbage/empty content."""
    conn = AsyncMock()
    conn.fetchrow.return_value = _atomize_row(status="needs_review", inner_status="generating")
    pool = _pool_ctx(conn)
    request = _FakeRequest(pool)
    tenant = {"sub": TENANT_ID}

    with patch("services.acp_produce.tenant_pipeline.run_t5_atomize", AsyncMock()) as m_atomize:
        with pytest.raises(HTTPException) as exc_info:
            await v1_tours.atomize_version(VERSION_ID, request, tenant)
    assert exc_info.value.status_code == 409
    m_atomize.assert_not_awaited()


@pytest.mark.asyncio
async def test_atomize_endpoint_502_when_t5_fails():
    conn = AsyncMock()
    conn.fetchrow.return_value = _atomize_row()
    pool = _pool_ctx(conn)
    request = _FakeRequest(pool)
    tenant = {"sub": TENANT_ID}

    with patch("services.acp_produce.tenant_pipeline.run_t5_atomize",
               AsyncMock(return_value={"status": "failed", "error": "BedrockError: boom"})):
        with pytest.raises(HTTPException) as exc_info:
            await v1_tours.atomize_version(VERSION_ID, request, tenant)
    assert exc_info.value.status_code == 502
    assert "boom" in exc_info.value.detail


@pytest.mark.asyncio
async def test_atomize_endpoint_502_persists_escalation_to_review_queue():
    """AA-469 Việc 5 — the gap this endpoint's own comment used to flag ("Việc 5's future job")
    is closed: a T5 failure must now ALSO be persisted (escalate_t5_atomize_failure(), same
    silver_aa_internal.review_queue table/shape T3 already writes to and A4 already reads) —
    not just returned to the tenant as a 502, which is exactly what test_atomize_endpoint_502_
    when_t5_fails above already covered and is unaffected by this addition."""
    conn = AsyncMock()
    conn.fetchrow.return_value = _atomize_row()
    pool = _pool_ctx(conn)
    request = _FakeRequest(pool)
    tenant = {"sub": TENANT_ID}

    with patch("services.acp_produce.tenant_pipeline.run_t5_atomize",
               AsyncMock(return_value={"status": "failed", "error": "BedrockError: boom"})), \
         patch("services.acp_produce.tenant_pipeline.escalate_t5_atomize_failure",
               AsyncMock()) as m_escalate:
        with pytest.raises(HTTPException) as exc_info:
            await v1_tours.atomize_version(VERSION_ID, request, tenant)

    assert exc_info.value.status_code == 502
    m_escalate.assert_awaited_once()
    call_args = m_escalate.call_args.args
    assert call_args[0] is pool
    assert call_args[1] == TENANT_ID
    assert call_args[2] == TOUR_ID
    assert call_args[3] == VERSION_ID
    assert "boom" in call_args[4]


@pytest.mark.asyncio
async def test_atomize_endpoint_502_still_raised_if_escalation_write_itself_fails():
    """Best-effort: a broken review_queue INSERT (e.g. a transient DB error) must not hide the
    real atomize failure from the tenant — they still get their 502 either way."""
    conn = AsyncMock()
    conn.fetchrow.return_value = _atomize_row()
    pool = _pool_ctx(conn)
    request = _FakeRequest(pool)
    tenant = {"sub": TENANT_ID}

    with patch("services.acp_produce.tenant_pipeline.run_t5_atomize",
               AsyncMock(return_value={"status": "failed", "error": "BedrockError: boom"})), \
         patch("services.acp_produce.tenant_pipeline.escalate_t5_atomize_failure",
               AsyncMock(side_effect=RuntimeError("db down"))):
        with pytest.raises(HTTPException) as exc_info:
            await v1_tours.atomize_version(VERSION_ID, request, tenant)

    assert exc_info.value.status_code == 502
    assert "boom" in exc_info.value.detail


@pytest.mark.asyncio
async def test_atomize_endpoint_idempotent_on_repeat_call():
    """Calling twice on unchanged content: run_t5_atomize()'s own source_hash check (already
    covered by test_aa445_t5_distinctiveness.py / the module's own idempotency design) returns
    {"status": "skipped"} — this endpoint must pass that straight through, not error or retry."""
    conn = AsyncMock()
    conn.fetchrow.return_value = _atomize_row()
    pool = _pool_ctx(conn)
    request = _FakeRequest(pool)
    tenant = {"sub": TENANT_ID}

    with patch("services.acp_produce.tenant_pipeline.run_t5_atomize",
               AsyncMock(side_effect=[
                   {"status": "success", "atom_count": 3},
                   {"status": "skipped", "atom_count": 0},
               ])) as m_atomize:
        first = await v1_tours.atomize_version(VERSION_ID, request, tenant)
        second = await v1_tours.atomize_version(VERSION_ID, request, tenant)

    assert first["status"] == "success"
    assert second["status"] == "skipped"
    assert m_atomize.await_count == 2
