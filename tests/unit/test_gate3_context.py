"""Unit tests for Gate 3 retry context builder (AA-116)."""
import json
import pytest
from unittest.mock import AsyncMock, patch

from services.acp_s4.graph import _build_gate3_context, EVAL_THRESHOLD


# ── Pure function tests ───────────────────────────────────────────────────────

def test_gate3_context_built_correctly():
    """Three attempts with escalating scores → payload matches spec."""
    history = [
        {"attempt": 1, "score": 5.2, "issues": ["factual_accuracy", "brand_voice"]},
        {"attempt": 2, "score": 6.1, "issues": ["factual_accuracy"]},
        {"attempt": 3, "score": 6.8, "issues": ["brand_voice"]},
    ]
    ctx = _build_gate3_context(history, threshold=7.5)

    assert ctx is not None
    assert ctx["attempts"] == 3
    assert ctx["best_score"] == 6.8
    assert ctx["best_attempt"] == 3
    assert ctx["threshold"] == 7.5
    assert ctx["retry_history"] == history
    # failing_dimensions comes from last attempt
    assert ctx["failing_dimensions"] == ["brand_voice"]


def test_gate3_context_null_for_first_pass():
    """Single attempt that passed → gate3_context must be None."""
    history = [{"attempt": 1, "score": 8.1, "issues": []}]
    ctx = _build_gate3_context(history, threshold=7.5)
    assert ctx is None


def test_gate3_context_null_for_empty_history():
    ctx = _build_gate3_context([], threshold=7.5)
    assert ctx is None


def test_best_score_extracted():
    """best_score must be the max across all attempts, not the last."""
    history = [
        {"attempt": 1, "score": 7.2, "issues": ["clarity"]},
        {"attempt": 2, "score": 6.5, "issues": ["factual_accuracy"]},
    ]
    ctx = _build_gate3_context(history, threshold=7.5)

    assert ctx is not None
    assert ctx["best_score"] == 7.2
    assert ctx["best_attempt"] == 1


def test_failing_dims_from_last_attempt():
    """failing_dimensions must come from the last attempt, not the best."""
    history = [
        {"attempt": 1, "score": 5.0, "issues": ["factual_accuracy", "brand_voice"]},
        {"attempt": 2, "score": 4.5, "issues": ["seo_density"]},
    ]
    ctx = _build_gate3_context(history, threshold=7.5)

    assert ctx is not None
    # best is attempt 1 (5.0 > 4.5) but dims from last (attempt 2)
    assert ctx["best_attempt"] == 1
    assert ctx["failing_dimensions"] == ["seo_density"]


def test_single_failed_attempt_builds_context():
    """Single attempt that failed (circuit breaker with MAX_REWRITE=1) → context set."""
    history = [{"attempt": 1, "score": 4.0, "issues": ["too_short"]}]
    ctx = _build_gate3_context(history, threshold=7.5)

    assert ctx is not None
    assert ctx["attempts"] == 1
    assert ctx["best_score"] == 4.0


# ── evaluate_node integration tests ──────────────────────────────────────────

def _eval_payload(score: float, issues: list) -> dict:
    import json
    body = json.dumps({"evaluator_score": score, "evaluator_input_hash": "abc123", "issues": issues})
    return {"statusCode": 200, "body": body}


def _lambda_response(score: float, issues: list):
    import json
    from unittest.mock import MagicMock
    payload_bytes = json.dumps(_eval_payload(score, issues)).encode()
    mock_resp = MagicMock()
    mock_resp["Payload"].read.return_value = payload_bytes
    return mock_resp


@pytest.mark.asyncio
async def test_evaluate_node_records_score_history_on_pass():
    """evaluate_node records score even when first attempt passes."""
    from services.acp_s4.graph import evaluate_node

    base_state = {
        "status": "evaluating",
        "content_md": "A " * 200,
        "rewrite_count": 0,
        "score_history": [],
        "run_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "aa_internal",
        "evaluator_score": None,
        "evaluator_input_hash": None,
        "rewrite_feedback": "",
        "error": "",
    }

    lambda_body = json.dumps({"evaluator_score": 8.5, "evaluator_input_hash": "h1", "issues": []})
    mock_payload = {"statusCode": 200, "body": lambda_body}

    from unittest.mock import MagicMock
    mock_resp = MagicMock()
    mock_resp["Payload"].read.return_value = json.dumps(mock_payload).encode()

    with patch("services.acp_s4.graph._LAMBDA") as mock_lambda:
        mock_lambda.invoke.return_value = mock_resp
        result = await evaluate_node(base_state)

    assert result["status"] == "validating"
    assert len(result["score_history"]) == 1
    assert result["score_history"][0]["score"] == 8.5
    assert result["score_history"][0]["attempt"] == 1


@pytest.mark.asyncio
async def test_evaluate_node_appends_history_on_retry():
    """evaluate_node appends new entry to existing score_history on retry."""
    from services.acp_s4.graph import evaluate_node

    existing_history = [{"attempt": 1, "score": 5.2, "issues": ["clarity"]}]
    base_state = {
        "status": "evaluating",
        "content_md": "A " * 200,
        "rewrite_count": 1,
        "score_history": existing_history,
        "run_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "aa_internal",
        "evaluator_score": None,
        "evaluator_input_hash": None,
        "rewrite_feedback": "",
        "error": "",
    }

    lambda_body = json.dumps({
        "evaluator_score": 6.1,
        "evaluator_input_hash": "h2",
        "issues": ["brand_voice"],
    })
    mock_payload = {"statusCode": 200, "body": lambda_body}

    from unittest.mock import MagicMock
    mock_resp = MagicMock()
    mock_resp["Payload"].read.return_value = json.dumps(mock_payload).encode()

    with patch("services.acp_s4.graph._LAMBDA") as mock_lambda:
        mock_lambda.invoke.return_value = mock_resp
        result = await evaluate_node(base_state)

    assert len(result["score_history"]) == 2
    assert result["score_history"][1]["attempt"] == 2
    assert result["score_history"][1]["score"] == 6.1
