"""
tests/unit/test_aa372_gates.py — services/acp_produce/gates.py F2/F3/F4/F6/F7
(AA-372) + F9 social rubric, tested directly (not through the pipeline).

Each gate gets >=1 pass case and >=1 fail case (AA-372 VERIFY checklist).
Follows test_aa298_gates.py's convention of calling the gate functions
directly with hand-built inputs, and test_aa298_judge.py's convention of
patching services.acp_produce.judge_client.boto3.client for the LLM gate.
"""
import json
from unittest.mock import MagicMock, patch

from services.acp_produce.gates import (SOCIAL_SEO_FAILURE_CODES, gate_banned_patterns,
                                          gate_brand_seo_audit_social, gate_brief_compliance,
                                          gate_faq_dedup, gate_route_to_sellable,
                                          gate_structural_variance)
from services.acp_produce.models import Brief, KeywordRecord


def _bedrock_response(data: dict):
    payload = {"output": {"message": {"content": [{"text": json.dumps(data)}], "role": "assistant"}},
               "usage": {"inputTokens": 10, "outputTokens": 5}}
    body = MagicMock()
    body.read.return_value = json.dumps(payload).encode()
    return {"body": body}


# ── F2 banned patterns ──

def test_f2_flags_a_banned_pattern_with_no_citation():
    result = gate_banned_patterns(
        "This trip takes you to a hidden gem in the mountains.", {}
    )
    assert result.gate == "F2_banned_patterns"
    assert result.passed is False
    assert any("hidden gem" in v for v in result.violations)


def test_f2_passes_clean_body():
    result = gate_banned_patterns(
        "The rickshaw ride opens the trip [R:atom_1].",
        {"atom_1": "Ride a rickshaw through Chandni Chowk."},
    )
    assert result.passed is True
    assert result.violations == []


def test_f2_b12_exempts_a_banned_phrase_genuinely_verbatim_in_the_cited_atom():
    """B12 fix: the atom's OWN source text legitimately contains 'hidden gem'
    (e.g. a guide's own description) — citing it verbatim must not trip F2."""
    result = gate_banned_patterns(
        "The guide calls it a hidden gem of the old town [R:atom_1].",
        {"atom_1": "Locals call this spot a hidden gem of the old town."},
    )
    assert result.passed is True


def test_f2_b12_does_not_exempt_a_banned_phrase_the_writer_added_near_a_citation():
    """A citation tag alone is not a free pass — the matched phrase must
    actually be present in the cited text, or it still fails."""
    result = gate_banned_patterns(
        "This is an unforgettable stop on the trip [R:atom_1].",
        {"atom_1": "The market opens at 8am."},
    )
    assert result.passed is False
    assert any("unforgettable" in v for v in result.violations)


# ── F3 structural variance ──

def test_f3_passes_blog_body_with_variance():
    body = "Short opener.\n\n" + "This is a much longer paragraph with several sentences. " * 5
    result = gate_structural_variance(body, "blog")
    assert result.gate == "F3_structural_variance"
    assert result.passed is True


def test_f3_fails_blog_body_with_no_one_sentence_paragraph():
    body = ("This paragraph has two sentences in it. It never stands alone.\n\n"
            "Neither does this one. It also has two sentences.")
    result = gate_structural_variance(body, "blog")
    assert result.passed is False
    assert any("one-sentence paragraph" in v for v in result.violations)


def test_f3_fails_blog_body_with_more_than_one_bulleted_list():
    body = (
        "Short opener.\n\n"
        "- item one\n- item two\n\n"
        "Some more prose here to separate the lists apart.\n\n"
        "- item three\n- item four"
    )
    result = gate_structural_variance(body, "blog")
    assert result.passed is False
    assert any("bulleted list" in v for v in result.violations)


def test_f3_no_ops_for_non_blog_channel():
    body = "Two sentences here. Never one alone. Two sentences here. Never one alone."
    result = gate_structural_variance(body, "facebook")
    assert result.passed is True


# ── F4 brief compliance ──

def _brief(**overrides):
    base = dict(
        brief_id="b1", slot_id="s1", keyword="rickshaw",
        demand=KeywordRecord(keyword="rickshaw", location="US"),
        required_h2s=["Getting there"], word_range=(5, 50),
        cta_target="https://example.com/trip", internal_links=[],
        framework="hub",
    )
    base.update(overrides)
    return Brief(**base)


def test_f4_passes_compliant_body():
    body = "## Getting there\n\nRide a rickshaw through the old town at dawn every single day."
    result = gate_brief_compliance(body, "blog", _brief())
    assert result.gate == "F4_brief_compliance"
    assert result.passed is True


def test_f4_fails_when_keyword_missing():
    body = "## Getting there\n\nRide a tuk-tuk through the old town at dawn."
    result = gate_brief_compliance(body, "blog", _brief())
    assert result.passed is False
    assert any("rickshaw" in v for v in result.violations)


def test_f4_fails_when_required_h2_missing():
    body = "## Somewhere else\n\nRide a rickshaw through the old town at dawn."
    result = gate_brief_compliance(body, "blog", _brief())
    assert result.passed is False
    assert any("Getting there" in v for v in result.violations)


def test_f4_fails_closed_when_brief_is_none_for_blog():
    result = gate_brief_compliance("Any body at all.", "blog", None)
    assert result.passed is False
    assert any("no Brief" in v for v in result.violations)


def test_f4_no_ops_for_non_blog_channel_even_without_brief():
    result = gate_brief_compliance("Any body at all.", "facebook", None)
    assert result.passed is True


# ── F6 route-to-sellable ──

def test_f6_passes_blog_with_cta_alive_and_in_body():
    result = gate_route_to_sellable(
        "Book it at https://example.com/trip.", "blog",
        "https://example.com/trip", True,
    )
    assert result.gate == "F6_route_to_sellable"
    assert result.passed is True


def test_f6_fails_closed_when_no_cta_target():
    result = gate_route_to_sellable("Some body.", "blog", None, True)
    assert result.passed is False
    assert any("no CTA target" in v for v in result.violations)


def test_f6_fails_closed_when_url_alive_is_none_no_row():
    result = gate_route_to_sellable(
        "Book it at https://example.com/trip.", "blog",
        "https://example.com/trip", None,
    )
    assert result.passed is False
    assert any("not confirmed alive" in v for v in result.violations)


def test_f6_fails_closed_when_url_alive_is_false():
    result = gate_route_to_sellable(
        "Book it at https://example.com/trip.", "blog",
        "https://example.com/trip", False,
    )
    assert result.passed is False


def test_f6_fails_blog_when_cta_not_literally_in_body():
    result = gate_route_to_sellable("Book your trip today.", "blog",
                                     "https://example.com/trip", True)
    assert result.passed is False
    assert any("not present in body" in v for v in result.violations)


def test_f6_skips_literal_cta_check_for_facebook():
    result = gate_route_to_sellable(
        "Come see the sunrise with us! Link in bio.", "facebook",
        "https://example.com/trip", True,
    )
    assert result.passed is True


# ── F7 FAQ dedup (intra-piece) ──

def test_f7_passes_body_with_no_faq_section():
    result = gate_faq_dedup("Just a plain body, no FAQ block at all.")
    assert result.gate == "F7_faq_dedup"
    assert result.passed is True


def test_f7_passes_faq_that_adds_new_information():
    body = (
        "The market opens early and closes by noon most days.\n\n"
        "## FAQ\n\n"
        "**Q: Is the market open on Sundays?**\n"
        "A: No, the market is closed every Sunday for a weekly cleaning schedule.\n"
    )
    result = gate_faq_dedup(body)
    assert result.passed is True


def test_f7_fails_faq_answer_that_restates_the_body():
    body = (
        "The market opens early and closes by noon on most weekdays throughout the season.\n\n"
        "## FAQ\n\n"
        "**Q: When is the market open?**\n"
        "A: The market opens early and closes by noon on most weekdays throughout the season.\n"
    )
    result = gate_faq_dedup(body)
    assert result.passed is False
    assert any("restates a body paragraph" in v for v in result.violations)


# ── F9 social rubric ──

def test_f9_social_unknown_channel_raises():
    try:
        gate_brand_seo_audit_social("some body", "blog", "rubric")
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_f9_social_facebook_uses_3_field_contract_not_blog_5_field():
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _bedrock_response({
        "status": "pass", "brand_fit": 1, "cta_clear": 1, "human_read": 1,
        "failure_codes": [], "notes": "clean",
    })
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result, audit = gate_brand_seo_audit_social("Caption text here.", "facebook", "brand rubric text")

    assert result.gate == "F9_brand_seo_audit_social"
    assert result.passed is True
    assert audit["channel"] == "facebook"
    assert set(audit) >= {"brand_fit", "cta_clear", "human_read"}
    assert "seo_fit" not in audit
    assert "trip_type_accuracy" not in audit

    sent_user = json.loads(fake_client.invoke_model.call_args.kwargs["body"])["messages"][0]["content"][0]["text"]
    assert "cta_clear" in sent_user
    assert "seo_fit" not in sent_user


def test_f9_social_tiktok_uses_2_field_contract():
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _bedrock_response({
        "status": "flagged", "hook_strength": 0, "cta_clear": 1,
        "failure_codes": ["HOOK_WEAK"], "notes": "hook doesn't land",
    })
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        result, audit = gate_brand_seo_audit_social("HOOK: meh.\nSCRIPT: ...\nVISUAL: ...",
                                                       "tiktok", "brand rubric text")

    assert result.passed is False
    assert audit["channel"] == "tiktok"
    assert set(audit) >= {"hook_strength", "cta_clear"}
    assert "brand_fit" not in audit
    assert "human_read" not in audit
    assert audit["failure_codes"] == ["HOOK_WEAK"]


def test_f9_social_drops_failure_codes_outside_fixed_vocabulary():
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = _bedrock_response({
        "status": "flagged", "hook_strength": 0, "cta_clear": 1,
        "failure_codes": ["HOOK_WEAK", "SOME_MADE_UP_CODE"], "notes": "n/a",
    })
    with patch("services.acp_produce.judge_client.boto3.client", return_value=fake_client):
        _, audit = gate_brand_seo_audit_social("body", "tiktok", "rubric")

    assert audit["failure_codes"] == ["HOOK_WEAK"]
    assert all(c in SOCIAL_SEO_FAILURE_CODES for c in audit["failure_codes"])


def test_f9_social_judge_unavailable_fails_not_silent_pass():
    with patch("services.acp_produce.judge_client.boto3.client", side_effect=RuntimeError("boom")):
        result, audit = gate_brand_seo_audit_social("body", "facebook", "rubric")

    assert result.passed is False
    assert audit is None
