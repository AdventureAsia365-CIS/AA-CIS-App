"""tests/unit/test_aa511_slate.py — AA-511: the Slate's Bar logic.

Pure-function tests only (no DB/HTTP) — `_clears_bar()`/`CHANNEL_BARS` against the literal
thresholds STEP0 confirmed from Ms. Thư's `reference/channels.toml`
(docs/claude_audit/AA-511-step0-slate-investigation.md).
"""
from services.acp_shared.slate import CHANNEL_BARS, ON_DEMAND_CHANNELS, WEEKLY_RHYTHM_CHANNELS
from services.acp_shared.slate import Candidate, _clears_bar


def _segment_candidate(demand=None, questions=0, said=0):
    return Candidate(
        segment_id="seg1", route_id=None, score=5, demand=demand, questions=questions,
        said=said, place="Matsumoto Castle", action="visit",
    )


def _route_candidate(demand=None, questions=0):
    return Candidate(
        route_id="r1", segment_id=None, score=3, demand=demand, questions=questions,
        said=0, hub_name="Kyoto -> Magome",
    )


class TestChannelBarsShape:
    def test_eight_channels_declared(self):
        assert set(CHANNEL_BARS) == {
            "blog", "linkedin", "facebook", "instagram", "tiktok",
            "email", "landing_page", "ads",
        }

    def test_blog_thresholds_match_reference_channels_toml(self):
        assert CHANNEL_BARS["blog"]["needs_demand"] == 1000
        assert CHANNEL_BARS["blog"]["needs_questions"] == 3
        assert CHANNEL_BARS["blog"]["grain"] == "route"
        assert CHANNEL_BARS["blog"]["on_demand"] is False

    def test_attention_led_channels_share_needs_said_150(self):
        for channel in ("linkedin", "facebook", "instagram", "tiktok"):
            spec = CHANNEL_BARS[channel]
            assert spec["needs_said"] == 150
            assert spec["needs_demand"] == 0
            assert spec["needs_questions"] == 0
            assert spec["grain"] == "segment"

    def test_on_demand_channels_have_open_bar(self):
        for channel in ("email", "landing_page", "ads"):
            spec = CHANNEL_BARS[channel]
            assert spec["on_demand"] is True
            assert spec["needs_demand"] == 0
            assert spec["needs_questions"] == 0
            assert spec["needs_said"] == 0

    def test_weekly_vs_on_demand_partition(self):
        assert set(WEEKLY_RHYTHM_CHANNELS) == {
            "blog", "linkedin", "facebook", "instagram", "tiktok",
        }
        assert set(ON_DEMAND_CHANNELS) == {"email", "landing_page", "ads"}
        assert set(WEEKLY_RHYTHM_CHANNELS) | set(ON_DEMAND_CHANNELS) == set(CHANNEL_BARS)


class TestClearsBarBlog:
    def test_clears_with_demand_and_questions_over_threshold(self):
        cleared, reason = _clears_bar("blog", _route_candidate(demand=1450, questions=5))
        assert cleared is True
        assert reason["demand_ok"] is True
        assert reason["questions_ok"] is True

    def test_fails_below_demand_threshold_even_with_questions(self):
        cleared, reason = _clears_bar("blog", _route_candidate(demand=999, questions=10))
        assert cleared is False
        assert reason["demand_ok"] is False
        assert reason["questions_ok"] is True

    def test_fails_below_questions_threshold_even_with_demand(self):
        cleared, reason = _clears_bar("blog", _route_candidate(demand=50_000, questions=2))
        assert cleared is False
        assert reason["demand_ok"] is True
        assert reason["questions_ok"] is False

    def test_exact_threshold_clears(self):
        cleared, _ = _clears_bar("blog", _route_candidate(demand=1000, questions=3))
        assert cleared is True

    def test_none_demand_treated_as_zero(self):
        cleared, reason = _clears_bar("blog", _route_candidate(demand=None, questions=10))
        assert cleared is False
        assert reason["demand_ok"] is False


class TestClearsBarAttentionLed:
    def test_facebook_clears_on_said_alone_no_demand_no_questions(self):
        cleared, reason = _clears_bar("facebook", _segment_candidate(demand=None, questions=0, said=200))
        assert cleared is True
        assert reason["demand_ok"] is True  # 0 >= 0
        assert reason["questions_ok"] is True  # 0 >= 0

    def test_instagram_fails_below_said_threshold(self):
        cleared, reason = _clears_bar("instagram", _segment_candidate(said=149))
        assert cleared is False
        assert reason["said_ok"] is False

    def test_tiktok_exact_threshold_clears(self):
        cleared, _ = _clears_bar("tiktok", _segment_candidate(said=150))
        assert cleared is True

    def test_linkedin_high_demand_does_not_substitute_for_said(self):
        # Attention-led channels don't accept demand in place of said -- each axis is its own gate.
        cleared, reason = _clears_bar("linkedin", _segment_candidate(demand=1_000_000, said=0))
        assert cleared is False
        assert reason["said_ok"] is False


class TestClearsBarOnDemand:
    def test_email_clears_anything_zero_bar(self):
        cleared, _ = _clears_bar("email", _segment_candidate(demand=None, questions=0, said=0))
        assert cleared is True

    def test_ads_clears_anything_zero_bar(self):
        cleared, _ = _clears_bar("ads", _segment_candidate())
        assert cleared is True

    def test_landing_page_reason_flags_on_demand(self):
        _, reason = _clears_bar("landing_page", _segment_candidate())
        assert reason["on_demand"] is True
