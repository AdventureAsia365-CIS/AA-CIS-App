"""Unit tests for S4.2 Social Media Content Engine (AA-93). Mocks LLM calls."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.acp_s4_social.brief import ContentBrief, VALID_CHANNELS
from services.acp_s4_social.formula import get_formula_name, load_formula_file
from services.acp_s4_social.output import _build_jsonb_columns, _extract_hashtags


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_brief(**overrides) -> ContentBrief:
    defaults = dict(
        brand="Adventure Asia",
        audience="Senior professionals 40-60, US/UK/AU",
        channel="facebook",
        goal="awareness",
        topic="Cycling South Korea",
        tone="calm, credible, specific",
        cta="Explore the route",
        must_include=["Seoul", "Busan"],
        must_avoid=["trip of a lifetime", "game-changing"],
        destination="south korea",
        tour_name="Korea Cycling 9 Days",
    )
    defaults.update(overrides)
    return ContentBrief(**defaults)


def _mock_llm(angles_response=None, content_response=None, quality_response=None):
    """Return a mock LLM callable that returns preset responses by call count."""
    call_count = [0]
    responses = [angles_response, content_response, quality_response]

    def call(system: str, user: str) -> str:
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        resp = responses[idx]
        return resp if resp is not None else '{"error": "no mock"}'

    return call


_MOCK_ANGLES = json.dumps([
    {"name": "Route Authority", "why_it_works": "Shows operator expertise.", "length_signal": "200 words", "style_signal": "expert authority"},
    {"name": "Transformation Story", "why_it_works": "Before-after contrast.", "length_signal": "250 words", "style_signal": "narrative"},
    {"name": "Counterintuitive Hook", "why_it_works": "Surprises the reader.", "length_signal": "180 words", "style_signal": "punchy"},
])

_MOCK_CONTENT = "Cycling from Seoul to Busan isn't just a bike ride. It's 650km of coastal trail, mountain terrain, and ancient temple stops — designed for travellers who move deliberately. Explore the route."

_MOCK_QUALITY = json.dumps({
    "revised_content": _MOCK_CONTENT,
    "warnings": [],
    "passed": True,
})


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_brief_validate_anchors_pass():
    brief = _make_brief()
    missing = brief.validate_anchors()
    assert missing == [], f"Expected no missing anchors, got: {missing}"


def test_brief_validate_anchors_missing_channel():
    brief = _make_brief(channel="")
    missing = brief.validate_anchors()
    assert "channel" in missing


def test_brief_validate_invalid_channel():
    brief = _make_brief(channel="pinterest")
    missing = brief.validate_anchors()
    assert "channel" in missing


def test_brief_validate_missing_multiple():
    brief = _make_brief(brand="", goal="")
    missing = brief.validate_anchors()
    assert "brand" in missing
    assert "goal" in missing


def test_formula_map_facebook_awareness():
    formula = get_formula_name("facebook", "awareness")
    assert formula == "aida"


def test_formula_map_tiktok_engagement():
    formula = get_formula_name("tiktok", "engagement")
    assert formula == "hook-value-cta"


def test_formula_map_landing_page_conversion():
    formula = get_formula_name("landing_page", "conversion")
    assert formula == "pppp"


def test_formula_map_default_fallback():
    formula = get_formula_name("unknown_channel", "unknown_goal")
    assert formula == "aida"


def test_load_formula_file_exists():
    content = load_formula_file("aida")
    assert len(content) > 100, "aida.md should have substantial content"
    assert "AIDA" in content or "aida" in content.lower() or "Attention" in content


def test_load_formula_file_missing():
    content = load_formula_file("nonexistent_formula_xyz")
    assert content == ""


@pytest.mark.asyncio
async def test_angles_auto_mode_returns_one():
    from services.acp_s4_social.angles import generate_angles
    brief = _make_brief()
    llm = _mock_llm(angles_response=_MOCK_ANGLES)
    angles = generate_angles(brief, llm, mode="auto")
    assert len(angles) == 1
    assert "name" in angles[0]
    assert "why_it_works" in angles[0]


@pytest.mark.asyncio
async def test_angles_guided_mode_returns_three():
    from services.acp_s4_social.angles import generate_angles
    brief = _make_brief()
    llm = _mock_llm(angles_response=_MOCK_ANGLES)
    angles = generate_angles(brief, llm, mode="guided")
    assert len(angles) == 3
    assert all("name" in a for a in angles)


def test_quality_pass_flags_forbidden_phrase():
    from services.acp_s4_social.quality import quality_pass, FORBIDDEN_PHRASES
    brief = _make_brief()
    content_with_phrase = f"This game-changing tour will transform your life. {_MOCK_CONTENT}"
    quality_response = json.dumps({
        "revised_content": _MOCK_CONTENT,
        "warnings": ["Forbidden phrase: game-changing"],
        "passed": False,
    })
    llm = _mock_llm(quality_response=quality_response)
    result = quality_pass(content_with_phrase, brief, llm)
    assert result["warnings"]
    assert any("game-changing" in w for w in result["warnings"])


def test_channel_mapping_tiktok_to_jsonb():
    content = "Cycling Seoul to Busan in 9 days. #KoreaCycling #AdventureAsia #BikeKorea"
    cols = _build_jsonb_columns("tiktok", content)
    assert cols["tiktok"] is not None
    tiktok_data = json.loads(cols["tiktok"])
    assert "content" in tiktok_data
    assert "hashtags" in tiktok_data
    assert "#KoreaCycling" in tiktok_data["hashtags"]
    assert cols["facebook_post"] is None
    assert cols["facebook_ad"] is None


def test_channel_mapping_facebook_to_jsonb():
    cols = _build_jsonb_columns("facebook", _MOCK_CONTENT)
    assert cols["facebook_post"] is not None
    fb_data = json.loads(cols["facebook_post"])
    assert "content" in fb_data
    assert cols["tiktok"] is None
    assert cols["facebook_ad"] is None


def test_channel_mapping_ads_to_jsonb():
    content = "Discover Korea's Best Cycling Route\nExplore 650km of coastal trail from Seoul to Busan. Book your spot."
    cols = _build_jsonb_columns("ads", content)
    assert cols["facebook_ad"] is not None
    ad_data = json.loads(cols["facebook_ad"])
    assert "headline" in ad_data
    assert "body" in ad_data


def test_channel_mapping_linkedin_to_strategy_notes():
    cols = _build_jsonb_columns("linkedin", _MOCK_CONTENT)
    assert cols["strategy_notes"] is not None
    data = json.loads(cols["strategy_notes"])
    assert data["channel"] == "linkedin"
    assert "content" in data
    assert cols["tiktok"] is None


def test_valid_channels_list():
    assert "facebook" in VALID_CHANNELS
    assert "tiktok" in VALID_CHANNELS
    assert "ads" in VALID_CHANNELS
    assert len(VALID_CHANNELS) == 8
