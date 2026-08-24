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
