"""Tests for isolated quality evaluator (AA-120)."""
from unittest.mock import MagicMock
from services.acp_shared.quality_evaluator import (
    QualityScore,
    evaluate_quality,
    QUALITY_PASS_THRESHOLD,
)

_ALL_FOURS = (
    '{"hook_strength": 4, "specificity": 4, "cta_clarity": 4,'
    ' "brand_voice": 4, "audience_fit": 4}'
)
_ALL_TWOS = (
    '{"hook_strength": 2, "specificity": 2, "cta_clarity": 2,'
    ' "brand_voice": 2, "audience_fit": 2}'
)
_EXACT_THREE = (
    '{"hook_strength": 3, "specificity": 3, "cta_clarity": 3,'
    ' "brand_voice": 3, "audience_fit": 3}'
)
_BELOW_THREE = (
    '{"hook_strength": 2, "specificity": 3, "cta_clarity": 3,'
    ' "brand_voice": 3, "audience_fit": 3}'
)


def _mock_client(return_value: str) -> MagicMock:
    client = MagicMock()
    client.return_value = return_value
    return client


def test_passing_score():
    client = _mock_client(_ALL_FOURS)
    result = evaluate_quality('Great post', 'instagram', client)
    assert result.average == 4.0
    assert result.passed is True
    assert result.hook_strength == 4.0


def test_failing_score():
    client = _mock_client(_ALL_TWOS)
    result = evaluate_quality('Poor post', 'instagram', client)
    assert result.average == 2.0
    assert result.passed is False


def test_threshold_boundary_pass():
    client = _mock_client(_EXACT_THREE)
    result = evaluate_quality('Border post', 'facebook', client)
    assert result.average == QUALITY_PASS_THRESHOLD
    assert result.passed is True


def test_threshold_boundary_fail():
    client = _mock_client(_BELOW_THREE)
    result = evaluate_quality('Border post', 'facebook', client)
    assert result.average == 2.8
    assert result.passed is False


def test_invalid_json_returns_failed():
    client = _mock_client('not json at all')
    result = evaluate_quality('Some post', 'linkedin', client)
    assert result.passed is False
    assert result.average == 0.0


def test_from_dict_calculates_average():
    d = {
        'hook_strength': 5,
        'specificity': 3,
        'cta_clarity': 4,
        'brand_voice': 3,
        'audience_fit': 5,
    }
    result = QualityScore.from_dict(d)
    assert result.average == 4.0
    assert result.passed is True


def test_post_text_truncated_at_2000():
    long_text = 'x' * 3000
    client = _mock_client(_ALL_FOURS)
    evaluate_quality(long_text, 'tiktok', client)
    call_args = client.call_args
    user_prompt = call_args[0][1]
    assert 'x' * 2001 not in user_prompt
    assert 'x' * 2000 in user_prompt
