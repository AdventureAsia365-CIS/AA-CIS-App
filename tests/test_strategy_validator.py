"""Tests for strategy validation gate (AA-119)."""
from services.acp_shared.strategy_validator import (
    validate_strategy,
    should_skip_tour,
    StrategyValidationResult,
)

VALID_STRATEGY = {
    'hook': 'Escape the boardroom',
    'emotional_payoff': 'Feel alive again',
    'proof_elements': 'Himalayan expedition leaders since 1998',
    'comparison_pain': 'Generic tours leave you empty',
}


def test_valid_strategy_all_fields():
    result = validate_strategy(VALID_STRATEGY, tour_id='tour-1')
    assert result.is_valid is True
    assert result.missing_fields == []
    assert result.empty_fields == []


def test_missing_one_field():
    strategy = {k: v for k, v in VALID_STRATEGY.items() if k != 'hook'}
    result = validate_strategy(strategy, tour_id='tour-2')
    assert result.is_valid is False
    assert result.missing_fields == ['hook']
    assert result.empty_fields == []


def test_missing_multiple_fields():
    strategy = {k: v for k, v in VALID_STRATEGY.items()
                if k not in ('hook', 'emotional_payoff')}
    result = validate_strategy(strategy, tour_id='tour-3')
    assert result.is_valid is False
    assert len(result.missing_fields) == 2
    assert 'hook' in result.missing_fields
    assert 'emotional_payoff' in result.missing_fields


def test_empty_string_field():
    strategy = {**VALID_STRATEGY, 'hook': ''}
    result = validate_strategy(strategy, tour_id='tour-4')
    assert result.is_valid is False
    assert result.empty_fields == ['hook']
    assert result.missing_fields == []


def test_whitespace_only_field():
    strategy = {**VALID_STRATEGY, 'hook': '   '}
    result = validate_strategy(strategy, tour_id='tour-5')
    assert result.is_valid is False
    assert result.empty_fields == ['hook']
    assert result.missing_fields == []


def test_none_value_field():
    strategy = {**VALID_STRATEGY, 'hook': None}
    result = validate_strategy(strategy, tour_id='tour-6')
    assert result.is_valid is False
    assert result.empty_fields == ['hook']
    assert result.missing_fields == []


def test_should_skip_after_max_attempts():
    result = StrategyValidationResult(is_valid=False, missing_fields=['hook'])
    assert should_skip_tour(result, attempt=1, max_attempts=1) is True


def test_should_not_skip_before_max_attempts():
    result = StrategyValidationResult(is_valid=False, missing_fields=['hook'])
    assert should_skip_tour(result, attempt=0, max_attempts=1) is False
