"""Unit tests for services/acp_s4_blog/validator.py (AA-80)."""
import re
import pytest

from services.acp_s4_blog.validator import ValidatorAgent, _parse_markdown
from services.acp_s4_blog.models import ValidationResult, CheckResult

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_blog(content_md: str, title: str = "South Korea Cycling Tour Guide",
               seo_title: str = "South Korea Cycling Tour: Seoul to Busan Route") -> dict:
    return {"content_md": content_md, "title": title, "seo_title": seo_title, "draft_id": "test-id"}


def _make_brief(destination: str = "south korea", primary_keyword: str = "south korea cycling tour",
                outline: list = None) -> dict:
    return {"destination": destination, "primary_keyword": primary_keyword, "outline": outline or []}


def _good_blog(extra_sections: int = 0) -> str:
    """Generate a blog that passes most structural checks (~1700 words)."""
    proof = (
        "Seoul to Busan spans 650km across varied terrain. The route covers 9 days "
        "through Gyeongju, Sokcho, and Gangneung. We crossed Seoraksan at 1700m elevation "
        "on day 4, the hardest day with 1200m of climbing. The KTX return leg takes 2.5 hours. "
        "Spring and autumn are ideal — summer humidity changes the pacing significantly, which is "
        "a trade-off worth knowing before you commit. Locals at the Han River checkpoint "
        "directed us toward the quieter coastal trails. At dusk outside Busan, you notice the "
        "temperature drop sharply. The coastal stretch from Gangneung south takes 3 days. "
        "The DMZ cycling day from Seoul requires advance booking but is achievable on day 2. "
        "Seoraksan national park offers 800m trail climbs above the treeline with dramatic views. "
        "Jeju island routes require a ferry crossing — allow a half day for transfers either way. "
        "Hallasan summit adds 1950m altitude gain; most groups camp at the Witseoreum shelter. "
        "KTX services link all major cities; bikes travel in dedicated luggage cars on most routes. "
    )
    sections = ""
    for i in range(1, 5 + extra_sections):
        sections += f"\n\n## Section {i}: Route Logic and Terrain\n\n{proof}\n\n{proof}\n"
    faq = (
        "\n\n## FAQ\n\n**Q: How fit do I need to be?**\n\n"
        "**A:** The 9-day route requires reasonable cycling fitness — day 4 climbs 1200m. "
        "Spring and autumn suit most riders; summer humidity adds difficulty.\n\n"
        "**Q: What is the best season?**\n\n"
        "**A:** April–May (spring) or September–October (autumn). Summer increases humidity "
        "and changes pacing on the mountain stages significantly.\n\n"
        "**Q: Can I take the KTX back from Busan?**\n\n"
        "**A:** Yes — the KTX from Busan to Seoul takes 2.5 hours with dedicated bike storage.\n\n"
        "**Q: Is the DMZ section accessible on a bike tour?**\n\n"
        "**A:** Yes, with advance booking via a licensed tour operator. Allow a full day.\n\n"
    )
    return proof * 2 + sections + faq


BAD_BLOG_LEAKY = """
# Internal Notes Blog Draft

This section follows the calendar brief for the Korea cycling tour.
Operational note: apply the section using the itinerary context.
verify provider details such as Bike Tour before final booking.

## Section One

Use route-specific logistics, seasonal caveats, and planning choices.
The itinerary context suggests Seoul to Busan route.
This guide follows the editorial brief and should be verified.

Created at 2024-01-15 14:30:00 by the planner agent.
The tour_id for this content is TK-2024-001.

## FAQ

**Q: How long does it take?**
**A:** Start by validating the provider before committing to any booking.
Use this as a logistics check before final decisions.
"""


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_word_count_pass():
    blog = _make_blog(_good_blog())
    agent = ValidatorAgent()
    result = await agent.validate(blog)
    wc_check = next(c for c in result.checks if c.check_name == "word_count")
    assert wc_check.passed, f"Expected word_count pass but got issues: {wc_check.issues}"


@pytest.mark.asyncio
async def test_word_count_fail_short():
    short_content = "This is a very short blog. " * 30  # ~150 words
    blog = _make_blog(short_content)
    agent = ValidatorAgent()
    result = await agent.validate(blog)
    wc_check = next(c for c in result.checks if c.check_name == "word_count")
    assert not wc_check.passed
    assert "too low" in wc_check.issues[0]


@pytest.mark.asyncio
async def test_leak_phrase_detected():
    blog = _make_blog(BAD_BLOG_LEAKY)
    agent = ValidatorAgent()
    result = await agent.validate(blog)
    leak_check = next(c for c in result.checks if c.check_name == "leak_phrases")
    assert not leak_check.passed
    assert any("operational note" in issue.lower() or "section follows" in issue.lower()
               for issue in leak_check.issues)


@pytest.mark.asyncio
async def test_datetime_pattern_detected():
    content = "The tour was booked on 2024-01-15 14:30:00 via the system.\n\n" + _good_blog()
    blog = _make_blog(content)
    agent = ValidatorAgent()
    result = await agent.validate(blog)
    dt_check = next(c for c in result.checks if c.check_name == "raw_datetime")
    assert not dt_check.passed
    assert "datetime" in dt_check.issues[0].lower()


@pytest.mark.asyncio
async def test_proof_point_count_pass():
    good = _good_blog()  # contains Seoul, Busan, Gyeongju, km, days, terrain
    blog = _make_blog(good)
    agent = ValidatorAgent()
    result = await agent.validate(blog)
    pp_check = next(c for c in result.checks if c.check_name == "proof_point_count")
    assert pp_check.passed, f"Expected proof_point pass, got: {pp_check.issues}"


@pytest.mark.asyncio
async def test_proof_point_count_fail():
    sparse = "South Korea is a beautiful country with many things to see and do for tourists.\n\n"
    sparse *= 200  # lots of words but no proof points
    blog = _make_blog(sparse)
    agent = ValidatorAgent()
    result = await agent.validate(blog)
    pp_check = next(c for c in result.checks if c.check_name == "proof_point_count")
    assert not pp_check.passed
    assert "distinct proof points" in pp_check.issues[0]


@pytest.mark.asyncio
async def test_faq_dedup_detected():
    content = _good_blog()
    dup_faq = (
        "\n\n## FAQ\n\n"
        "**Q: Question one?**\n**A:** South Korea is best visited in spring for mild weather and good cycling.\n\n"
        "**Q: Question two?**\n**A:** South Korea is best visited in spring for mild weather and good cycling.\n\n"
        "**Q: Question three?**\n**A:** Different answer about the route from Seoul to Busan.\n\n"
        "**Q: Question four?**\n**A:** Completely different answer about accommodation options.\n\n"
    )
    blog = _make_blog(content + dup_faq)
    agent = ValidatorAgent()
    result = await agent.validate(blog)
    dup_check = next(c for c in result.checks if c.check_name == "duplicate_faq_answers")
    assert not dup_check.passed
    assert "near-duplicates" in dup_check.issues[0]


@pytest.mark.asyncio
async def test_compiled_rules_block():
    # 'operational note' is a block rule in db_rules seed (migration 020)
    block_rule = [{"rule_id": "r1", "rule_type": "block", "pattern": "operational note",
                   "action_value": None, "error_message": "Scaffolding leak"}]
    content = "This is a good article. Operational note: check the provider details."
    blog = _make_blog(content)
    agent = ValidatorAgent(db_rules=block_rule)
    result = await agent.validate(blog)
    rule_checks = [c for c in result.checks if c.check_name.startswith("rule:block:")]
    assert any(not c.passed for c in rule_checks), "Block rule should fail"


@pytest.mark.asyncio
async def test_compiled_rules_flag():
    flag_rule = [{"rule_id": "r2", "rule_type": "flag", "pattern": "tour_id",
                  "action_value": None, "error_message": "DB field leak"}]
    content = "Please note tour_id is TK-2024-001 for reference.\n\n" + _good_blog()
    blog = _make_blog(content)
    agent = ValidatorAgent(db_rules=flag_rule)
    result = await agent.validate(blog)
    flag_checks = [c for c in result.checks if c.check_name.startswith("rule:flag:")]
    assert any(not c.passed for c in flag_checks), "Flag rule should fire"
    fired = next(c for c in flag_checks if not c.passed)
    assert "[FLAG]" in fired.issues[0]


@pytest.mark.asyncio
async def test_validation_result_structure():
    blog = _make_blog(_good_blog())
    agent = ValidatorAgent()
    result = await agent.validate(blog)
    assert isinstance(result, ValidationResult)
    assert isinstance(result.overall_passed, bool)
    assert 0.0 <= result.overall_score <= 1.0
    assert len(result.checks) >= 29  # 29 structural + compiled rules
    for check in result.checks:
        assert isinstance(check, CheckResult)
        assert isinstance(check.passed, bool)
        assert 0.0 <= check.score <= 1.0
    assert isinstance(result.failing_sections, list)
    assert isinstance(result.repair_targets, list)
    assert result.blog_draft_id == "test-id"


@pytest.mark.asyncio
async def test_known_bad_blog():
    """Load the actual not-do HTML from Ms. Thư and verify ≥5 checks fail."""
    from pathlib import Path
    bad_html_path = Path(
        "docs/AI-gent-for automation works/"
        "stage-4_ Media contents_ blog, FB posts, Tikitok/"
        "not-do/blog1_south-korea-soft-adventure-destination.html"
    )
    if not bad_html_path.exists():
        pytest.skip("Bad blog HTML not found — skipping integration test")

    html = bad_html_path.read_text(encoding="utf-8")
    # Strip HTML tags to get text content
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    blog = {"content_md": text, "title": "Why South Korea is Asia's Hidden Soft Adventure Destination",
            "seo_title": "South Korea Soft Adventure Destination Guide"}
    agent = ValidatorAgent()
    result = await agent.validate(blog)

    failing = [c for c in result.checks if not c.passed]
    failing_names = [c.check_name for c in failing]
    assert len(failing) >= 5, (
        f"Expected ≥5 failing checks for bad blog, got {len(failing)}: {failing_names}"
    )
    # Specifically verify leak detection and datetime fire
    assert any("leak" in name or "operational" in name.lower() for name in failing_names), \
        f"Leak checks should fire on bad blog. Failing: {failing_names}"
