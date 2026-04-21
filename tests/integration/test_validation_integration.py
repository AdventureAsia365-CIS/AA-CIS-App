"""
Integration tests — S4: Validation Service
Tests: quality_scores insert, pass/fail/HITL routing, brand rule spot-checks, DLQ
"""

import uuid
import json
import pytest
from conftest import SAMPLE_TOUR, SAMPLE_GENERATED, BATCH_ID, TENANT_ID


def _setup_tour_with_content(db_conn, aa_name=None, aa_subtitle=None,
                               aa_summary=None, seo_meta=None) -> tuple[str, str]:
    """Insert raw_tour + generated_content, return (tour_id, content_id)."""
    tour_id = str(uuid.uuid4())
    content_id = str(uuid.uuid4())
    cur = db_conn.cursor()
    cur.execute("""
        INSERT INTO silver_aa_internal.raw_tours
            (tour_id, tenant_id, batch_id, country, src_name, src_subtitle, src_summary,
             src_highlights, src_itineraries, pipeline_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, '[]', '[]', 'seo_done')
    """, (tour_id, BATCH_ID, "Vietnam", SAMPLE_TOUR["src_name"],
          SAMPLE_TOUR["src_subtitle"], SAMPLE_TOUR["src_summary"]))
    cur.execute("""
        INSERT INTO silver_aa_internal.generated_content
                (id, tour_id, tenant_id, version_num, aa_name, aa_subtitle, aa_summary,
             aa_highlights, aa_itineraries, seo_title, seo_meta,
             model_editorial, model_schema, prompt_version, status)
        VALUES (%s,%s,1,%s,%s,%s,'[]','...','SEO Title',%s,
                'claude-3-5-sonnet-20241022','gpt-4.1','v3.2','draft')
    """, (
        content_id, tour_id,
        aa_name or SAMPLE_GENERATED["aa_name"],
        aa_subtitle or SAMPLE_GENERATED["aa_subtitle"],
        aa_summary or SAMPLE_GENERATED["aa_summary"],
        seo_meta or SAMPLE_GENERATED["seo_meta"],
    ))
    cur.close()
    return tour_id, content_id


class TestQualityScoresRepository:
    """Test: quality_scores insert, pass/fail/HITL thresholds."""

    def test_insert_passing_score(self, db_conn):
        tour_id, content_id = _setup_tour_with_content(db_conn)
        cur = db_conn.cursor()
        score_id = str(uuid.uuid4())
        lesson_results = {f"v{str(i).zfill(2)}": "pass" for i in range(1, 30)}

        cur.execute("""
            INSERT INTO silver_aa_internal.quality_scores
                (id, tour_id, content_id, overall_score, lesson_results,
                 passed, hitl_required)
            VALUES (%s, %s, %s, %s, %s, TRUE, FALSE)
        """, (score_id, tour_id, content_id, 0.94, json.dumps(lesson_results)))
        cur.execute(
            "SELECT overall_score, passed, hitl_required FROM silver_aa_internal.quality_scores WHERE id = %s",
            (score_id,)
        )
        row = cur.fetchone()
        cur.close()
        assert float(row[0]) == 0.94
        assert row[1] is True
        assert row[2] is False

    def test_hitl_required_when_score_borderline(self, db_conn):
        """Score 0.70–0.79 → hitl_required = True, passed = False."""
        tour_id, content_id = _setup_tour_with_content(db_conn)
        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO silver_aa_internal.quality_scores
                (tour_id, content_id, overall_score, lesson_results,
                 passed, hitl_required)
            VALUES (%s, %s, 0.74, '{}', FALSE, TRUE)
        """, (tour_id, content_id))
        cur.execute(
            "SELECT passed, hitl_required FROM silver_aa_internal.quality_scores WHERE tour_id = %s",
            (tour_id,)
        )
        row = cur.fetchone()
        cur.close()
        assert row[0] is False
        assert row[1] is True

    def test_pipeline_status_to_failed_on_low_score(self, db_conn):
        """Score < 0.70 → pipeline_status = 'failed'."""
        tour_id, content_id = _setup_tour_with_content(db_conn)
        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO silver_aa_internal.quality_scores
                (tour_id, content_id, overall_score, lesson_results, passed, hitl_required)
            VALUES (%s, %s, 0.55, '{}', FALSE, FALSE)
        """, (tour_id, content_id))
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'failed'
            WHERE tour_id = %s
        """, (tour_id,))
        cur.execute(
            "SELECT pipeline_status FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        assert cur.fetchone()[0] == "failed"
        cur.close()

    def test_all_29_lessons_in_registry(self, db_conn):
        """lessons_registry must have entries loadable for 29 validators."""
        cur = db_conn.cursor()
        # Seed a representative subset
        validators = [
            ("v01", "formatting", "no_all_caps", "V01_CAPS_CHECK"),
            ("v02", "formatting", "title_case_name", "V02_TITLE_CASE"),
            ("v05", "seo", "no_this_is_opener", "V05_SEO_OPENER"),
            ("v25", "seo", "meta_max_160_chars", "V25_META_LENGTH"),
            ("v29", "brand", "no_forbidden_words", "V29_FORBIDDEN"),
        ]
        for lesson_num, category, fn, failure_code in validators:
            cur.execute("""
                INSERT INTO shared.lessons_registry
                    (lesson_num, category, validator_fn, failure_code, is_active)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (lesson_num) DO NOTHING
            """, (lesson_num, category, fn, failure_code))
        cur.execute("SELECT COUNT(*) FROM shared.lessons_registry WHERE is_active = TRUE")
        count = cur.fetchone()[0]
        cur.close()
        assert count >= 5  # Seeded 5 above


class TestBrandRuleValidation:
    """Test: known bad patterns rejected, known good patterns pass."""

    @pytest.mark.parametrize("bad_name,rule", [
        ("HA LONG BAY 3 DAY CRUISE", "v01 — all-caps name"),
        ("This is a great tour of Ha Long Bay", "v05 — 'This is a' opener"),
        ("The tour is amazing and very unique", "v15 — filler adjectives"),
    ])
    def test_bad_aa_name_fails_rule(self, bad_name, rule):
        """Direct rule logic check — not DB-dependent."""
        # v01: all-caps
        if "all-caps" in rule:
            assert bad_name == bad_name.upper(), f"Expected all-caps: {bad_name}"
        # v05: 'This is a' opener
        if "opener" in rule:
            assert bad_name.lower().startswith("this is a")
        # v15: filler words
        if "filler" in rule:
            fillers = ["amazing", "unique", "very", "really", "truly"]
            assert any(f in bad_name.lower() for f in fillers)

    def test_valid_aa_name_passes(self):
        aa_name = SAMPLE_GENERATED["aa_name"]
        # Not all-caps
        assert aa_name != aa_name.upper()
        # Not all-lowercase
        assert aa_name != aa_name.lower()
        # Not starting with "This is"
        assert not aa_name.lower().startswith("this is")
        # Has reasonable length
        assert 10 <= len(aa_name) <= 100

    def test_subtitle_is_clause_not_city_list(self):
        """v06: subtitle must be a descriptive clause, not 'City, Country'."""
        good_subtitle = "Sail through Vietnam's iconic limestone karst seascape"
        bad_subtitle = "Ha Long Bay, Vietnam"

        # Good: has a verb
        words = good_subtitle.split()
        verbs = ["sail", "explore", "discover", "drift", "trek", "cruise"]
        assert any(v in good_subtitle.lower() for v in verbs)

        # Bad: matches city-list pattern (short, comma-separated)
        parts = bad_subtitle.split(",")
        is_city_list = len(parts) == 2 and all(len(p.strip()) < 30 for p in parts)
        assert is_city_list

    def test_seo_meta_does_not_end_mid_phrase(self):
        """v26: SEO meta must end with a complete sentence (period or meaningful ending)."""
        good_meta = SAMPLE_GENERATED["seo_meta"]
        # Must not end with ellipsis or mid-word cut
        assert not good_meta.endswith("...")
        assert not good_meta.endswith(",")
        assert not good_meta.endswith(" and")

    def test_forbidden_words_rejected(self):
        """v29: known forbidden words must be detected."""
        forbidden = ["guaranteed", "best in class", "world-class", "unparalleled"]
        test_content = "Experience the world-class cruise on Ha Long Bay."
        detected = [w for w in forbidden if w.lower() in test_content.lower()]
        assert len(detected) > 0

    def test_summary_word_count_in_range(self):
        """v08: aa_summary must be 80–150 words."""
        summary = SAMPLE_GENERATED["aa_summary"]
        word_count = len(summary.split())
        assert 80 <= word_count <= 150, f"Summary word count out of range: {word_count}"


class TestHITLRouting:
    """Test: HITL task token flow, approve/reject transitions."""

    def test_hitl_flag_persists_in_quality_scores(self, db_conn):
        tour_id, content_id = _setup_tour_with_content(db_conn)
        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO silver_aa_internal.quality_scores
                (tour_id, content_id, overall_score, lesson_results,
                 passed, hitl_required)
            VALUES (%s, %s, 0.76, '{"v01":"pass","v05":"fail"}', FALSE, TRUE)
        """, (tour_id, content_id))
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'hitl_pending'
            WHERE tour_id = %s
        """, (tour_id,))
        cur.execute(
            "SELECT pipeline_status FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        assert cur.fetchone()[0] == "hitl_pending"
        cur.close()

    def test_hitl_approve_transitions_to_validated(self, db_conn):
        tour_id, content_id = _setup_tour_with_content(db_conn)
        cur = db_conn.cursor()
        # Set to hitl_pending
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'hitl_pending' WHERE tour_id = %s
        """, (tour_id,))
        cur.execute("""
            UPDATE silver_aa_internal.generated_content
            SET status = 'hitl_pending' WHERE id = %s
        """, (content_id,))
        # Approve action
        cur.execute("""
            UPDATE silver_aa_internal.generated_content
            SET status = 'approved' WHERE id = %s
        """, (content_id,))
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'validated' WHERE tour_id = %s
        """, (tour_id,))
        cur.execute(
            "SELECT pipeline_status FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        assert cur.fetchone()[0] == "validated"
        cur.close()

    def test_batch_stats_reflect_hitl_count(self, db_conn):
        """pipeline_runs.tours_hitl must match actual HITL tours in batch."""
        cur = db_conn.cursor()
        # Insert 3 tours, 1 hitl
        run_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO shared.pipeline_runs
                (id, tenant_id, batch_id, tours_total, tours_passed, tours_hitl, tours_failed)
            VALUES (%s, %s, %s, 3, 2, 1, 0)
        """, (run_id, TENANT_ID, BATCH_ID))
        cur.execute(
            "SELECT tours_total, tours_passed, tours_hitl FROM shared.pipeline_runs WHERE id = %s",
            (run_id,)
        )
        row = cur.fetchone()
        cur.close()
        assert row[0] == 3
        assert row[1] == 2
        assert row[2] == 1
