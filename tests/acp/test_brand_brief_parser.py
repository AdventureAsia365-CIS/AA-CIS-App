from pathlib import Path

import pytest

from services.acp_brand_brief_parser.parser import parse_docx

FIXTURES = Path(__file__).parent.parent.parent / "services/acp_brand_brief_parser/fixtures"


def test_atlas_brief():
    brief = parse_docx(FIXTURES / "Atlas.docx")
    assert brief.brand_type == "Luxury cultural travel brand"
    assert len(brief.voice_examples.tone_traits) >= 5
    assert "Elegant" in brief.voice_examples.tone_traits
    assert "Discreet" in brief.voice_examples.tone_traits
    assert any("backpacker" in w.lower() for w in brief.forbidden_words)
    assert any("VIP lifestyle" in w for w in brief.forbidden_words)
    assert brief.confidence >= 0.75


def test_terra_family_brief():
    brief = parse_docx(FIXTURES / "Terra Family Expeditions.docx")
    assert brief.brand_type == "Premium family adventure travel brand"
    assert "Warm" in brief.voice_examples.tone_traits
    assert "Reassuring" in brief.voice_examples.tone_traits
    assert any("kiddos" in w.lower() for w in brief.forbidden_words)
    assert brief.confidence >= 0.75


def test_trail_pulse_brief():
    brief = parse_docx(FIXTURES / "Trail Pulse.docx")
    assert "young active adventure" in brief.brand_type.lower()
    assert "Energetic" in brief.voice_examples.tone_traits
    assert any(
        "bucket-list" in w.lower() or "bucket-list adventure" in w.lower()
        for w in brief.forbidden_words
    )
    assert brief.confidence >= 0.75


def test_wildkind_brief():
    brief = parse_docx(FIXTURES / "WildKind Travel.docx")
    assert "responsible nature" in brief.brand_type.lower()
    assert "Thoughtful" in brief.voice_examples.tone_traits
    assert any("get up close" in w.lower() for w in brief.forbidden_words)
    assert any("untouched" in w.lower() for w in brief.forbidden_words)
    assert brief.confidence >= 0.75
