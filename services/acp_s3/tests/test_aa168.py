"""
AA-168 — H-3 programmatic confidence threshold for system_promotions.

Tests that write_lessons enforces H3_PROMOTION_THRESHOLD (0.80) before
writing to acp_lessons_shared, regardless of what the LLM returned.
"""
import json
from unittest.mock import MagicMock

import lessons
from lessons import H3_PROMOTION_THRESHOLD
from models import LessonUpdateOutput, SystemPromotion


def _make_write_conn():
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


class TestAA168Threshold:
    def test_above_threshold_writes_to_shared(self):
        conn, cur = _make_write_conn()
        output = LessonUpdateOutput(
            job_lessons=[],
            root_lessons_append=[],
            system_promotions=[SystemPromotion(content="cross-tenant rule", confidence=0.81)],
        )
        lessons.write_lessons(conn, "run-1", "atlas", "Vietnam", output)

        assert cur.execute.call_count == 1
        assert "acp_shared.acp_lessons_shared" in cur.execute.call_args.args[0]

    def test_below_threshold_skipped(self):
        conn, cur = _make_write_conn()
        output = LessonUpdateOutput(
            job_lessons=[],
            root_lessons_append=[],
            system_promotions=[SystemPromotion(content="uncertain rule", confidence=0.79)],
        )
        lessons.write_lessons(conn, "run-1", "atlas", "Vietnam", output)

        assert cur.execute.call_count == 0

    def test_exact_threshold_writes(self):
        conn, cur = _make_write_conn()
        output = LessonUpdateOutput(
            job_lessons=[],
            root_lessons_append=[],
            system_promotions=[SystemPromotion(content="boundary rule", confidence=0.80)],
        )
        lessons.write_lessons(conn, "run-1", "atlas", "Vietnam", output)

        assert cur.execute.call_count == 1
        assert "acp_shared.acp_lessons_shared" in cur.execute.call_args.args[0]

    def test_missing_confidence_defaults_zero_skipped(self):
        conn, cur = _make_write_conn()
        # confidence defaults to 0.0 when not provided
        output = LessonUpdateOutput(
            job_lessons=[],
            root_lessons_append=[],
            system_promotions=[SystemPromotion(content="no confidence given")],
        )
        assert output.system_promotions[0].confidence == 0.0

        lessons.write_lessons(conn, "run-1", "atlas", "Vietnam", output)

        assert cur.execute.call_count == 0

    def test_mixed_promotions_only_high_confidence_written(self):
        conn, cur = _make_write_conn()
        output = LessonUpdateOutput(
            job_lessons=[],
            root_lessons_append=[],
            system_promotions=[
                SystemPromotion(content="high confidence", confidence=0.90),
                SystemPromotion(content="low confidence", confidence=0.50),
                SystemPromotion(content="exact boundary", confidence=0.80),
            ],
        )
        lessons.write_lessons(conn, "run-1", "atlas", "Vietnam", output)

        assert cur.execute.call_count == 2
        written_contents = [c.args[1][0] for c in cur.execute.call_args_list]
        assert "high confidence" in written_contents
        assert "exact boundary" in written_contents
        assert "low confidence" not in written_contents

    def test_invalid_json_from_llm_graceful(self):
        """lesson_update_call raises on bad JSON — caller (handler.py) wraps in try/except."""
        from unittest.mock import patch as _patch

        with _patch("lessons._bedrock_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_client.exceptions.ThrottlingException = Exception
            mock_resp_body = MagicMock()
            mock_resp_body.read.return_value = json.dumps({
                "content": [{"text": "not valid json at all!!!"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }).encode()
            mock_client.invoke_model.return_value = {"body": mock_resp_body}

            try:
                lessons.lesson_update_call("run-1", "atlas", "Vietnam", "", "summary")
                raised = False
            except Exception:
                raised = True

        # We expect an exception — caller in handler.py should wrap in try/except
        assert raised

    def test_h3_threshold_constant(self):
        assert H3_PROMOTION_THRESHOLD == 0.80
