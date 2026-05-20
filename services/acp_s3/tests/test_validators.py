import validators


GOOD_MARKDOWN = """
## Week 1 — Adventure

### Week 1

#### Post 1
Primary Keyword: vietnam adventure tours
Lead Magnet CTA: Download our free Vietnam itinerary guide
"""

POSTS_VIETNAM = [
    {"primary_keyword": "vietnam adventure tours"},
    {"primary_keyword": "vietnam trekking packages"},
]

S1_USED = ["thailand jungle tours", "cambodia temples trek"]


class TestCheckWeekStructure:
    def test_passes_when_present(self):
        assert validators.check_week_structure(GOOD_MARKDOWN) is True

    def test_fails_when_absent(self):
        assert validators.check_week_structure("No headings here") is False

    def test_requires_digits(self):
        assert validators.check_week_structure("### Week A") is False


class TestCheckPrimaryKeywordLabels:
    def test_passes_when_present(self):
        assert validators.check_primary_keyword_labels(GOOD_MARKDOWN) is True

    def test_fails_when_absent(self):
        assert validators.check_primary_keyword_labels("no labels") is False


class TestCheckLeadMagnetCta:
    def test_passes_when_present(self):
        assert validators.check_lead_magnet_cta(GOOD_MARKDOWN) is True

    def test_fails_when_absent(self):
        assert validators.check_lead_magnet_cta("no cta here") is False


class TestCheckNoBannedCountry:
    def test_passes_country_specific_keywords(self):
        assert validators.check_no_banned_country(POSTS_VIETNAM, "vietnam") is True

    def test_fails_when_other_country_in_keyword(self):
        posts = [{"primary_keyword": "thailand beach tours"}]
        assert validators.check_no_banned_country(posts, "vietnam") is False

    def test_active_country_allowed_in_keyword(self):
        posts = [{"primary_keyword": "vietnam eco tours"}]
        assert validators.check_no_banned_country(posts, "vietnam") is True

    def test_case_insensitive(self):
        posts = [{"primary_keyword": "Korea cycling tours"}]
        assert validators.check_no_banned_country(posts, "vietnam") is False


class TestCheckAntiCannibalization:
    def test_passes_no_overlap(self):
        assert validators.check_anti_cannibalization(POSTS_VIETNAM, S1_USED) is True

    def test_fails_on_exact_overlap(self):
        posts = [{"primary_keyword": "thailand jungle tours"}]
        assert validators.check_anti_cannibalization(posts, S1_USED) is False

    def test_case_insensitive(self):
        posts = [{"primary_keyword": "Thailand Jungle Tours"}]
        assert validators.check_anti_cannibalization(posts, S1_USED) is False

    def test_partial_match_does_not_fail(self):
        posts = [{"primary_keyword": "thailand jungle"}]
        assert validators.check_anti_cannibalization(posts, S1_USED) is True


class TestRunAll:
    def test_returns_empty_on_all_pass(self):
        errors = validators.run_all(GOOD_MARKDOWN, POSTS_VIETNAM, "vietnam", S1_USED)
        assert errors == []

    def test_collects_multiple_errors(self):
        bad_md = "no structure here"
        posts = [{"primary_keyword": "thailand jungle tours"}]
        errors = validators.run_all(bad_md, posts, "vietnam", S1_USED)
        assert len(errors) >= 3  # week_structure, primary_keyword_labels, lead_magnet_cta
        error_ids = [e.split(":")[0] for e in errors]
        assert "week_structure" in error_ids
        assert "anti_cannibalization" in error_ids
