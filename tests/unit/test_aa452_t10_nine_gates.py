"""AA-452 — services/acp_content_writing/quality_gates.py's 3 new blog-only gates
(F5_atom_density/F3_structural_variance/F7_faq_dedup) + the tag strip/leak-prevention mechanism
(strip_citation_tags/deep_strip_citation_tags) + service.write_and_check()'s mandatory
strip-before-persist step. Same conventions test_aa450_quality_gates.py already uses (pure
functions tested directly, judge gates mocked via patch.object(qg, "invoke_judge", ...))."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_content_writing import quality_gates as qg
from services.acp_content_writing import service


# ---------------------------------------------------------------- gate_atom_density (F5)

class TestGateAtomDensity:
    def test_short_body_with_no_tags_passes_window_floor(self):
        # under ATOM_DENSITY_WORDS//2 (150 words) — same exemption N7's own short-form channels
        # get, confirmed by test in this file's N7 counterpart (gates.py test suite).
        result = qg.gate_atom_density("word " * 50)
        assert result["passed"] is True

    def test_300_word_window_with_zero_citations_fails(self):
        body = "word " * 300
        result = qg.gate_atom_density(body)
        assert result["passed"] is False
        assert "zero atom citations" in result["violations"][0]

    def test_300_word_window_with_one_citation_passes(self):
        words = ["word"] * 299 + ["[R:atom_abc123]"]
        result = qg.gate_atom_density(" ".join(words))
        assert result["passed"] is True

    def test_trailing_short_chunk_skipped_not_flagged(self):
        # 300 clean words (tagged, passes) + a 100-word trailing fragment (< window//2=150) —
        # the trailing fragment must NOT be independently flagged.
        first_window = ["word"] * 299 + ["[R:atom_abc123]"]
        trailing = ["word"] * 100
        result = qg.gate_atom_density(" ".join(first_window + trailing))
        assert result["passed"] is True


# ---------------------------------------------------------------- gate_structural_variance (F3)

class TestGateStructuralVariance:
    def test_no_one_sentence_paragraph_fails(self):
        body = "This is a long paragraph with several sentences. It keeps going. And going more."
        result = qg.gate_structural_variance(body)
        assert result["passed"] is False
        assert "one-sentence paragraph" in result["violations"][0]

    def test_one_sentence_paragraph_present_passes_that_check(self):
        body = "A short one.\n\nA longer paragraph that has multiple sentences. Here is another."
        result = qg.gate_structural_variance(body)
        assert result["passed"] is True

    def test_uniform_h2_section_lengths_fail_with_3_plus_sections(self):
        section = "word " * 50
        body = f"## One\n{section}\n\n## Two\n{section}\n\n## Three\n{section}"
        result = qg.gate_structural_variance(body)
        assert any("notably longer" in v for v in result["violations"])

    def test_multiple_bulleted_lists_fail(self):
        body = "One sentence.\n\n- item\n- item2\n\n- item3\n- item4"
        result = qg.gate_structural_variance(body)
        assert any("bulleted lists" in v for v in result["violations"])


# ---------------------------------------------------------------- gate_faq_dedup (F7)

class TestGateFaqDedup:
    def test_no_faq_section_passes_as_noop(self):
        result = qg.gate_faq_dedup("A body with no FAQ section at all.")
        assert result["passed"] is True

    def test_faq_answer_restating_body_fails(self):
        body = (
            "The waterfall trail winds through dense highland forest reaching remote plateau "
            "villages before dawn.\n\n"
            "## FAQ\n\n"
            "**Q: What is the trail like?**\n"
            "A: The waterfall trail winds through dense highland forest reaching remote plateau "
            "villages before dawn."
        )
        result = qg.gate_faq_dedup(body)
        assert result["passed"] is False
        assert "restates a body paragraph" in result["violations"][0]

    def test_faq_answer_with_new_detail_passes(self):
        body = (
            "The waterfall trail winds through dense highland forest.\n\n"
            "## FAQ\n\n"
            "**Q: How long does the visit take?**\n"
            "A: Most travelers spend around ninety minutes at the third tier."
        )
        result = qg.gate_faq_dedup(body)
        assert result["passed"] is True


# ---------------------------------------------------------------- strip_citation_tags

class TestStripCitationTags:
    def test_strips_tag_and_leading_space(self):
        assert qg.strip_citation_tags("A fact. [R:atom_abc123] Next.") == "A fact. Next."

    def test_strips_tag_with_no_leading_space(self):
        assert qg.strip_citation_tags("A fact.[R:atom_abc123] Next.") == "A fact. Next."

    def test_strips_f_prefixed_tag_too(self):
        assert qg.strip_citation_tags("A fact. [F:fact_9] Next.") == "A fact. Next."

    def test_no_tags_is_unchanged(self):
        assert qg.strip_citation_tags("Nothing tagged here.") == "Nothing tagged here."

    def test_none_returns_empty_string(self):
        assert qg.strip_citation_tags(None) == ""

    def test_deep_strip_walks_gate_ledger_shape(self):
        ledger = [
            {"gate": "F1_grounding", "passed": False,
             "violations": ["sentence quotes [R:atom_abc123] here"], "repairable": True},
            {"gate": "F6_cta_present", "passed": True, "violations": [], "repairable": True},
        ]
        cleaned = qg.deep_strip_citation_tags(ledger)
        assert "[R:" not in cleaned[0]["violations"][0]
        assert cleaned[1] == ledger[1]  # untouched entries pass through unchanged


# ---------------------------------------------------------------- run_quality_gates channel dispatch

def _judge_raw(**fields) -> dict:
    return {"text": json.dumps(fields)}


class TestRunQualityGatesChannelDispatch:
    def test_non_blog_channel_still_runs_exactly_6_gates(self):
        rubric = qg.get_framework_rubric("promotion")
        f8_data = {"items": [{"criterion": c, "score": "1", "evidence": "q"} for c in rubric]}
        f9_data = {"status": "pass", "brand_fit": "1", "cta_clear": "1", "human_read": "1",
                   "failure_codes": [], "flagged_phrases": [], "notes": ""}
        with patch.object(qg, "invoke_judge", side_effect=[_judge_raw(**f8_data), _judge_raw(**f9_data)]):
            outcome = qg.run_quality_gates(
                content_text="A clean piece about the trail.", atom_text="the trail",
                cta="Book now", goal_key="promotion", brand_rubric_text="rubric", channel="tiktok",
            )
        gates = [g["gate"] for g in outcome["gate_ledger"]]
        assert gates == [
            "F6_cta_present", "F1_grounding", "F2_banned_patterns", "F4_extreme_length",
            "F8_framework", "F9_brand_voice",
        ]

    def test_blog_channel_runs_all_9_gates(self):
        rubric = qg.get_framework_rubric("promotion")
        f8_data = {"items": [{"criterion": c, "score": "1", "evidence": "q"} for c in rubric]}
        f9_data = {"status": "pass", "brand_fit": "1", "cta_clear": "1", "human_read": "1",
                   "failure_codes": [], "flagged_phrases": [], "notes": ""}
        body = "## Intro\n" + ("word " * 300) + "[R:atom_abc123]"
        with patch.object(qg, "invoke_judge", side_effect=[_judge_raw(**f8_data), _judge_raw(**f9_data)]):
            outcome = qg.run_quality_gates(
                content_text=body, atom_text="the trail", cta="Book now", goal_key="promotion",
                brand_rubric_text="rubric", channel="blog",
            )
        gates = [g["gate"] for g in outcome["gate_ledger"]]
        assert gates == [
            "F6_cta_present", "F1_grounding", "F2_banned_patterns", "F4_extreme_length",
            "F5_atom_density", "F3_structural_variance", "F7_faq_dedup",
            "F8_framework", "F9_brand_voice",
        ]

    def test_extreme_length_measured_on_stripped_text_not_tagged(self):
        # 6000-char ceiling: build content just under it once tags are stripped, but the RAW
        # tagged text (many short tags) pushes it over — must still pass, since F4 measures the
        # stripped length, not the tagged one.
        tag = "[R:atom_abc123]"
        sentence = "A short sentence. "
        tagged_body = f"{tag} ".join([sentence] * 100) + tag * 400  # raw length pushed way over
        assert len(tagged_body) > 6000
        stripped = qg.strip_citation_tags(tagged_body)
        assert len(stripped) < 6000
        assert qg.gate_extreme_length(stripped)["passed"] is True


# ---------------------------------------------------------------- service.write_and_check() leak test
# The single most important test in this file (Nghiep's own framing) — confirms NO [R:/[F: tag
# ever survives into the persisted/returned piece, for a real blog-channel run through the whole
# write_and_check() orchestration, not just the gate functions in isolation.

TENANT_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()

GOAL = {"key": "promotion", "name": "Promotion", "description": "d", "logic": "AIDA", "marketing_term": "AIDA"}
ANGLE = {"idx": 0, "name": "A", "why_it_works": "wa", "formula_fit": "AIDA",
         "best_final_style": "warm", "recommended": True, "chosen": True}

TAGGED_BLOG_CONTENT = (
    "## Why Southern Laos\n"
    "Cross the bamboo bridge at dawn for a quiet start. [R:atom_abc123]\n\n"
    "A short one.\n\n"
    "## What to Expect\n"
    "The falls draw crowds by midday. [R:atom_abc123] Go early instead.\n\n"
    "## FAQ\n\n"
    "**Q: When is the best time to visit?**\n"
    "A: Early morning, before the tour groups arrive. [R:atom_abc123]"
)


def _make_pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _request(channel="blog"):
    return {
        "request_id": str(REQUEST_ID), "tenant_id": str(TENANT_ID), "atom_id": "atom_abc123",
        "trip_id": None, "channel": channel, "goal": "promotion", "cta": "Book a consultation",
        "status": "approved", "created_at": "2026-08-24T00:00:00", "updated_at": "2026-08-24T00:00:00",
        "angles": [ANGLE],
    }


def _echo_insert_as_returning_row(*args):
    """Simulates Postgres's own RETURNING clause: echoes back whatever was actually passed to
    the INSERT, rather than a hand-typed static fixture — a static fixture can't catch a bug
    where write_and_check() computes the right value but forgets to actually pass it into
    _persist_piece() (exactly the class of gap the first version of these 2 tests missed:
    asserting only against a hardcoded mock return value tests nothing about the real code
    path). `args` is (sql, tenant_id, request_id, attempt_number, content_text, status,
    held_reason, gate_ledger_json, repair_log_json) — the exact positional shape
    service.py::_persist_piece()'s one real INSERT call uses."""
    (_sql, tenant_id, request_id, attempt_number, content_text, status, held_reason,
     gate_ledger_json, repair_log_json) = args
    return {
        "piece_id": uuid.uuid4(), "tenant_id": tenant_id, "angle_gate_request_id": request_id,
        "attempt_number": attempt_number, "content_text": content_text, "status": status,
        "held_reason": held_reason, "gate_ledger": json.loads(gate_ledger_json),
        "repair_log": json.loads(repair_log_json), "created_at": datetime.now(timezone.utc),
    }


def _piece_row(**over):
    base = {
        "piece_id": uuid.uuid4(), "tenant_id": TENANT_ID, "angle_gate_request_id": REQUEST_ID,
        "attempt_number": 1, "content_text": "final piece text", "status": "approved",
        "held_reason": None, "gate_ledger": [], "repair_log": [],
        "created_at": datetime.now(timezone.utc),
    }
    base.update(over)
    return base


@pytest.mark.asyncio
class TestWriteAndCheckStripsTagsBeforeOutput:
    async def test_approved_blog_piece_has_no_tag_in_returned_content_or_ledger(self):
        conn = AsyncMock()
        calls = {"n": 0}

        def _fetchrow(*args):
            calls["n"] += 1
            return {"text": "atom text"} if calls["n"] == 1 else _echo_insert_as_returning_row(*args)

        conn.fetchrow.side_effect = _fetchrow
        pool = _make_pool(conn)

        tagged_violation_ledger = [
            {"gate": "F6_cta_present", "passed": True, "violations": [], "repairable": True},
            {"gate": "F1_grounding", "passed": True,
             "violations": ["sentence quotes [R:atom_abc123] here, but passed"], "repairable": True},
        ]
        passing_outcome = {"passed": True, "gate_ledger": tagged_violation_ledger, "first_failure": None}

        with patch.object(service.angle_gate_service, "fetch_request",
                           new=AsyncMock(return_value=_request())), \
             patch.object(service, "fetch_brand_audience", new=AsyncMock(return_value={})), \
             patch.object(service, "fetch_brand_rubric_text", new=AsyncMock(return_value="rubric")), \
             patch.object(service, "get_goal", return_value=GOAL), \
             patch.object(service, "write_content", return_value=(TAGGED_BLOG_CONTENT, 0.02)), \
             patch.object(service, "run_quality_gates", return_value=passing_outcome):
            result = await service.write_and_check(TENANT_ID, REQUEST_ID, pool)

        assert "[R:" not in result["content_text"]
        assert "[F:" not in result["content_text"]
        # confirm the tag-free markdown/prose survived (strip removed only the tag, not content)
        assert "## Why Southern Laos" in result["content_text"]
        assert "Cross the bamboo bridge at dawn" in result["content_text"]
        # gate_ledger's own violation string must be scrubbed too (F1's own quoted-excerpt path)
        ledger_str = str(result["gate_ledger"])
        assert "[R:" not in ledger_str

        # also confirm what was actually sent to the INSERT (not just the mocked RETURNING row)
        insert_args = conn.fetchrow.call_args_list[1][0]
        persisted_content_text = insert_args[4]  # positional order in _persist_piece's SQL
        assert "[R:" not in persisted_content_text

    async def test_held_blog_piece_also_has_no_tag_leak(self):
        # L6 precedent: a held piece is fully visible to the tenant (content + reason + ledger),
        # so it must be scrubbed exactly as thoroughly as an approved one.
        conn = AsyncMock()
        calls = {"n": 0}

        def _fetchrow(*args):
            calls["n"] += 1
            return {"text": "atom text"} if calls["n"] == 1 else _echo_insert_as_returning_row(*args)

        conn.fetchrow.side_effect = _fetchrow
        pool = _make_pool(conn)

        failing_ledger = [
            {"gate": "F6_cta_present", "passed": True, "violations": [], "repairable": True},
            {"gate": "F5_atom_density", "passed": False,
             "violations": ["words 0-300: zero atom citations — first 80 chars: '[R:atom_abc123] stray'"],
             "repairable": True},
        ]
        held_first_failure = failing_ledger[1]
        failing_outcome = {"passed": False, "gate_ledger": failing_ledger, "first_failure": held_first_failure}

        with patch.object(service.angle_gate_service, "fetch_request",
                           new=AsyncMock(return_value=_request())), \
             patch.object(service, "fetch_brand_audience", new=AsyncMock(return_value={})), \
             patch.object(service, "fetch_brand_rubric_text", new=AsyncMock(return_value="rubric")), \
             patch.object(service, "get_goal", return_value=GOAL), \
             patch.object(service, "write_content", return_value=(TAGGED_BLOG_CONTENT, 0.02)), \
             patch.object(service, "rewrite_with_feedback", return_value=(TAGGED_BLOG_CONTENT, 0.02)), \
             patch.object(service, "run_quality_gates", return_value=failing_outcome):
            result = await service.write_and_check(TENANT_ID, REQUEST_ID, pool)

        assert result["status"] == "held"
        assert "[R:" not in (result["held_reason"] or "")
        assert "[R:" not in str(result["gate_ledger"])
        assert "[R:" not in result["content_text"]

    async def test_non_blog_channel_write_unaffected_by_strip_step(self):
        # No tags ever produced for non-blog — confirms the unconditional strip call is a true
        # no-op for the other 7 channels, not a behavior change.
        conn = AsyncMock()
        conn.fetchrow.side_effect = [{"text": "atom text"}, _piece_row(content_text="Plain facebook post.")]
        pool = _make_pool(conn)
        passing_outcome = {
            "passed": True,
            "gate_ledger": [{"gate": "F6_cta_present", "passed": True, "violations": [], "repairable": True}],
            "first_failure": None,
        }

        with patch.object(service.angle_gate_service, "fetch_request",
                           new=AsyncMock(return_value=_request(channel="facebook"))), \
             patch.object(service, "fetch_brand_audience", new=AsyncMock(return_value={})), \
             patch.object(service, "fetch_brand_rubric_text", new=AsyncMock(return_value="rubric")), \
             patch.object(service, "get_goal", return_value=GOAL), \
             patch.object(service, "write_content", return_value=("Plain facebook post.", 0.02)) as mock_write, \
             patch.object(service, "run_quality_gates", return_value=passing_outcome) as mock_gates:
            result = await service.write_and_check(TENANT_ID, REQUEST_ID, pool)

        assert result["content_text"] == "Plain facebook post."
        assert mock_write.call_args.kwargs["atom_id"] == "atom_abc123"
        assert mock_gates.call_args.kwargs["channel"] == "facebook"
