"""
Integration tests — S1: Ingestion Service
Tests: Excel parse → Pydantic validate → silver_aa_internal.raw_tours insert
"""

import uuid
import json
import pytest
import psycopg2
from unittest.mock import patch, MagicMock
from conftest import SAMPLE_TOUR, BATCH_ID, TENANT_ID


class TestIngestionRepository:
    """Test: raw_tour repository CRUD against real PostgreSQL."""

    def test_insert_raw_tour(self, db_conn):
        cur = db_conn.cursor()
        tour_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO silver_aa_internal.raw_tours
                (tour_id, batch_id, country, src_name, src_subtitle, src_summary,
                 src_highlights, src_itineraries, pipeline_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            tour_id, BATCH_ID, SAMPLE_TOUR["country"],
            SAMPLE_TOUR["src_name"], SAMPLE_TOUR["src_subtitle"],
            SAMPLE_TOUR["src_summary"],
            json.dumps(SAMPLE_TOUR["src_highlights"]),
            json.dumps(SAMPLE_TOUR["src_itineraries"]),
            "ingested",
        ))
        cur.execute(
            "SELECT tour_id, country, pipeline_status FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        row = cur.fetchone()
        cur.close()

        assert row is not None
        assert row[0] == tour_id
        assert row[1] == "Vietnam"
        assert row[2] == "ingested"

    def test_insert_batch_5_tours(self, db_conn):
        cur = db_conn.cursor()
        tour_ids = [str(uuid.uuid4()) for _ in range(5)]
        for tid in tour_ids:
            cur.execute("""
                INSERT INTO silver_aa_internal.raw_tours
                    (tour_id, batch_id, country, src_name, src_subtitle, src_summary,
                     src_highlights, src_itineraries)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                tid, BATCH_ID, "Thailand", f"Tour {tid[:8]}",
                "Bangkok, Thailand", "A sample tour.", "[]", "[]",
            ))
        cur.execute(
            "SELECT COUNT(*) FROM silver_aa_internal.raw_tours WHERE batch_id = %s",
            (BATCH_ID,)
        )
        count = cur.fetchone()[0]
        cur.close()
        assert count == 5

    def test_pipeline_status_update(self, db_conn):
        cur = db_conn.cursor()
        tour_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO silver_aa_internal.raw_tours
                (tour_id, batch_id, country, src_name, src_subtitle, src_summary,
                 src_highlights, src_itineraries)
            VALUES (%s, %s, %s, %s, %s, %s, '[]', '[]')
        """, (tour_id, BATCH_ID, "Cambodia", "Angkor Wat Tour", "Siem Reap", "Ancient temples."))

        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'seo_done'
            WHERE tour_id = %s
        """, (tour_id,))

        cur.execute(
            "SELECT pipeline_status FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        assert cur.fetchone()[0] == "seo_done"
        cur.close()

    def test_src_name_preserved_as_raw(self, db_conn):
        """ALL-CAPS input from vendor must be stored as-is in bronze/silver."""
        cur = db_conn.cursor()
        tour_id = str(uuid.uuid4())
        raw_name = "HA LONG BAY 3 DAY CRUISE"  # vendor format
        cur.execute("""
            INSERT INTO silver_aa_internal.raw_tours
                (tour_id, batch_id, country, src_name, src_subtitle, src_summary,
                 src_highlights, src_itineraries)
            VALUES (%s, %s, %s, %s, %s, %s, '[]', '[]')
        """, (tour_id, BATCH_ID, "Vietnam", raw_name, "Ha Long Bay", "..."))
        cur.execute(
            "SELECT src_name FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        stored_name = cur.fetchone()[0]
        cur.close()
        # src_name stores raw vendor input — normalization happens in generated_content.aa_name
        assert stored_name == raw_name

    def test_highlights_stored_as_jsonb(self, db_conn):
        cur = db_conn.cursor()
        tour_id = str(uuid.uuid4())
        highlights = ["Kayaking through caves", "Sunset on deck", "Fresh seafood"]
        cur.execute("""
            INSERT INTO silver_aa_internal.raw_tours
                (tour_id, batch_id, country, src_name, src_subtitle, src_summary,
                 src_highlights, src_itineraries)
            VALUES (%s, %s, %s, %s, %s, %s, %s, '[]')
        """, (tour_id, BATCH_ID, "Vietnam", "Test Tour", "Ha Long", "Summary.",
              json.dumps(highlights)))
        cur.execute(
            "SELECT src_highlights FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        stored = cur.fetchone()[0]
        cur.close()
        assert stored == highlights
        assert len(stored) == 3


class TestIngestionPipelineRun:
    """Test: pipeline_runs record lifecycle."""

    def test_create_pipeline_run(self, db_conn):
        cur = db_conn.cursor()
        run_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO shared.pipeline_runs
                (id, tenant_id, batch_id, tours_total)
            VALUES (%s, %s, %s, %s)
        """, (run_id, TENANT_ID, BATCH_ID, 10))
        cur.execute(
            "SELECT tenant_id, tours_total, status FROM shared.pipeline_runs WHERE id = %s",
            (run_id,)
        )
        row = cur.fetchone()
        cur.close()
        assert row[0] == TENANT_ID
        assert row[1] == 10
        assert row[2] == "running"

    def test_pipeline_run_completion(self, db_conn):
        cur = db_conn.cursor()
        run_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO shared.pipeline_runs
                (id, tenant_id, batch_id, tours_total)
            VALUES (%s, %s, %s, 5)
        """, (run_id, TENANT_ID, BATCH_ID))
        cur.execute("""
            UPDATE shared.pipeline_runs
            SET status = 'completed',
                tours_passed = 4,
                tours_hitl = 1,
                cost_usd = 0.85,
                completed_at = NOW()
            WHERE id = %s
        """, (run_id,))
        cur.execute("""
            SELECT status, tours_passed, tours_hitl, cost_usd, completed_at
            FROM shared.pipeline_runs WHERE id = %s
        """, (run_id,))
        row = cur.fetchone()
        cur.close()
        assert row[0] == "completed"
        assert row[1] == 4
        assert row[2] == 1
        assert float(row[3]) == 0.85
        assert row[4] is not None
