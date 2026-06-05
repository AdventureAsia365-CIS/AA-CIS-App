"""Tests for S4.2 v2 selective reference writer (AA-145-C)."""
from unittest.mock import MagicMock, patch

from services.acp_s4_social.writer import write_content, SKILL_V2_SYSTEM
from services.acp_s4_social.brief import ContentBrief


def _brief(**kwargs):
    defaults = dict(
        brand="Adventure Asia",
        audience="senior professionals",
        channel="facebook",
        goal="awareness",
        topic="Mekong tour",
        tone="calm",
        cta="Enquire now",
    )
    defaults.update(kwargs)
    return ContentBrief(**defaults)


_ANGLE = {"name": "Experience-first", "why_it_works": "Puts reader in the scene."}


def test_writer_uses_skill_v2_when_goal_key():
    llm_client = MagicMock(return_value="Content output.")
    brief = _brief(goal_key="1", goal_name="Promotion")
    write_content(brief, _ANGLE, "", llm_client)
    system_arg = llm_client.call_args[0][0]
    assert system_arg == SKILL_V2_SYSTEM


def test_writer_uses_v1_formula_when_no_goal_key():
    llm_client = MagicMock(return_value="Content output.")
    brief = _brief(goal_key=None)
    write_content(brief, _ANGLE, "AIDA formula text", llm_client)
    system_arg = llm_client.call_args[0][0]
    assert system_arg != SKILL_V2_SYSTEM


def test_writer_loads_goal_references():
    llm_client = MagicMock(return_value="Content output.")
    brief = _brief(goal_key="2", goal_name="Lead generation")
    with patch(
        "services.acp_s4_social.writer.load_goal_references", return_value="ref text"
    ) as mock_refs:
        write_content(brief, _ANGLE, "", llm_client)
    mock_refs.assert_called_once_with("2")
