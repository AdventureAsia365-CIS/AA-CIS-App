"""
Unit tests for AA-105 (deterministic confidence scorer) and AA-113 (circuit breaker).

Tests are pure unit tests — no DB, no AWS, no network required.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── AA-105: compute_confidence ────────────────────────────────────────────────

def test_full_score():
    """All signals present → max score 1.0."""
    from services.acp.s2.tools.confidence import compute_confidence

    score, dims = compute_confidence(
        keyword_count=25,
        competitor_count=4,
        cache_hit_rate=0.3,
        gsc_data=True,
    )
    assert score == 1.0
    assert dims["keywords"] == 0.40
    assert dims["competitors"] == 0.30
    assert dims["freshness"] == 0.20
    assert dims["gsc"] == 0.10


def test_partial_score():
    """Mid-range signals → 0.35."""
    from services.acp.s2.tools.confidence import compute_confidence

    score, dims = compute_confidence(
        keyword_count=15,
        competitor_count=2,
        cache_hit_rate=0.6,
        gsc_data=False,
    )
    assert score == 0.35
    assert dims["keywords"] == 0.20   # >= 10 but < 20
    assert dims["competitors"] == 0.15  # >= 1 but < 3
    assert dims["freshness"] == 0.0   # cache_hit_rate >= 0.5
    assert dims["gsc"] == 0.0


def test_zero_score():
    """No useful signals → 0.0."""
    from services.acp.s2.tools.confidence import compute_confidence

    score, dims = compute_confidence(
        keyword_count=5,
        competitor_count=0,
        cache_hit_rate=0.8,
        gsc_data=False,
    )
    assert score == 0.0
    assert dims["keywords"] == 0.0
    assert dims["competitors"] == 0.0
    assert dims["freshness"] == 0.0
    assert dims["gsc"] == 0.0


def test_score_boundary_keywords_at_10():
    from services.acp.s2.tools.confidence import compute_confidence
    score, dims = compute_confidence(keyword_count=10, competitor_count=0,
                                     cache_hit_rate=1.0, gsc_data=False)
    assert dims["keywords"] == 0.20


def test_score_boundary_keywords_at_20():
    from services.acp.s2.tools.confidence import compute_confidence
    score, dims = compute_confidence(keyword_count=20, competitor_count=0,
                                     cache_hit_rate=1.0, gsc_data=False)
    assert dims["keywords"] == 0.40


def test_score_boundary_cache_hit_rate_at_0_5():
    """Exactly 0.5 is NOT fresh (>= 0.5 → no bonus)."""
    from services.acp.s2.tools.confidence import compute_confidence
    _, dims = compute_confidence(keyword_count=0, competitor_count=0,
                                 cache_hit_rate=0.5, gsc_data=False)
    assert dims["freshness"] == 0.0


def test_score_boundary_one_competitor():
    from services.acp.s2.tools.confidence import compute_confidence
    _, dims = compute_confidence(keyword_count=0, competitor_count=1,
                                 cache_hit_rate=1.0, gsc_data=False)
    assert dims["competitors"] == 0.15


def test_score_boundary_three_competitors():
    from services.acp.s2.tools.confidence import compute_confidence
    _, dims = compute_confidence(keyword_count=0, competitor_count=3,
                                 cache_hit_rate=1.0, gsc_data=False)
    assert dims["competitors"] == 0.30


# ── AA-113: circuit breaker ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_fires():
    """expand_attempts=1 + keyword_count < 20 → gate1_override='manual_required' without API call."""
    from services.acp.s2.tools.expand_scope import make_expand_scope_node

    s3 = MagicMock()
    api_keys = {"DATAFORSEO_LOGIN": "login", "DATAFORSEO_PASSWORD": "pass"}
    node = make_expand_scope_node(s3, api_keys)

    state = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "country": "Vietnam",
        "keyword_count": 8,
        "expand_attempts": 1,
        "iteration": 1,
        "completed_tools": [],
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        result = await node(state)
        # Circuit breaker must fire without calling the API
        mock_client_cls.assert_not_called()

    assert result["gate1_override"] == "manual_required"
    assert result["data_quality"] == "low"
    assert "expand_scope" in result["completed_tools"]


@pytest.mark.asyncio
async def test_circuit_breaker_not_fired_when_threshold_met():
    """keyword_count >= 20 → skip expand entirely, no gate1_override."""
    from services.acp.s2.tools.expand_scope import make_expand_scope_node

    s3 = MagicMock()
    node = make_expand_scope_node(s3, {})

    state = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "country": "Thailand",
        "keyword_count": 25,
        "expand_attempts": 0,
        "iteration": 0,
        "completed_tools": [],
    }
    result = await node(state)
    assert result.get("gate1_override") is None
    assert result.get("data_quality") is None


@pytest.mark.asyncio
async def test_expand_sets_gate1_override_when_still_below_threshold():
    """First expand but API returns 0 extra → new_count < 20 → gate1_override set."""
    from services.acp.s2.tools.expand_scope import make_expand_scope_node

    s3 = MagicMock()
    api_keys = {"DATAFORSEO_LOGIN": "l", "DATAFORSEO_PASSWORD": "p"}
    node = make_expand_scope_node(s3, api_keys)

    state = {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "country": "Laos",
        "keyword_count": 5,
        "expand_attempts": 0,
        "iteration": 0,
        "completed_tools": [],
    }

    empty_response = {"tasks": [{"result": [{"items": []}]}]}
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=empty_response)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_client

        result = await node(state)

    assert result["gate1_override"] == "manual_required"
    assert result["data_quality"] == "low"
    assert result["expand_attempts"] == 1


# ── Gate 1 auto-approve block ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate1_override_blocks_autoapprove():
    """score=0.90 + gate1_override='manual_required' → auto_approve=False."""
    from services.acp.s2.router import _handle_gate1

    AA_INTERNAL_ID = "00000000-0000-0000-0000-000000000001"

    # Mock run_context returning high confidence but gate1_override set
    mock_ctx = MagicMock()
    mock_ctx.s2_confidence_score = 0.90
    mock_ctx.s2_visibility_report = {"gate1_override": "manual_required"}

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=MagicMock())  # non-None row
    conn.execute = AsyncMock()

    ctx_mgr = AsyncMock()
    ctx_mgr.__aenter__ = AsyncMock(return_value=conn)
    ctx_mgr.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx_mgr)

    with patch(
        "services.acp.s2.router.get_run_context_validated",
        AsyncMock(return_value=mock_ctx),
    ):
        result = await _handle_gate1(pool, "00000000-0000-0000-0000-000000000099", AA_INTERNAL_ID)

    assert result["auto_approved"] is False
    assert result["gate1_override"] == "manual_required"
    assert result["next"] == "await_manual_approval"


@pytest.mark.asyncio
async def test_gate1_autoapproves_when_no_override():
    """score=0.90 + no gate1_override → aa_internal auto-approved."""
    from services.acp.s2.router import _handle_gate1

    AA_INTERNAL_ID = "00000000-0000-0000-0000-000000000001"

    mock_ctx = MagicMock()
    mock_ctx.s2_confidence_score = 0.90
    mock_ctx.s2_visibility_report = {"gate1_override": None}

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=MagicMock())
    conn.execute = AsyncMock()

    ctx_mgr = AsyncMock()
    ctx_mgr.__aenter__ = AsyncMock(return_value=conn)
    ctx_mgr.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx_mgr)

    with patch(
        "services.acp.s2.router.get_run_context_validated",
        AsyncMock(return_value=mock_ctx),
    ):
        result = await _handle_gate1(pool, "00000000-0000-0000-0000-000000000099", AA_INTERNAL_ID)

    assert result["auto_approved"] is True
    assert result["gate1_override"] is None
    assert result["next"] == "trigger_s3"
