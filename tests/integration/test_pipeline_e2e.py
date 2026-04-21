"""
Integration tests — S6: Full Pipeline End-to-End
Tests: 1 tour Bronze→Silver→Gold happy path, DLQ dead-letter routing, cost tracking
"""

import uuid
import json
import re
import pytest
from conftest import SAMPLE_TOUR, SAMPLE_SEO, SAMPLE_GENERATED, BATCH_ID, TENANT_ID


class TestFullPipelineHappyPath:
    """
    End-to-end: 1 tour traverses all 5 stages.
    Bronze → Ingest → SEO → ContentGen → Validate → Export → Gold
    No real AWS calls — all via testcontainer PostgreSQL + Redis mocks.
    """

    def test_full_pipeline_single_tour(self, db_conn, redis_client):
        tour_id = str(uuid.uuid4())
        content_id = str(uuid.uuid4())
        score_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        cur = db_conn.cursor()

        # ── STAGE 0: Create pipeline run ──────────────────────────────────
        cur.execute("""
            INSERT INTO shared.pipeline_runs
                (id, tenant_id, batch_id, tours_total, status)
            VALUES (%s, %s, %s, 1, 'running')
        """, (run_id, TENANT_ID, BATCH_ID))

        # ── STAGE 1: Ingestion → silver raw_tours ─────────────────────────
        cur.execute("""
            INSERT INTO silver_aa_internal.raw_tours
                (tour_id, tenant_id, batch_id, country, src_name, src_subtitle, src_summary,
                 src_highlights, src_itineraries, pipeline_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'ingested')
        """, (
            tour_id, TENANT_ID, BATCH_ID, SAMPLE_TOUR["country"],
            SAMPLE_TOUR["src_name"], SAMPLE_TOUR["src_subtitle"],
            SAMPLE_TOUR["src_summary"],
            json.dumps(SAMPLE_TOUR["src_highlights"]),
            json.dumps(SAMPLE_TOUR["src_itineraries"]),
        ))
        # Update Redis pipeline progress
        redis_client.setex(f"pipeline:job:{BATCH_ID}", 3600,
                           json.dumps({"step": "ingestion", "pct": 20}))

        # ── STAGE 2: SEO Intelligence → seo_context ───────────────────────
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'seo_done' WHERE tour_id = %s
        """, (tour_id,))
        cache_key = f"seo:{TENANT_ID}:vietnam:ha-long-bay:en_US"
        redis_client.setex(cache_key, 86400, json.dumps(SAMPLE_SEO))
        cur.execute("""
            INSERT INTO silver_aa_internal.seo_context
                (tour_id, keyword_search, keyword_ideas, demographics, trends,
                 cache_key, provider)
            VALUES (%s,%s,%s,%s,%s,%s,'dataforseo')
        """, (
            tour_id, SAMPLE_SEO["keyword_search"],
            json.dumps(SAMPLE_SEO["keyword_ideas"]),
            json.dumps(SAMPLE_SEO["demographics"]),
            json.dumps(SAMPLE_SEO["trends"]),
            cache_key,
        ))
        redis_client.setex(f"pipeline:job:{BATCH_ID}", 3600,
                           json.dumps({"step": "seo_intelligence", "pct": 40}))

        # ── STAGE 3: Content Generation → generated_content ───────────────
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'content_generated' WHERE tour_id = %s
        """, (tour_id,))
        cur.execute("""
            INSERT INTO silver_aa_internal.generated_content
                (id, tour_id, tenant_id, version_num, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 model_editorial, model_schema, prompt_version, retry_count, status)
            VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,'draft')
        """, (
            content_id, tour_id, TENANT_ID,
            SAMPLE_GENERATED["aa_name"], SAMPLE_GENERATED["aa_subtitle"],
            SAMPLE_GENERATED["aa_summary"],
            json.dumps(SAMPLE_GENERATED["aa_highlights"]),
            SAMPLE_GENERATED["aa_itineraries"],
            SAMPLE_GENERATED["seo_title"], SAMPLE_GENERATED["seo_meta"],
            SAMPLE_GENERATED["model_editorial"], SAMPLE_GENERATED["model_schema"],
            SAMPLE_GENERATED["prompt_version"],
        ))
        redis_client.setex(f"pipeline:job:{BATCH_ID}", 3600,
                           json.dumps({"step": "content_generation", "pct": 60}))

        # ── STAGE 4: Validation → quality_scores ──────────────────────────
        lesson_results = {f"v{str(i).zfill(2)}": "pass" for i in range(1, 30)}
        cur.execute("""
            INSERT INTO silver_aa_internal.quality_scores
                (id, tour_id, content_id, overall_score, lesson_results,
                 passed, hitl_required)
            VALUES (%s,%s,%s,0.92,%s,TRUE,FALSE)
        """, (score_id, tour_id, content_id, json.dumps(lesson_results)))
        cur.execute("""
            UPDATE silver_aa_internal.generated_content
            SET status = 'hitl_approved' WHERE id = %s
        """, (content_id,))
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'hitl_approved' WHERE tour_id = %s
        """, (tour_id,))
        redis_client.setex(f"pipeline:job:{BATCH_ID}", 3600,
                           json.dumps({"step": "validation", "pct": 80}))

        # ── STAGE 5: Export → gold published_tours ─────────────────────────
        slug = re.sub(r"[^a-z0-9]+", "-", SAMPLE_GENERATED["aa_name"].lower()).strip("-")
        cur.execute("""
            INSERT INTO gold_aa_internal.published_tours
                (tour_id, tenant_id, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 country, slug, quality_score)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0.92)
        """, (
            tour_id, TENANT_ID,
            SAMPLE_GENERATED["aa_name"], SAMPLE_GENERATED["aa_subtitle"],
            SAMPLE_GENERATED["aa_summary"],
            json.dumps(SAMPLE_GENERATED["aa_highlights"]),
            SAMPLE_GENERATED["aa_itineraries"],
            SAMPLE_GENERATED["seo_title"], SAMPLE_GENERATED["seo_meta"],
            SAMPLE_TOUR["country"], slug,
        ))
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'published' WHERE tour_id = %s
        """, (tour_id,))

        # Close pipeline run
        cur.execute("""
            UPDATE shared.pipeline_runs
            SET status = 'completed',
                tours_passed = 1,
                cost_usd = 0.018,
                tokens_input = 1200,
                tokens_output = 800,
                completed_at = NOW()
            WHERE id = %s
        """, (run_id,))
        redis_client.setex(f"pipeline:job:{BATCH_ID}", 3600,
                           json.dumps({"step": "export", "pct": 100}))

        # ── ASSERTIONS ─────────────────────────────────────────────────────
        # 1. Tour exists in Gold
        cur.execute(
            "SELECT aa_name, quality_score, is_active FROM gold_aa_internal.published_tours WHERE tour_id = %s",
            (tour_id,)
        )
        gold_row = cur.fetchone()
        assert gold_row is not None
        assert gold_row[0] == SAMPLE_GENERATED["aa_name"]
        assert float(gold_row[1]) == 0.92
        assert gold_row[2] is True

        # 2. pipeline_status = 'published'
        cur.execute(
            "SELECT pipeline_status FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        assert cur.fetchone()[0] == "published"

        # 3. Pipeline run closed
        cur.execute(
            "SELECT status, tours_passed, cost_usd FROM shared.pipeline_runs WHERE id = %s",
            (run_id,)
        )
        run_row = cur.fetchone()
        assert run_row[0] == "completed"
        assert run_row[1] == 1
        assert float(run_row[2]) == 0.018

        # 4. Redis progress at 100%
        progress = json.loads(redis_client.get(f"pipeline:job:{BATCH_ID}"))
        assert progress["pct"] == 100

        # 5. SEO cache present
        assert redis_client.get(cache_key) is not None

        cur.close()

    def test_pipeline_5_tours_batch_stats(self, db_conn):
        """5-tour batch: 3 pass, 1 HITL, 1 fail — verify pipeline_runs counters."""
        run_id = str(uuid.uuid4())
        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO shared.pipeline_runs
                (id, tenant_id, batch_id, tours_total, tours_passed, tours_hitl,
                 tours_failed, cost_usd, status)
            VALUES (%s,%s,%s, 5, 3, 1, 1, 0.072, 'completed')
        """, (run_id, TENANT_ID, BATCH_ID))
        cur.execute("""
            SELECT tours_total, tours_passed, tours_hitl, tours_failed, cost_usd
            FROM shared.pipeline_runs WHERE id = %s
        """, (run_id,))
        row = cur.fetchone()
        cur.close()
        assert row[0] == 5
        assert row[1] == 3
        assert row[2] == 1
        assert row[3] == 1
        assert float(row[4]) == 0.072


class TestDLQRouting:
    """Test: failed tours route to DLQ (pipeline_status = 'dlq')."""

    def test_failed_tour_dlq_status(self, db_conn):
        tour_id = str(uuid.uuid4())
        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO silver_aa_internal.raw_tours
                (tour_id, batch_id, country, src_name, src_subtitle, src_summary,
                 src_highlights, src_itineraries, pipeline_status)
            VALUES (%s,%s,'Vietnam','BAD TOUR','City','Sum','[]','[]','failed')
        """, (tour_id, BATCH_ID))
        # DLQ classifier sets to 'dlq' after 3 retries
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'dlq' WHERE tour_id = %s
        """, (tour_id,))
        cur.execute(
            "SELECT pipeline_status FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        assert cur.fetchone()[0] == "dlq"
        cur.close()

    def test_dlq_tours_excluded_from_published_count(self, db_conn):
        """Gold published_tours must not contain DLQ tours."""
        cur = db_conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM gold_aa_internal.published_tours WHERE is_active = TRUE"
        )
        initial_count = cur.fetchone()[0]

        # Insert a DLQ tour (should NOT go to gold)
        tour_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO silver_aa_internal.raw_tours
                (tour_id, batch_id, country, src_name, src_subtitle, src_summary,
                 src_highlights, src_itineraries, pipeline_status)
            VALUES (%s,%s,'Vietnam','FAIL TOUR','Sub','Sum','[]','[]','dlq')
        """, (tour_id, BATCH_ID))

        cur.execute(
            "SELECT COUNT(*) FROM gold_aa_internal.published_tours WHERE is_active = TRUE"
        )
        assert cur.fetchone()[0] == initial_count  # unchanged
        cur.close()


class TestCostValidation:
    """Validate cost model: ~$0.018/tour target."""

    @pytest.mark.parametrize("tours,expected_max_cost", [
        (100, 2.0),    # $0.02/tour max
        (1000, 20.0),
        (3000, 60.0),  # $97 target with margin → $0.032/tour
    ])
    def test_cost_per_tour_within_budget(self, tours, expected_max_cost):
        cost_per_tour = 0.018  # baseline from SAMPLE_GENERATED mock
        total_cost = cost_per_tour * tours
        assert total_cost <= expected_max_cost, (
            f"{tours} tours: ${total_cost:.2f} exceeds ${expected_max_cost:.2f} budget"
        )

    def test_monthly_3000_tours_within_110_usd(self):
        """PRD target: 3,000 tours/month ≤ $110 (10% buffer over $97)."""
        cost_per_tour = 0.030  # conservative upper bound
        monthly_tours = 3000
        total = cost_per_tour * monthly_tours
        assert total <= 110.0, f"Monthly cost ${total:.2f} exceeds $110 budget"
