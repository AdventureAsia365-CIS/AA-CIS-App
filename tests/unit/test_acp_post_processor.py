"""Unit tests for api/services/acp_post_processor.py (AA-49 H-2)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from api.services.acp_post_processor import apply_output_rules, OutputRuleViolation


class _Row(dict):
    """Minimal asyncpg Record mock — supports both dict[key] and .key access."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _make_rule(rule_id, rule_type, pattern, action_value=None, error_message=None, is_active=True):
    return _Row({
        "rule_id": rule_id,
        "rule_type": rule_type,
        "pattern": pattern,
        "action_value": action_value,
        "error_message": error_message or f"Rule {rule_id} violated",
        "is_active": is_active,
    })


def _make_db(rules):
    db = AsyncMock()
    db.fetch = AsyncMock(return_value=rules)
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_no_rules_returns_empty_metadata():
    db = _make_db([])
    output = {"content": "A great travel blog about cycling in Vietnam."}
    result = await apply_output_rules(output, stage="S4", tenant_id="00000000-0000-0000-0000-000000000001", db=db)
    assert result["review_flags"] == []
    assert result["rules_applied"] == []
    assert result["content"] == "A great travel blog about cycling in Vietnam."


@pytest.mark.asyncio
async def test_replace_rule_mutates_content():
    rules = [_make_rule("r1", "replace", "cheap", action_value="exceptional value")]
    db = _make_db(rules)
    output = {"content": "Get cheap tours today!"}
    result = await apply_output_rules(output, stage="S4", tenant_id="00000000-0000-0000-0000-000000000001", db=db)
    assert "exceptional value" in result["content"]
    assert "cheap" not in result["content"]
    assert "r1" in result["rules_applied"]


@pytest.mark.asyncio
async def test_block_rule_raises_violation():
    rules = [_make_rule("r2", "block", "book now", error_message="Avoid salesy CTAs")]
    db = _make_db(rules)
    output = {"content": "Come and book now!"}
    with pytest.raises(OutputRuleViolation) as exc_info:
        await apply_output_rules(output, stage="S4", tenant_id="00000000-0000-0000-0000-000000000001", db=db)
    assert exc_info.value.rule_id == "r2"
    assert exc_info.value.rule_type == "block"


@pytest.mark.asyncio
async def test_flag_rule_adds_to_review_flags():
    rules = [_make_rule("r3", "flag", "discount", error_message="Brand voice: avoid discount")]
    db = _make_db(rules)
    output = {"content": "Enjoy our seasonal discount on tours."}
    result = await apply_output_rules(output, stage="S4", tenant_id="00000000-0000-0000-0000-000000000001", db=db)
    assert len(result["review_flags"]) == 1
    assert result["review_flags"][0]["rule_id"] == "r3"
    assert "r3" in result["rules_applied"]
    assert result["content"] == "Enjoy our seasonal discount on tours."


@pytest.mark.asyncio
async def test_non_matching_rule_not_applied():
    rules = [_make_rule("r4", "replace", "cheap", action_value="premium")]
    db = _make_db(rules)
    output = {"content": "This tour is affordable and enjoyable."}
    result = await apply_output_rules(output, stage="S4", tenant_id="00000000-0000-0000-0000-000000000001", db=db)
    assert result["rules_applied"] == []
    assert result["review_flags"] == []


@pytest.mark.asyncio
async def test_pattern_matching_is_case_insensitive():
    rules = [_make_rule("r5", "replace", "Cheap", action_value="excellent")]
    db = _make_db(rules)
    output = {"content_md": "This is CHEAP travel."}
    result = await apply_output_rules(output, stage="S4", tenant_id="00000000-0000-0000-0000-000000000001", db=db)
    assert "r5" in result["rules_applied"]


@pytest.mark.asyncio
async def test_run_count_incremented_on_trigger():
    rules = [_make_rule("r6", "flag", "discount")]
    db = _make_db(rules)
    output = {"content": "Get a discount on your next adventure."}
    await apply_output_rules(output, stage="S4", tenant_id="00000000-0000-0000-0000-000000000001", db=db)
    db.execute.assert_called_once()
    call_args = db.execute.call_args[0]
    assert "run_count" in call_args[0]
    assert "r6" in call_args[1]
