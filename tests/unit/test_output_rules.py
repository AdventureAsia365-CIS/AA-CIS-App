"""
AA-115 — Forbidden word enforcement: 20 deterministic test cases.

10 positive: MUST be caught (OutputRuleViolation raised or review_flags populated).
10 negative: MUST pass cleanly against the full seeded rule set.

All tests use in-memory mock rules — no DB required.
Rule set mirrors migration 020: 18 block rules + 4 flag rules.
"""
import pytest
from unittest.mock import AsyncMock

from api.services.acp_post_processor import apply_output_rules, OutputRuleViolation

TENANT = "00000000-0000-0000-0000-000000000001"


class _Row(dict):
    """Minimal asyncpg Record mock — supports both row["key"] and row.key."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _rule(rule_id, rule_type, pattern, action_value=None, error_message=None):
    return _Row({
        "rule_id": rule_id,
        "rule_type": rule_type,
        "pattern": pattern,
        "action_value": action_value,
        "error_message": error_message or f"Rule {rule_id} violated",
    })


def _db(rules):
    db = AsyncMock()
    db.fetch = AsyncMock(return_value=rules)
    db.execute = AsyncMock()
    return db


# Full rule set from migration 020 — injected into negative-case tests.
ALL_RULES = [
    # GROUP 1 — block (18 rules)
    _rule("b01", "block", "this section follows the calendar brief"),
    _rule("b02", "block", "operational note"),
    _rule("b03", "block", "verify provider details"),
    _rule("b04", "block", "trip of a lifetime"),
    _rule("b05", "block", "once in a lifetime"),
    _rule("b06", "block", "hidden gem"),
    _rule("b07", "block", "don't miss out"),
    _rule("b08", "block", "ultimate adventure"),
    _rule("b09", "block", "stunning"),
    _rule("b10", "block", "breathtaking"),
    _rule("b11", "block", "unforgettable"),
    _rule("b12", "block", "world-class"),
    _rule("b13", "block", "iconic"),
    _rule("b14", "block", "epic"),
    _rule("b15", "block", "calendar brief"),
    _rule("b16", "block", "brief outline"),
    _rule("b17", "block", "internal note"),
    _rule("b18", "block", "placeholder text"),
    # GROUP 2 — flag (4 rules)
    _rule("f01", "flag", "tour_id"),
    _rule("f02", "flag", "created_at"),
    _rule("f03", "flag", "updated_at"),
    _rule("f04", "flag", "from $"),
]


# ── Positive cases (MUST be caught) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_positive_stunning_breathtaking():
    """'stunning' is a block rule — raises immediately."""
    db = _db([_rule("b09", "block", "stunning")])
    with pytest.raises(OutputRuleViolation) as exc:
        await apply_output_rules(
            {"content": "The stunning temples are breathtaking"},
            stage=None, tenant_id=TENANT, db=db,
        )
    assert exc.value.rule_id == "b09"
    assert exc.value.rule_type == "block"


@pytest.mark.asyncio
async def test_positive_iconic_world_class():
    """'iconic' triggers before 'world-class' in list order."""
    db = _db([_rule("b13", "block", "iconic"), _rule("b12", "block", "world-class")])
    with pytest.raises(OutputRuleViolation) as exc:
        await apply_output_rules(
            {"content": "An iconic world-class experience"},
            stage=None, tenant_id=TENANT, db=db,
        )
    assert exc.value.rule_id == "b13"


@pytest.mark.asyncio
async def test_positive_hidden_gem():
    db = _db([_rule("b06", "block", "hidden gem")])
    with pytest.raises(OutputRuleViolation) as exc:
        await apply_output_rules(
            {"content": "Hidden gem of Southeast Asia"},
            stage=None, tenant_id=TENANT, db=db,
        )
    assert exc.value.rule_id == "b06"


@pytest.mark.asyncio
async def test_positive_dont_miss_out():
    db = _db([_rule("b07", "block", "don't miss out")])
    with pytest.raises(OutputRuleViolation) as exc:
        await apply_output_rules(
            {"content": "Don't miss out on this ultimate adventure"},
            stage=None, tenant_id=TENANT, db=db,
        )
    assert exc.value.rule_id == "b07"


@pytest.mark.asyncio
async def test_positive_trip_of_a_lifetime():
    db = _db([_rule("b04", "block", "trip of a lifetime")])
    with pytest.raises(OutputRuleViolation) as exc:
        await apply_output_rules(
            {"content": "trip of a lifetime experience"},
            stage=None, tenant_id=TENANT, db=db,
        )
    assert exc.value.rule_id == "b04"


@pytest.mark.asyncio
async def test_positive_epic_unforgettable():
    db = _db([_rule("b14", "block", "epic"), _rule("b11", "block", "unforgettable")])
    with pytest.raises(OutputRuleViolation) as exc:
        await apply_output_rules(
            {"content": "This is truly epic and unforgettable"},
            stage=None, tenant_id=TENANT, db=db,
        )
    assert exc.value.rule_id == "b14"


@pytest.mark.asyncio
async def test_positive_verify_provider_details():
    db = _db([_rule("b03", "block", "verify provider details")])
    with pytest.raises(OutputRuleViolation) as exc:
        await apply_output_rules(
            {"content": "verify provider details before booking"},
            stage=None, tenant_id=TENANT, db=db,
        )
    assert exc.value.rule_id == "b03"


@pytest.mark.asyncio
async def test_positive_calendar_brief():
    db = _db([_rule("b15", "block", "calendar brief")])
    with pytest.raises(OutputRuleViolation) as exc:
        await apply_output_rules(
            {"content": "calendar brief: day 1"},
            stage=None, tenant_id=TENANT, db=db,
        )
    assert exc.value.rule_id == "b15"


@pytest.mark.asyncio
async def test_positive_operational_note():
    db = _db([_rule("b02", "block", "operational note")])
    with pytest.raises(OutputRuleViolation) as exc:
        await apply_output_rules(
            {"content": "Operational note: check with supplier"},
            stage=None, tenant_id=TENANT, db=db,
        )
    assert exc.value.rule_id == "b02"


@pytest.mark.asyncio
async def test_positive_price_flag():
    """'from $' is a flag rule — adds to review_flags, does not raise."""
    db = _db([_rule("f04", "flag", "from $")])
    result = await apply_output_rules(
        {"content": "from $299 per person"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert len(result["review_flags"]) == 1
    assert result["review_flags"][0]["rule_id"] == "f04"
    assert result["review_flags"][0]["field_name"] == "content"


# ── Negative cases (MUST pass — no violation) ────────────────────────────────

@pytest.mark.asyncio
async def test_negative_temples_devotion():
    db = _db(ALL_RULES)
    result = await apply_output_rules(
        {"content": "The temples reflect centuries of devotion"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert result["review_flags"] == []
    assert result["rules_applied"] == []


@pytest.mark.asyncio
async def test_negative_guests_arrive():
    db = _db(ALL_RULES)
    result = await apply_output_rules(
        {"content": "Guests arrive at 08:00 for a guided walk"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert result["review_flags"] == []
    assert result["rules_applied"] == []


@pytest.mark.asyncio
async def test_negative_local_community():
    db = _db(ALL_RULES)
    result = await apply_output_rules(
        {"content": "The local community shaped this experience"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert result["review_flags"] == []
    assert result["rules_applied"] == []


@pytest.mark.asyncio
async def test_negative_journey_highlands():
    db = _db(ALL_RULES)
    result = await apply_output_rules(
        {"content": "A journey through the highlands"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert result["review_flags"] == []
    assert result["rules_applied"] == []


@pytest.mark.asyncio
async def test_negative_quiet_discovery():
    db = _db(ALL_RULES)
    result = await apply_output_rules(
        {"content": "Designed for those who seek quiet discovery"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert result["review_flags"] == []
    assert result["rules_applied"] == []


@pytest.mark.asyncio
async def test_negative_private_access():
    db = _db(ALL_RULES)
    result = await apply_output_rules(
        {"content": "Private access to restricted zones"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert result["review_flags"] == []
    assert result["rules_applied"] == []


@pytest.mark.asyncio
async def test_negative_senior_professionals():
    db = _db(ALL_RULES)
    result = await apply_output_rules(
        {"content": "Curated for senior professionals"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert result["review_flags"] == []
    assert result["rules_applied"] == []


@pytest.mark.asyncio
async def test_negative_patient_exploration():
    db = _db(ALL_RULES)
    result = await apply_output_rules(
        {"content": "The landscape rewards patient exploration"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert result["review_flags"] == []
    assert result["rules_applied"] == []


@pytest.mark.asyncio
async def test_negative_rafting_sections():
    db = _db(ALL_RULES)
    result = await apply_output_rules(
        {"content": "Rafting through remote river sections"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert result["review_flags"] == []
    assert result["rules_applied"] == []


@pytest.mark.asyncio
async def test_negative_traditional_market():
    db = _db(ALL_RULES)
    result = await apply_output_rules(
        {"content": "An afternoon at the traditional market"},
        stage=None, tenant_id=TENANT, db=db,
    )
    assert result["review_flags"] == []
    assert result["rules_applied"] == []
