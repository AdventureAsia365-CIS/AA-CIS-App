"""Strategy validation gate for S4.2 Social Media Content Engine (AA-119)."""
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger(__name__)

REQUIRED_STRATEGY_FIELDS = ['hook', 'emotional_payoff', 'proof_elements', 'comparison_pain']


@dataclass
class StrategyValidationResult:
    is_valid: bool
    missing_fields: list[str] = field(default_factory=list)
    empty_fields: list[str] = field(default_factory=list)


def validate_strategy(strategy: dict, tour_id: str = '') -> StrategyValidationResult:
    missing = [f for f in REQUIRED_STRATEGY_FIELDS if f not in strategy]
    empty = [
        f for f in REQUIRED_STRATEGY_FIELDS
        if f in strategy and not str(strategy.get(f, '') or '').strip()
    ]
    is_valid = len(missing) == 0 and len(empty) == 0
    if not is_valid:
        logger.warning(
            "strategy_validation_failed",
            tour_id=tour_id,
            missing_fields=missing,
            empty_fields=empty,
        )
    return StrategyValidationResult(is_valid=is_valid, missing_fields=missing, empty_fields=empty)


def should_skip_tour(
    result: StrategyValidationResult,
    attempt: int,
    max_attempts: int = 1,
) -> bool:
    return not result.is_valid and attempt >= max_attempts
