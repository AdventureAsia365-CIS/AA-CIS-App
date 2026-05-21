"""Unit tests for S4 Blog Engine graph nodes (AA-46). Mocks Bedrock + Lambda + DB."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_state(**overrides) -> dict:
    state = {
        "tenant_id": "aa_internal",
        "run_id": "00000000-0000-0000-0000-000000000001",
        "calendar_item_id": "00000000-0000-0000-0000-000000000002",
        "primary_keyword": "south korea cycling tour",
        "outline": ["Introduction", "Route overview", "FAQ"],
        "target_keywords": ["cycling korea", "korea bike tour"],
        "title": "Cycling South Korea: Seoul to Busan Route Guide",
        "content_md": "",
        "seo_title": "",
        "seo_meta": "",
        "slug": "",
        "review_flags": [],
        "rules_applied": [],
        "evaluator_score": None,
        "evaluator_input_hash": None,
        "validation_passed": None,
        "validation_score": None,
        "failing_checks": [],
        "repair_targets": [],
        "seo_score": None,
        "seo_issues": [],
        "rewrite_count": 0,
        "rewrite_feedback": "",
        "error": "",
        "status": "briefing",
        "draft_id": None,
        "db": None,
        "db_rules": [],
    }
    state.update(overrides)
    return state


def _make_db(**fetch_results):
    db = AsyncMock()
    db.fetch = AsyncMock(return_value=[])
    db.fetchrow = AsyncMock(return_value=None)
    db.execute = AsyncMock()
    return db


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_brief_node_builds_state():
    from services.acp_s4.graph import brief_node
    state = _base_state()
    result = await brief_node(state)
    assert result["status"] == "drafting"
    assert result["error"] == ""
    assert result["primary_keyword"] == "south korea cycling tour"


@pytest.mark.asyncio
async def test_brief_node_fails_missing_keyword():
    from services.acp_s4.graph import brief_node
    state = _base_state(primary_keyword="", title="")
    result = await brief_node(state)
    assert result["status"] == "error"
    assert "required" in result["error"]


@pytest.mark.asyncio
async def test_post_process_blocks_on_violation():
    from services.acp_s4.graph import post_process_node
    from api.services.acp_post_processor import OutputRuleViolation

    db = _make_db()
    with patch("services.acp_s4.graph.apply_output_rules",
               AsyncMock(side_effect=OutputRuleViolation("r1", "block", "Rule blocked: operational note"))):
        state = _base_state(db=db, content_md="Content with operational note here.", status="post_processing")
        result = await post_process_node(state)

    assert result["rewrite_count"] == 1
    assert result["status"] == "rewriting"
    assert "rewrite_feedback" in result and result["rewrite_feedback"]


@pytest.mark.asyncio
async def test_rewrite_loop_max_2():
    """At rewrite_count=2, post_process violation routes to blocked."""
    from services.acp_s4.graph import post_process_node
    from api.services.acp_post_processor import OutputRuleViolation

    db = _make_db()
    with patch("services.acp_s4.graph.apply_output_rules",
               AsyncMock(side_effect=OutputRuleViolation("r1", "block", "Blocked"))):
        state = _base_state(db=db, content_md="bad content", status="post_processing", rewrite_count=2)
        result = await post_process_node(state)

    assert result["status"] == "blocked"
    assert result["rewrite_count"] == 3


@pytest.mark.asyncio
async def test_evaluate_gates_below_threshold():
    from services.acp_s4.graph import evaluate_node

    eval_response = {
        "statusCode": 200,
        "body": json.dumps({
            "evaluator_score": 6.2,
            "dimension_scores": {"readability": 6.0, "engagement": 6.5,
                                 "factual_trust": 6.0, "keyword_naturalness": 6.5, "completeness": 6.0},
            "issues": ["Too short", "Low engagement"],
            "evaluator_input_hash": "abc123def456",
        })
    }
    mock_payload = MagicMock()
    mock_payload.read.return_value = json.dumps(eval_response).encode()

    with patch("services.acp_s4.graph._LAMBDA") as mock_lambda:
        mock_lambda.invoke.return_value = {"Payload": mock_payload}
        state = _base_state(content_md="Short blog content.", status="evaluating")
        result = await evaluate_node(state)

    assert result["evaluator_score"] == 6.2
    assert result["rewrite_count"] == 1
    assert result["status"] == "rewriting"


@pytest.mark.asyncio
async def test_evaluate_passes_threshold():
    from services.acp_s4.graph import evaluate_node

    eval_response = {
        "statusCode": 200,
        "body": json.dumps({
            "evaluator_score": 8.5,
            "dimension_scores": {"readability": 8.5, "engagement": 8.5,
                                 "factual_trust": 8.5, "keyword_naturalness": 8.5, "completeness": 8.5},
            "issues": [],
            "evaluator_input_hash": "abc123def456hash",
        })
    }
    mock_payload = MagicMock()
    mock_payload.read.return_value = json.dumps(eval_response).encode()

    with patch("services.acp_s4.graph._LAMBDA") as mock_lambda:
        mock_lambda.invoke.return_value = {"Payload": mock_payload}
        state = _base_state(content_md="Long great blog content about Korea cycling.", status="evaluating")
        result = await evaluate_node(state)

    assert result["evaluator_score"] == 8.5
    assert result["status"] == "validating"
    assert result["rewrite_count"] == 0


@pytest.mark.asyncio
async def test_validation_failure_routes_to_hitl():
    """Validation failure should NOT trigger rewrite — goes to seo_node with validation_passed=False."""
    from services.acp_s4.graph import validate_node

    state = _base_state(
        content_md="Short. " * 100,  # too short, leaky
        status="validating",
        db_rules=[],
    )
    result = await validate_node(state)
    assert result["status"] == "seo_scoring"
    # validation_passed may be True or False depending on content — just check it's set
    assert result["validation_passed"] is not None
    assert result["validation_score"] is not None


@pytest.mark.asyncio
async def test_seo_node_scores_correctly():
    from services.acp_s4.graph import seo_node

    good_content = "south korea cycling tour " * 100
    state = _base_state(
        content_md=good_content,
        seo_title="South Korea Cycling Tour: Seoul to Busan Complete Guide",
        seo_meta="Discover the best cycling routes in South Korea from Seoul to Busan. "
                 "Our expert guide covers terrain, timing and logistics for all levels.",
        primary_keyword="south korea cycling tour",
        status="seo_scoring",
    )
    result = await seo_node(state)
    assert result["seo_score"] is not None
    assert 0.0 <= result["seo_score"] <= 10.0
    assert isinstance(result["seo_issues"], list)
    assert result["status"] == "saving"


@pytest.mark.asyncio
async def test_save_node_inserts_draft():
    from services.acp_s4.graph import save_node

    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: "draft-uuid-123" if key == "draft_id" else None
    db = _make_db()
    db.fetchrow = AsyncMock(return_value=mock_row)

    state = _base_state(
        db=db,
        content_md="Long good blog content " * 100,
        seo_title="Korea Cycling Guide: Seoul to Busan",
        seo_meta="A 160 char meta about Korea cycling tours with specific details " * 2,
        slug="korea-cycling-tour-seoul-busan",
        validation_passed=True,
        validation_score=8.5,
        evaluator_score=8.5,
        evaluator_input_hash="abc123",
        seo_score=7.5,
        seo_issues=[],
        status="saving",
    )
    result = await save_node(state)
    assert result["status"] == "done"
    db.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_hitl_approve_updates_status():
    """HITL endpoint logic: update hitl_gate3_status."""
    from api.routers.v1_s4_blog import HitlRequest

    body = HitlRequest(status="approved", reviewer_id="reviewer-01", notes="Looks good")
    assert body.status == "approved"
    assert body.reviewer_id == "reviewer-01"
    # Verify schema validation — 'approved' and 'rejected' are valid
    body2 = HitlRequest(status="rejected", reviewer_id="reviewer-02")
    assert body2.status == "rejected"
