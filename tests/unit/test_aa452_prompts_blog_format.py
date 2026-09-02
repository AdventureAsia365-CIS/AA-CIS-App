"""AA-452 — services/acp_content_writing/prompts.py's blog-only H2/FAQ/citation-tag instruction
block. Same convention test_aa450_content_writing_generate.py already uses for this module's
build_user_prompt() (GOAL/CHANNEL_STYLE/ANGLE/BRAND_AUDIENCE fixtures)."""
from services.acp_angle_gate.channel_style import get_channel_style
from services.acp_angle_gate.goals import get_goal
from services.acp_content_writing.prompts import build_user_prompt

GOAL = get_goal("promotion")
ANGLE = {"name": "A", "why_it_works": "wa", "formula_fit": "AIDA", "best_final_style": "warm"}
BRAND_AUDIENCE = {"customer_segment": "Senior execs", "customer_mindset": "seek depth"}


class TestBlogFormatInstructions:
    def test_blog_channel_gets_h2_faq_and_tag_instructions(self):
        prompt = build_user_prompt(
            content_seed="seed", goal=GOAL, channel_style=get_channel_style("blog"),
            brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now", atom_id="atom_abc123",
        )
        assert "## " in prompt  # H2 header instruction
        assert "## FAQ" in prompt
        assert "[R:atom_abc123]" in prompt

    def test_blog_channel_with_no_atom_id_falls_back_to_placeholder_not_malformed_tag(self):
        prompt = build_user_prompt(
            content_seed="seed", goal=GOAL, channel_style=get_channel_style("blog"),
            brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
        )
        assert "[R:atom]" in prompt
        assert "[R:]" not in prompt

    def test_non_blog_channel_gets_no_blog_instructions(self):
        for channel in ["facebook", "tiktok", "linkedin", "instagram", "email", "landing_page", "ads"]:
            prompt = build_user_prompt(
                content_seed="seed", goal=GOAL, channel_style=get_channel_style(channel),
                brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now", atom_id="atom_abc123",
            )
            assert "[R:" not in prompt, f"channel={channel} unexpectedly got the citation-tag instruction"
            assert "BLOG-SPECIFIC" not in prompt, f"channel={channel} unexpectedly got blog instructions"


class TestRouteAwareBlogFormat:
    """AA-513 — >=2 route_segments: labeled-moment CONTENT SEED + per-moment tagging instruction,
    instead of the single blanket atom_id. Ported real gap this build closes — see
    docs/claude_audit/AA-513-step0-investigation.md §1."""

    def test_two_or_more_segments_render_labeled_moments_and_route_instructions(self):
        segments = [("atom_seg1", "Cross the bamboo bridge at dawn"), ("atom_seg2", "Kayak the bay at sunset")]
        prompt = build_user_prompt(
            content_seed="unused when route-aware", goal=GOAL, channel_style=get_channel_style("blog"),
            brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now",
            route_segments=segments,
        )
        assert "[Moment id=atom_seg1]" in prompt
        assert "[Moment id=atom_seg2]" in prompt
        assert "Cross the bamboo bridge at dawn" in prompt
        assert "Kayak the bay at sunset" in prompt
        assert "THAT MOMENT'S OWN id" in prompt  # route-aware instruction, not the single-id one
        assert "[R:atom_seg1]" not in prompt  # the model is TOLD to tag, not pre-tagged for it
        # The single-moment instruction's own literal-fallback line must NOT also be present.
        assert "[R:atom]" not in prompt

    def test_single_segment_behaves_like_no_route_segments(self):
        one = [("atom_only", "some text")]
        with_one = build_user_prompt(
            content_seed="the flat seed", goal=GOAL, channel_style=get_channel_style("blog"),
            brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now", atom_id="atom_only",
            route_segments=one,
        )
        without = build_user_prompt(
            content_seed="the flat seed", goal=GOAL, channel_style=get_channel_style("blog"),
            brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now", atom_id="atom_only",
        )
        assert with_one == without
        assert "[Moment id=" not in with_one

    def test_none_route_segments_unchanged_for_every_existing_caller(self):
        """The exact byte-identical assertion the build task's own regression ask requires:
        route_segments omitted entirely (every pre-AA-513 caller) must produce identical output
        to explicitly passing None."""
        kwargs = dict(
            content_seed="seed", goal=GOAL, channel_style=get_channel_style("blog"),
            brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now", atom_id="atom_abc123",
        )
        assert build_user_prompt(**kwargs) == build_user_prompt(**kwargs, route_segments=None)

    def test_non_blog_channel_ignores_route_segments(self):
        segments = [("atom_seg1", "text1"), ("atom_seg2", "text2")]
        prompt = build_user_prompt(
            content_seed="seed", goal=GOAL, channel_style=get_channel_style("facebook"),
            brand_audience=BRAND_AUDIENCE, angle=ANGLE, cta="Book now", route_segments=segments,
        )
        assert "BLOG-SPECIFIC" not in prompt
        assert "[Moment id=" not in prompt  # non-blog never renders the labeled-moment seed either
