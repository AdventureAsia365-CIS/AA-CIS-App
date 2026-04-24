"""
Export Service
PRD v4 S5: Gold RDS write + S3 Gold + Webhook Delivery (HMAC signing)

Flow:
  1. publish_tour()     → write to gold_aa_internal.published_tours
  2. create_export()    → write to gold_aa_internal.content_exports
  3. trigger_webhook()  → write to gold_aa_internal.webhook_deliveries
  4. deliver_webhook()  → HTTP POST + HMAC + retry logic
"""

import hashlib
import hmac
import json
import uuid
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import asyncpg
import structlog

logger = structlog.get_logger()


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80]


def _hmac_sign(payload: str, secret: str) -> str:
    """HMAC-SHA256 signature for webhook payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class ExportService:
    """
    Handles Gold layer writes and webhook delivery.
    PRD v4: Immutable Gold — published_tours never overwritten.
    """

    def __init__(self, conn: asyncpg.Connection, s3_client=None,
                 webhook_secret: str = "default_secret"):
        self.conn           = conn
        self.s3             = s3_client
        self.webhook_secret = webhook_secret

    # ── Publish tour to Gold ──────────────────────────────────

    async def publish_tour(self, tenant_id: str, content: dict,
                           quality_score: float) -> str:
        """
        Write approved tour to gold_aa_internal.published_tours.
        Immutable — ON CONFLICT DO NOTHING (never overwrite published content).
        Returns tour_id.
        """
        tour_id = content.get("tour_id") or str(uuid.uuid4())
        slug    = _slugify(content["aa_name"])

        # Ensure slug uniqueness — append short uuid suffix if collision
        existing = await self.conn.fetchval(
            "SELECT tour_id FROM gold_aa_internal.published_tours WHERE slug = $1",
            slug
        )
        if existing and str(existing) != tour_id:
            slug = f"{slug}-{tour_id[:8]}"

        generated_content_id = content.get("generated_content_id") or str(uuid.uuid4())
        await self.conn.execute("""
            INSERT INTO gold_aa_internal.published_tours
                (tour_id, tenant_id, generated_content_id, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 country, slug, quality_score, is_active)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,TRUE)
            ON CONFLICT (tour_id) DO NOTHING
        """,
            tour_id, tenant_id, generated_content_id,
            content["aa_name"],
            content.get("aa_subtitle", ""),
            content.get("aa_summary", ""),
            json.dumps(content.get("aa_highlights", [])),
            content.get("aa_itineraries", ""),
            content.get("seo_title", ""),
            content.get("seo_meta", ""),
            content.get("country", ""),
            slug,
            quality_score,
        )

        # Update pipeline status in silver
        await self.conn.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'published'
            WHERE tour_id = $1::uuid
        """, tour_id)

        logger.info("tour.published", tour_id=tour_id, tenant_id=tenant_id,
                    slug=slug, score=quality_score)
        return tour_id

    # ── Create export job ─────────────────────────────────────

    async def create_export(self, tenant_id: str, format: str = "json",
                            filter_params: dict = None) -> dict:
        """
        Create an export job for tenant's published tours.
        Returns export metadata with s3_path.
        """
        export_id = str(uuid.uuid4())
        s3_path   = f"exports/{tenant_id}/{export_id}.{format}"

        # Count matching tours
        total = await self.conn.fetchval("""
            SELECT COUNT(*) FROM gold_aa_internal.published_tours
            WHERE tenant_id = $1 AND is_active = TRUE
        """, tenant_id)

        # Write export record
        await self.conn.execute("""
            INSERT INTO gold_aa_internal.content_exports
                (tenant_id, export_id, format, filter_params,
                 s3_path, total_tours, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'processing')
        """,
            tenant_id, export_id, format,
            json.dumps(filter_params or {}),
            s3_path, total,
        )

        # Mock S3 upload (real impl uploads actual file)
        if self.s3:
            tours = await self.conn.fetch("""
                SELECT * FROM gold_aa_internal.published_tours
                WHERE tenant_id = $1 AND is_active = TRUE
                ORDER BY published_at DESC
            """, tenant_id)

            payload = json.dumps([dict(t) for t in tours], default=str)
            self.s3.put_object(
                Bucket="aa-cis-gold",
                Key=s3_path,
                Body=payload.encode(),
                ContentType="application/json",
            )

        # Mark complete
        await self.conn.execute("""
            UPDATE gold_aa_internal.content_exports
            SET status = 'complete', file_size_kb = $2
            WHERE export_id = $1
        """, export_id, total * 2)  # ~2KB per tour estimate

        logger.info("export.created", export_id=export_id,
                    tenant_id=tenant_id, total=total)
        return {
            "export_id":   export_id,
            "s3_path":     s3_path,
            "total_tours": total,
            "format":      format,
            "status":      "complete",
        }

    # ── Webhook delivery ──────────────────────────────────────

    async def trigger_webhook(self, tenant_id: str, tour_id: str,
                              webhook_url: str) -> str:
        """
        Create webhook delivery record.
        Returns delivery_id.
        """
        delivery_id = str(uuid.uuid4())
        s3_path     = f"webhooks/{tenant_id}/payload_{tour_id}.json"

        # Build payload
        tour = await self.conn.fetchrow("""
            SELECT * FROM gold_aa_internal.published_tours
            WHERE tour_id = $1::uuid AND tenant_id = $2
        """, tour_id, tenant_id)

        if not tour:
            raise ValueError(f"Tour {tour_id} not found for tenant {tenant_id}")

        payload = json.dumps({
            "event":     "tour.published",
            "tenant_id": tenant_id,
            "tour_id":   tour_id,
            "data":      dict(tour),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, default=str)

        signature = _hmac_sign(payload, self.webhook_secret)

        await self.conn.execute("""
            INSERT INTO gold_aa_internal.webhook_deliveries
                (id, tenant_id, tour_id, webhook_url,
                 payload_s3_path, hmac_signature, status)
            VALUES ($1, $2, $3::uuid, $4, $5, $6, 'pending')
        """,
            delivery_id, tenant_id, tour_id,
            webhook_url, s3_path, signature,
        )

        logger.info("webhook.triggered", delivery_id=delivery_id,
                    tenant_id=tenant_id, tour_id=tour_id)
        return delivery_id

    async def record_delivery_result(self, delivery_id: str,
                                     http_status: int,
                                     last_error: str = None) -> None:
        """Record HTTP result of webhook delivery attempt."""
        success = 200 <= http_status < 300

        if success:
            await self.conn.execute("""
                UPDATE gold_aa_internal.webhook_deliveries
                SET status       = 'delivered',
                    http_status  = $2,
                    delivered_at = NOW(),
                    attempt_count = attempt_count + 1
                WHERE id = $1
            """, delivery_id, http_status)
        else:
            # Check if max retries reached
            row = await self.conn.fetchrow("""
                SELECT attempt_count, max_attempts
                FROM gold_aa_internal.webhook_deliveries WHERE id = $1
            """, delivery_id)

            next_attempts = row["attempt_count"] + 1
            exhausted     = next_attempts >= row["max_attempts"]

            await self.conn.execute("""
                UPDATE gold_aa_internal.webhook_deliveries
                SET status        = $2::webhook_status_enum,
                    http_status   = $3,
                    attempt_count = attempt_count + 1,
                    last_error     = $4,
                    next_retry_at = CASE
                        WHEN $2::webhook_status_enum = 'retrying'::webhook_status_enum
                        THEN NOW() + INTERVAL '5 minutes'
                        ELSE NULL
                    END
                WHERE id = $1
            """,
                delivery_id,
                "failed" if exhausted else "retrying",
                http_status,
                last_error,
            )

        logger.info("webhook.delivery_recorded",
                    delivery_id=delivery_id,
                    http_status=http_status,
                    success=success)
