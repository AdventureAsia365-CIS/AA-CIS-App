"""
Integration tests — Gap 3: Export Service + Webhook
PRD v4 S5: Gold RDS write + S3 Gold + Webhook Delivery (HMAC, retry 3x)
"""

import json
import uuid
import pytest
import asyncpg
from unittest.mock import MagicMock

TENANT_A  = "aa_internal"
WEBHOOK_SECRET = "test_webhook_secret_abc123"
DB_DSN = "postgresql://cistest:cistest@127.0.0.1:5432/cis_integration_test"

SAMPLE_CONTENT = {
    "aa_name":      "Ha Long Bay 3-Day Luxury Cruise",
    "aa_subtitle":  "Sail through Vietnam's iconic karst seascape",
    "aa_summary":   "Drift through emerald waters aboard a boutique cruise. Kayak into hidden caves.",
    "aa_highlights": ["Kayak at sunrise", "Sunset cocktails", "Seafood banquet"],
    "aa_itineraries": "Day 1: Board at noon...",
    "seo_title":    "Ha Long Bay 3-Day Cruise | Adventure Asia",
    "seo_meta":     "Discover Ha Long Bay on a 3-day boutique cruise.",
    "country":      "Vietnam",
}


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
async def aconn():
    conn = await asyncpg.connect(DB_DSN)
    yield conn
    # Cleanup
    await conn.execute("""
        TRUNCATE TABLE
            gold_aa_internal.webhook_deliveries,
            gold_aa_internal.content_exports,
            gold_aa_internal.published_tours,
            silver_aa_internal.quality_scores,
            silver_aa_internal.generated_content,
            silver_aa_internal.seo_context,
            silver_aa_internal.raw_tours,
            shared.pipeline_runs
        RESTART IDENTITY CASCADE
    """)
    await conn.close()


@pytest.fixture
def mock_s3():
    s3 = MagicMock()
    s3.put_object.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
    return s3


@pytest.fixture
async def export_svc(aconn, mock_s3):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
    from shared.services.export_service import ExportService
    return ExportService(aconn, s3_client=mock_s3,
                         webhook_secret=WEBHOOK_SECRET)


@pytest.fixture
async def export_svc_no_s3(aconn):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
    from shared.services.export_service import ExportService
    return ExportService(aconn, s3_client=None,
                         webhook_secret=WEBHOOK_SECRET)


async def _seed_raw_tour(conn, tenant_id: str) -> str:
    """Helper: insert a raw tour to satisfy FK for pipeline_status update."""
    tour_id = str(uuid.uuid4())
    await conn.execute("""
        INSERT INTO silver_aa_internal.raw_tours
            (tour_id, batch_id, tenant_id, country, src_name,
             src_subtitle, src_summary, src_highlights, src_itineraries,
             pipeline_status)
        VALUES ($1,$2,$3,'Vietnam','RAW NAME','Sub','Sum','[]','[]','validated')
    """, tour_id, str(uuid.uuid4()), tenant_id)
    return tour_id


# ── Publish Tour Tests ────────────────────────────────────────

class TestPublishTourToGold:

    async def test_publish_tour_creates_gold_row(self, export_svc, aconn):
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        content = {**SAMPLE_CONTENT, "tour_id": tour_id}

        published_id = await export_svc.publish_tour(TENANT_A, content, 0.92)

        row = await aconn.fetchrow(
            "SELECT aa_name, quality_score, is_active FROM gold_aa_internal.published_tours WHERE tour_id = $1::uuid",
            published_id
        )
        assert row is not None
        assert row["aa_name"] == "Ha Long Bay 3-Day Luxury Cruise"
        assert float(row["quality_score"]) == 0.92
        assert row["is_active"] is True

    async def test_publish_tour_sets_pipeline_status_published(self, export_svc, aconn):
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        content = {**SAMPLE_CONTENT, "tour_id": tour_id}

        await export_svc.publish_tour(TENANT_A, content, 0.90)

        status = await aconn.fetchval(
            "SELECT pipeline_status FROM silver_aa_internal.raw_tours WHERE tour_id = $1::uuid",
            tour_id
        )
        assert status == "published"

    async def test_publish_tour_generates_slug(self, export_svc, aconn):
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        content = {**SAMPLE_CONTENT, "tour_id": tour_id}

        await export_svc.publish_tour(TENANT_A, content, 0.91)

        slug = await aconn.fetchval(
            "SELECT slug FROM gold_aa_internal.published_tours WHERE tour_id = $1::uuid",
            tour_id
        )
        assert slug == "ha-long-bay-3-day-luxury-cruise"

    async def test_publish_tour_immutable_on_conflict(self, export_svc, aconn):
        """Second publish of same tour_id → ON CONFLICT DO NOTHING."""
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        content = {**SAMPLE_CONTENT, "tour_id": tour_id}

        await export_svc.publish_tour(TENANT_A, content, 0.92)
        # Try publish again with different score
        await export_svc.publish_tour(TENANT_A, content, 0.55)

        score = await aconn.fetchval(
            "SELECT quality_score FROM gold_aa_internal.published_tours WHERE tour_id = $1::uuid",
            tour_id
        )
        assert float(score) == 0.92  # Original score preserved

    async def test_publish_multiple_tours(self, export_svc, aconn):
        for i in range(3):
            tour_id = await _seed_raw_tour(aconn, TENANT_A)
            content = {**SAMPLE_CONTENT, "tour_id": tour_id,
                       "aa_name": f"Tour {i} Adventure"}
            await export_svc.publish_tour(TENANT_A, content, 0.90)

        count = await aconn.fetchval(
            "SELECT COUNT(*) FROM gold_aa_internal.published_tours WHERE tenant_id = $1",
            TENANT_A
        )
        assert count == 3


# ── Export Job Tests ──────────────────────────────────────────

class TestExportJob:

    async def test_create_export_json(self, export_svc, aconn, mock_s3):
        # Publish a tour first
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        await export_svc.publish_tour(TENANT_A, {**SAMPLE_CONTENT, "tour_id": tour_id}, 0.91)

        result = await export_svc.create_export(TENANT_A, format="json")

        assert result["format"] == "json"
        assert result["total_tours"] == 1
        assert result["status"] == "complete"
        assert f"exports/{TENANT_A}/" in result["s3_path"]
        assert result["s3_path"].endswith(".json")

    async def test_export_calls_s3_put(self, export_svc, aconn, mock_s3):
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        await export_svc.publish_tour(TENANT_A, {**SAMPLE_CONTENT, "tour_id": tour_id}, 0.90)
        await export_svc.create_export(TENANT_A, format="json")

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "aa-cis-gold"

    async def test_export_record_saved_to_db(self, export_svc, aconn):
        result = await export_svc.create_export(TENANT_A, format="csv")

        row = await aconn.fetchrow("""
            SELECT status, format, total_tours
            FROM gold_aa_internal.content_exports
            WHERE export_id = $1::uuid
        """, result["export_id"])

        assert row["status"] == "complete"
        assert row["format"] == "csv"

    @pytest.mark.parametrize("fmt", ["json", "csv", "xml"])
    async def test_export_all_formats(self, export_svc_no_s3, fmt):
        result = await export_svc_no_s3.create_export(TENANT_A, format=fmt)
        assert result["format"] == fmt
        assert result["s3_path"].endswith(f".{fmt}")


# ── Webhook Tests ─────────────────────────────────────────────

class TestWebhookDelivery:

    async def test_trigger_webhook_creates_delivery_record(self, export_svc, aconn):
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        await export_svc.publish_tour(TENANT_A, {**SAMPLE_CONTENT, "tour_id": tour_id}, 0.91)

        delivery_id = await export_svc.trigger_webhook(
            TENANT_A, tour_id, "https://webhook.example.com/tours"
        )

        row = await aconn.fetchrow(
            "SELECT status, hmac_signature, attempt_count FROM gold_aa_internal.webhook_deliveries WHERE id = $1::uuid",
            delivery_id
        )
        assert row["status"] == "pending"
        assert row["hmac_signature"] is not None
        assert len(row["hmac_signature"]) == 64  # SHA256 hex = 64 chars
        assert row["attempt_count"] == 0

    async def test_hmac_signature_is_valid(self, export_svc, aconn):
        """Verify HMAC signature matches expected format."""
        import hashlib, hmac as hmaclib
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        await export_svc.publish_tour(TENANT_A, {**SAMPLE_CONTENT, "tour_id": tour_id}, 0.91)

        delivery_id = await export_svc.trigger_webhook(
            TENANT_A, tour_id, "https://webhook.example.com"
        )
        sig = await aconn.fetchval(
            "SELECT hmac_signature FROM gold_aa_internal.webhook_deliveries WHERE id = $1::uuid",
            delivery_id
        )
        # Must be valid hex SHA256
        assert len(sig) == 64
        int(sig, 16)  # Raises ValueError if not valid hex

    async def test_webhook_delivery_success(self, export_svc, aconn):
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        await export_svc.publish_tour(TENANT_A, {**SAMPLE_CONTENT, "tour_id": tour_id}, 0.91)
        delivery_id = await export_svc.trigger_webhook(
            TENANT_A, tour_id, "https://webhook.example.com"
        )

        await export_svc.record_delivery_result(delivery_id, http_status=200)

        row = await aconn.fetchrow(
            "SELECT status, attempt_count, delivered_at FROM gold_aa_internal.webhook_deliveries WHERE id = $1::uuid",
            delivery_id
        )
        assert row["status"] == "delivered"
        assert row["attempt_count"] == 1
        assert row["delivered_at"] is not None

    async def test_webhook_delivery_retry_on_failure(self, export_svc, aconn):
        """500 response → status = retrying (not failed yet)."""
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        await export_svc.publish_tour(TENANT_A, {**SAMPLE_CONTENT, "tour_id": tour_id}, 0.91)
        delivery_id = await export_svc.trigger_webhook(
            TENANT_A, tour_id, "https://webhook.example.com"
        )

        await export_svc.record_delivery_result(
            delivery_id, http_status=500, error_msg="Internal Server Error"
        )

        row = await aconn.fetchrow(
            "SELECT status, attempt_count, next_retry_at FROM gold_aa_internal.webhook_deliveries WHERE id = $1::uuid",
            delivery_id
        )
        assert row["status"] == "retrying"
        assert row["attempt_count"] == 1
        assert row["next_retry_at"] is not None

    async def test_webhook_fails_after_max_attempts(self, export_svc, aconn):
        """3 failures → status = failed."""
        tour_id = await _seed_raw_tour(aconn, TENANT_A)
        await export_svc.publish_tour(TENANT_A, {**SAMPLE_CONTENT, "tour_id": tour_id}, 0.91)
        delivery_id = await export_svc.trigger_webhook(
            TENANT_A, tour_id, "https://webhook.example.com"
        )

        # 3 failures
        for _ in range(3):
            await export_svc.record_delivery_result(
                delivery_id, http_status=503, error_msg="Service unavailable"
            )

        row = await aconn.fetchrow(
            "SELECT status, attempt_count FROM gold_aa_internal.webhook_deliveries WHERE id = $1::uuid",
            delivery_id
        )
        assert row["status"] == "failed"
        assert row["attempt_count"] == 3

    async def test_trigger_webhook_unknown_tour_raises(self, export_svc):
        with pytest.raises(ValueError, match="not found"):
            await export_svc.trigger_webhook(
                TENANT_A, str(uuid.uuid4()), "https://webhook.example.com"
            )
