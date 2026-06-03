import json
from unittest.mock import MagicMock, patch

import lessons
from models import LessonUpdateOutput, SystemPromotion


def _make_lesson_output(job=None, root=None, system=None) -> LessonUpdateOutput:
    if system is None:
        system = []
    return LessonUpdateOutput(
        job_lessons=job if job is not None else ["Used long-tail keywords effectively"],
        root_lessons_append=root if root is not None else ["Vietnam travelers prefer 7-10 day itineraries"],  # noqa: E501
        system_promotions=system,
    )


def _make_conn_with_cursor(job_rows, root_rows, system_rows):
    """Build a mock conn where conn.cursor() context manager yields a real cursor mock."""
    cur = MagicMock()
    cur.fetchall.side_effect = [job_rows, root_rows, system_rows]
    conn = MagicMock()
    # conn.cursor() returns cm; `with cm as c:` gives c = cur
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


def _make_write_conn():
    """Build a mock conn for write operations."""
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


class TestReadLessons:
    def test_returns_string(self):
        conn, _ = _make_conn_with_cursor(
            [{"tier": "job", "content": "Used long-tail keywords"}],
            [{"tier": "root", "content": "Vietnam 7-day preference"}],
            [{"content": "Luxury travelers book 3+ months out"}],
        )
        result = lessons.read_lessons(conn, "atlas", "Vietnam")
        assert isinstance(result, str)
        assert "Used long-tail keywords" in result
        assert "Vietnam 7-day preference" in result
        assert "Luxury travelers" in result

    def test_returns_no_prior_lessons_when_empty(self):
        conn, _ = _make_conn_with_cursor([], [], [])
        result = lessons.read_lessons(conn, "atlas", "Vietnam")
        assert result == "No prior lessons."

    def test_sections_present_only_when_data_exists(self):
        conn, _ = _make_conn_with_cursor(
            [{"tier": "job", "content": "job lesson"}],
            [],
            [],
        )
        result = lessons.read_lessons(conn, "atlas", "Vietnam")
        assert "## Recent Run Lessons" in result
        assert "## Country Lessons" not in result
        assert "## System Lessons" not in result


class TestLessonUpdateCall:
    def test_parses_bedrock_response(self):
        output = _make_lesson_output(
            system=[SystemPromotion(content="cross-tenant rule", confidence=0.85)]
        )
        mock_response = json.dumps(output.model_dump())

        with patch("lessons._bedrock_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client_fn.return_value = mock_client
            mock_resp_body = MagicMock()
            mock_resp_body.read.return_value = json.dumps({
                "content": [{"text": mock_response}],
                "usage": {"input_tokens": 80, "output_tokens": 120},
            }).encode()
            mock_client.invoke_model.return_value = {"body": mock_resp_body}
            mock_client.exceptions.ThrottlingException = Exception

            result, in_tok, out_tok = lessons.lesson_update_call(
                "run-1", "atlas", "Vietnam", "existing lessons", "12-week plan summary"
            )

        assert isinstance(result, LessonUpdateOutput)
        assert in_tok == 80
        assert out_tok == 120


class TestWriteLessons:
    def test_inserts_job_and_root_to_agency(self):
        conn, cur = _make_write_conn()
        output = _make_lesson_output(job=["job lesson 1"], root=["root lesson 1"], system=[])

        lessons.write_lessons(conn, "run-1", "atlas", "Vietnam", output)

        assert cur.execute.call_count == 2
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert all("acp_shared.acp_lessons_agency" in s for s in sqls)

    def test_inserts_system_to_shared(self):
        conn, cur = _make_write_conn()
        output = _make_lesson_output(
            job=[], root=[],
            system=[SystemPromotion(content="system lesson", confidence=0.90)],
        )

        lessons.write_lessons(conn, "run-1", "atlas", "Vietnam", output)

        assert cur.execute.call_count == 1
        assert "acp_shared.acp_lessons_shared" in cur.execute.call_args.args[0]

    def test_no_inserts_when_empty(self):
        conn, cur = _make_write_conn()
        output = _make_lesson_output(job=[], root=[], system=[])

        lessons.write_lessons(conn, "run-1", "atlas", "Vietnam", output)

        assert cur.execute.call_count == 0
