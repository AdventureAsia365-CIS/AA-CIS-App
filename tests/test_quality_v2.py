"""Tests for S4.2 v2 Quality Editor Pass (AA-145-C)."""
from unittest.mock import MagicMock

from services.acp_s4_social.quality import quality_pass
from services.acp_s4_social.brief import ContentBrief


def _brief(**kwargs):
    defaults = dict(
        brand="Adventure Asia",
        audience="senior professionals",
        channel="linkedin",
        goal="awareness",
        topic="Mekong tour",
        tone="calm",
        cta="Enquire now",
        goal_key="4",
        goal_name="Introduction / Awareness",
    )
    defaults.update(kwargs)
    return ContentBrief(**defaults)


def test_quality_pass_revises_content():
    payload = '{"revised_content": "Revised text.", "warnings": "", "passed": true}'
    llm_client = MagicMock(return_value=payload)
    result = quality_pass("Original draft.", _brief(), llm_client)
    assert result["revised_content"] == "Revised text."


def test_quality_pass_extracts_warnings():
    payload = (
        '{"revised_content": "Fixed.", '
        '"warnings": "Unverified claim about 5-star rating.", "passed": true}'
    )
    llm_client = MagicMock(return_value=payload)
    result = quality_pass("Draft with claim.", _brief(), llm_client)
    assert "Unverified claim" in result["warnings"]


def test_quality_pass_passed_flag_true():
    payload = '{"revised_content": "Clean copy.", "warnings": "", "passed": true}'
    llm_client = MagicMock(return_value=payload)
    result = quality_pass("Good draft.", _brief(), llm_client)
    assert result["passed"] is True


def test_quality_pass_invalid_json_graceful():
    llm_client = MagicMock(return_value="Sorry, I cannot help with that.")
    result = quality_pass("My draft.", _brief(), llm_client)
    assert result["revised_content"] == "My draft."
    assert result["passed"] is False


def test_quality_pass_uses_channel_in_prompt():
    payload = '{"revised_content": "ok", "warnings": "", "passed": true}'
    llm_client = MagicMock(return_value=payload)
    quality_pass("Some content.", _brief(channel="facebook"), llm_client)
    _system_arg, user_arg = llm_client.call_args[0]
    assert "facebook" in user_arg
