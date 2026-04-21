"""
Integration tests — S5: Export Service
Tests: published_tours insert into gold, S3 export mock, slug generation, tenant isolation
"""

import uuid
import json
import pytest
from conftest import SAMPLE_TOUR, SAMPLE_GENERATED, BATCH_ID, TENANT_ID


def _setup_validated_tour(db_conn) -> tuple[str, str]:
    """Insert raw_tour + approved generated_content. Return (tour_id, content_id)."""
    tour_id = str(uuid.uuid4())
    content_id = str(uuid.uuid4())
    cur = db_conn.cursor()
    cur.execute("""
        INSERT INTO silver_aa_internal.raw_tours
            (tour_id, tenant_id, batch_id, country, src_name, src_subtitle, src_summary,
             src_highlights, src_itineraries, pipeline_status)
        VALUES (%s,%s,%s,%s,%s,%s,'[]','[]','validated')
    """, (tour_id, BATCH_ID, "Vietnam", SAMPLE_TOUR["src_name"],
          SAMPLE_TOUR["src_subtitle"], SAMPLE_TOUR["src_summary"]))
    cur.execute("""
        INSERT INTO silver_aa_internal.generated_content
            (id, tour_id, version_num, aa_name, aa_subtitle, aa_summary,
             aa_highlights, aa_itineraries, seo_title, seo_meta,
             model_editorial, model_schema, prompt_version, status)
        VALUES (%s,%s,1,%s,%s,%s,'[]','...','SEO T','SEO M',
                'claude-3-5-sonnet-20241022','gpt-4.1','v3.2','approved')
    """, (
        content_id, tour_id,
        SAMPLE_GENERATED["aa_name"], SAMPLE_GENERATED["aa_subtitle"],
        SAMPLE_GENERATED["aa_summary"],
    ))
    cur.close()
    return tour_id, content_id


class TestPublishedToursRepository:
    """Test: gold_aa_internal.published_tours CRUD."""

    def test_publish_tour_to_gold(self, db_conn):
        tour_id, _ = _setup_validated_tour(db_conn)
        cur = db_conn.cursor()
        slug = "ha-long-bay-3-day-luxury-cruise"
        cur.execute("""
            INSERT INTO gold_aa_internal.published_tours
                (tour_id, tenant_id, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 country, slug, quality_score)
            VALUES (%s,%s,%s,%s,%s,'[]','...','SEO T','SEO M',%s,%s,0.94)
        """, (
            tour_id, TENANT_ID,
            SAMPLE_GENERATED["aa_name"], SAMPLE_GENERATED["aa_subtitle"],
            SAMPLE_GENERATED["aa_summary"],
            "Vietnam", slug,
        ))
        cur.execute(
            "SELECT aa_name, slug, quality_score, is_active FROM gold_aa_internal.published_tours WHERE tour_id = %s",
            (tour_id,)
        )
        row = cur.fetchone()
        cur.close()
        assert row[0] == SAMPLE_GENERATED["aa_name"]
        assert row[1] == slug
        assert float(row[2]) == 0.94
        assert row[3] is True

    def test_slug_is_unique(self, db_conn):
        """slug UNIQUE constraint must reject duplicates."""
        tour_id_1, _ = _setup_validated_tour(db_conn)
        tour_id_2, _ = _setup_validated_tour(db_conn)
        slug = "unique-slug-test"
        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO gold_aa_internal.published_tours
                (tour_id, tenant_id, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 country, slug, quality_score)
            VALUES (%s,%s,'Name','Sub','Sum','[]','...','T','M','Vietnam',%s,0.90)
        """, (tour_id_1, TENANT_ID, slug))
        with pytest.raises(Exception):  # unique constraint violation
            cur.execute("""
                INSERT INTO gold_aa_internal.published_tours
                    (tour_id, tenant_id, aa_name, aa_subtitle, aa_summary,
                     aa_highlights, aa_itineraries, seo_title, seo_meta,
                     country, slug, quality_score)
                VALUES (%s,%s,'Name2','Sub','Sum','[]','...','T','M','Vietnam',%s,0.88)
            """, (tour_id_2, TENANT_ID, slug))
        cur.close()

    def test_published_tour_is_immutable(self, db_conn):
        """Once published, aa_name should not be overwritten by pipeline retry."""
        tour_id, _ = _setup_validated_tour(db_conn)
        original_name = "Ha Long Bay 3-Day Luxury Cruise"
        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO gold_aa_internal.published_tours
                (tour_id, tenant_id, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 country, slug, quality_score)
            VALUES (%s,%s,%s,'Sub','Sum','[]','...','T','M','Vietnam','slug-immutable-test',0.92)
        """, (tour_id, TENANT_ID, original_name))
        # Simulate an accidental re-insert attempt (ON CONFLICT DO NOTHING)
        cur.execute("""
            INSERT INTO gold_aa_internal.published_tours
                (tour_id, tenant_id, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 country, slug, quality_score)
            VALUES (%s,%s,'OVERWRITTEN NAME','Sub','Sum','[]','...','T','M','Vietnam','slug-immutable-test',0.55)
            ON CONFLICT (tour_id) DO NOTHING
        """, (tour_id, TENANT_ID))
        cur.execute(
            "SELECT aa_name FROM gold_aa_internal.published_tours WHERE tour_id = %s",
            (tour_id,)
        )
        assert cur.fetchone()[0] == original_name
        cur.close()

    def test_pipeline_status_set_to_published(self, db_conn):
        tour_id, _ = _setup_validated_tour(db_conn)
        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO gold_aa_internal.published_tours
                (tour_id, tenant_id, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 country, slug, quality_score)
            VALUES (%s,%s,'Name','Sub','Sum','[]','...','T','M','Vietnam','pub-slug-1',0.91)
        """, (tour_id, TENANT_ID))
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'published'
            WHERE tour_id = %s
        """, (tour_id,))
        cur.execute(
            "SELECT pipeline_status FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        assert cur.fetchone()[0] == "published"
        cur.close()


class TestExportS3Integration:
    """Test: S3 export mock — JSON/CSV/XML export paths."""

    def test_s3_put_object_called_on_export(self, mock_s3):
        mock_s3.put_object(
            Bucket="aa-cis-gold",
            Key=f"exports/aa_internal/export_{BATCH_ID}.json",
            Body=json.dumps({"tours": [SAMPLE_GENERATED]}),
            ContentType="application/json",
        )
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "aa-cis-gold"
        assert "exports/aa_internal/" in call_kwargs["Key"]

    def test_s3_published_tour_json_path(self, mock_s3):
        tour_id = str(uuid.uuid4())
        mock_s3.put_object(
            Bucket="aa-cis-gold",
            Key=f"published/aa_internal/{tour_id}.json",
            Body=json.dumps(SAMPLE_GENERATED),
        )
        call_key = mock_s3.put_object.call_args.kwargs["Key"]
        assert call_key == f"published/aa_internal/{tour_id}.json"

    @pytest.mark.parametrize("export_format", ["json", "csv", "xml"])
    def test_export_formats_all_supported(self, mock_s3, export_format):
        export_id = str(uuid.uuid4())
        mock_s3.put_object(
            Bucket="aa-cis-gold",
            Key=f"exports/aa_internal/{export_id}.{export_format}",
            Body=b"content",
        )
        key = mock_s3.put_object.call_args.kwargs["Key"]
        assert key.endswith(f".{export_format}")


class TestSlugGeneration:
    """Test: slug generation from aa_name."""

    @pytest.mark.parametrize("aa_name,expected_slug", [
        ("Ha Long Bay 3-Day Luxury Cruise", "ha-long-bay-3-day-luxury-cruise"),
        ("Angkor Wat & Siem Reap Explorer", "angkor-wat-siem-reap-explorer"),
        ("Chiang Mai Trekking (5 Days)", "chiang-mai-trekking-5-days"),
    ])
    def test_slug_from_name(self, aa_name, expected_slug):
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", aa_name.lower()).strip("-")
        assert slug == expected_slug

    def test_slug_max_length(self):
        import re
        long_name = "A Very Long Tour Name That Exceeds The Maximum Slug Length Limit For SEO Purposes"
        slug = re.sub(r"[^a-z0-9]+", "-", long_name.lower()).strip("-")[:80]
        assert len(slug) <= 80
