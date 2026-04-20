"""
migrate_to_schema_v3.py
Update tất cả repositories và services sang schema-per-tenant Medallion.

Thay đổi chính:
  bronze.raw_sources              → silver_{tenant}.raw_sources
  bronze.raw_tours                → silver_{tenant}.raw_tours
  silver.seo_contexts             → silver_{tenant}.seo_context
  silver.published_tour_versions  → silver_{tenant}.generated_content
  gold.published_catalog          → gold_{tenant}.published_tours

Pattern trong code:
  Mỗi repository nhận thêm tenant_slug: str = "aa_internal"
  SQL queries dùng f-string: f"silver_{tenant_slug}.raw_tours"

Run từ AA-CIS-App root:
  python migrate_to_schema_v3.py
"""
import re
import os
from pathlib import Path

# ── Repository rewrites ──────────────────────────────────────────────────────

RAW_SOURCE_REPO = '''import asyncpg
import structlog

logger = structlog.get_logger()


class RawSourceRepository:
    """Repository for silver_{tenant}.raw_sources table."""

    def __init__(self, conn: asyncpg.Connection, tenant_slug: str = "aa_internal"):
        self.conn = conn
        self.schema = f"silver_{tenant_slug}"

    async def insert(self, data: dict) -> str:
        row = await self.conn.fetchrow(f"""
            INSERT INTO {self.schema}.raw_sources (
                tenant_id, batch_id, filename, s3_path,
                file_size_kb, row_count, parse_errors
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id::text
        """,
            data.get("tenant_id", "00000000-0000-0000-0000-000000000001"),
            data["batch_id"],
            data["filename"],
            data["s3_path"],
            data.get("file_size_kb"),
            data.get("row_count"),
            data.get("parse_errors", "[]"),
        )
        return row["id"]

    async def update_status(self, source_id: str, status: str, row_count: int = None):
        """Update parse status and row count."""
        await self.conn.execute(f"""
            UPDATE {self.schema}.raw_sources
            SET row_count = COALESCE($2, row_count)
            WHERE id = $1::uuid
        """, source_id, row_count)

    async def get_by_id(self, id: str) -> dict | None:
        row = await self.conn.fetchrow(
            f"SELECT * FROM {self.schema}.raw_sources WHERE id = $1::uuid", id
        )
        return dict(row) if row else None

    async def list(self, limit: int = 50, offset: int = 0) -> list:
        rows = await self.conn.fetch(
            f"SELECT * FROM {self.schema}.raw_sources ORDER BY parsed_at DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(r) for r in rows]
'''

RAW_TOUR_REPO = '''import asyncpg
import structlog

logger = structlog.get_logger()


class RawTourRepository:
    """Repository for silver_{tenant}.raw_tours table."""

    def __init__(self, conn: asyncpg.Connection, tenant_slug: str = "aa_internal"):
        self.conn = conn
        self.schema = f"silver_{tenant_slug}"

    async def insert(self, data: dict) -> str:
        row = await self.conn.fetchrow(f"""
            INSERT INTO {self.schema}.raw_tours (
                tenant_id, batch_id, source_id,
                tour_id_external, sku, provider,
                src_name, src_subtitle, src_summary, src_description,
                src_highlights, src_itineraries,
                country, duration, group_size, period,
                price_raw, inclusions, exclusions, links,
                activities, feature, best_time_to_go,
                pipeline_status
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                $21, $22, $23, $24
            )
            RETURNING tour_id::text
        """,
            data.get("tenant_id", "00000000-0000-0000-0000-000000000001"),
            data.get("batch_id"),
            data.get("source_id"),
            data.get("tour_id_external"),
            data.get("sku"),
            data.get("provider"),
            data["src_name"],
            data.get("src_subtitle"),
            data.get("src_summary"),
            data.get("src_description"),
            data.get("src_highlights", "[]"),
            data.get("src_itineraries"),
            data.get("country"),
            data.get("duration"),
            data.get("group_size"),
            data.get("period"),
            data.get("price_raw"),
            data.get("inclusions"),
            data.get("exclusions"),
            data.get("links", "[]"),
            data.get("activities", "[]"),
            data.get("feature"),
            data.get("best_time_to_go"),
            data.get("pipeline_status", "ingested"),
        )
        return row["tour_id"]

    async def update_status(self, tour_id: str, status: str):
        await self.conn.execute(f"""
            UPDATE {self.schema}.raw_tours
            SET pipeline_status = $2::pipeline_status_enum
            WHERE tour_id = $1::uuid
        """, tour_id, status)

    async def get_by_id(self, id: str) -> dict | None:
        row = await self.conn.fetchrow(
            f"SELECT * FROM {self.schema}.raw_tours WHERE tour_id = $1::uuid", id
        )
        return dict(row) if row else None

    async def get_by_source(self, source_id: str) -> list:
        rows = await self.conn.fetch(
            f"SELECT * FROM {self.schema}.raw_tours WHERE source_id = $1::uuid ORDER BY ingest_at",
            source_id
        )
        return [dict(r) for r in rows]

    async def list(self, limit: int = 50, offset: int = 0) -> list:
        rows = await self.conn.fetch(
            f"SELECT * FROM {self.schema}.raw_tours ORDER BY ingest_at DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(r) for r in rows]
'''

SEO_CONTEXT_REPO = '''import asyncpg
import structlog

logger = structlog.get_logger()


class SeoContextRepository:
    """Repository for silver_{tenant}.seo_context table."""

    def __init__(self, conn: asyncpg.Connection, tenant_slug: str = "aa_internal"):
        self.conn = conn
        self.schema = f"silver_{tenant_slug}"

    async def insert(self, data: dict) -> str:
        row = await self.conn.fetchrow(f"""
            INSERT INTO {self.schema}.seo_context (
                tour_id, tenant_id, keyword_search, provider,
                keyword_ideas, demographics, trends, top_keywords,
                cache_key, expires_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id::text
        """,
            data["tour_id"],
            data.get("tenant_id", "00000000-0000-0000-0000-000000000001"),
            data.get("keyword_search"),
            data.get("provider", "dataforseo"),
            data.get("keyword_ideas", "[]"),
            data.get("demographics", "{}"),
            data.get("trends", "{}"),
            data.get("top_keywords", "[]"),
            data.get("cache_key"),
            data.get("expires_at"),
        )
        return row["id"]

    async def get_by_cache_key(self, cache_key: str) -> dict | None:
        row = await self.conn.fetchrow(
            f"SELECT * FROM {self.schema}.seo_context WHERE cache_key = $1 AND expires_at > NOW()",
            cache_key
        )
        return dict(row) if row else None

    async def get_by_id(self, id: str) -> dict | None:
        row = await self.conn.fetchrow(
            f"SELECT * FROM {self.schema}.seo_context WHERE id = $1::uuid", id
        )
        return dict(row) if row else None

    async def list(self, limit: int = 50, offset: int = 0) -> list:
        rows = await self.conn.fetch(
            f"SELECT * FROM {self.schema}.seo_context ORDER BY fetched_at DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(r) for r in rows]
'''

PUBLISHED_CATALOG_REPO = '''import asyncpg
import structlog

logger = structlog.get_logger()


class PublishedCatalogRepository:
    """Repository for gold_{tenant}.published_tours table."""

    def __init__(self, conn: asyncpg.Connection, tenant_slug: str = "aa_internal"):
        self.conn = conn
        self.silver = f"silver_{tenant_slug}"
        self.gold   = f"gold_{tenant_slug}"

    async def insert(self, data: dict) -> str:
        row = await self.conn.fetchrow(f"""
            INSERT INTO {self.gold}.published_tours (
                tour_id, generated_content_id, tenant_id,
                aa_name, aa_subtitle, aa_summary, aa_description,
                aa_highlights, aa_itineraries, mobile_card_text,
                seo_title, seo_meta, seo_keywords_used, og_tags,
                quality_score, quality_score_id,
                s3_gold_path, approved_by
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10, $11, $12, $13, $14,
                $15, $16, $17, $18
            )
            ON CONFLICT (tour_id) DO UPDATE SET
                generated_content_id = EXCLUDED.generated_content_id,
                aa_name              = EXCLUDED.aa_name,
                quality_score        = EXCLUDED.quality_score,
                published_at         = NOW()
            RETURNING id::text
        """,
            data["tour_id"],
            data["generated_content_id"],
            data.get("tenant_id", "00000000-0000-0000-0000-000000000001"),
            data["aa_name"],
            data.get("aa_subtitle"),
            data.get("aa_summary"),
            data.get("aa_description"),
            data.get("aa_highlights", "[]"),
            data.get("aa_itineraries"),
            data.get("mobile_card_text"),
            data.get("seo_title"),
            data.get("seo_meta"),
            data.get("seo_keywords_used", "[]"),
            data.get("og_tags", "{}"),
            data.get("quality_score"),
            data.get("quality_score_id"),
            data.get("s3_gold_path"),
            data.get("approved_by", "auto"),
        )
        return row["id"]

    async def get_by_id(self, id: str) -> dict | None:
        row = await self.conn.fetchrow(
            f"SELECT * FROM {self.gold}.published_tours WHERE id = $1::uuid", id
        )
        return dict(row) if row else None

    async def get_by_tour_id(self, tour_id: str) -> dict | None:
        row = await self.conn.fetchrow(
            f"SELECT * FROM {self.gold}.published_tours WHERE tour_id = $1::uuid", tour_id
        )
        return dict(row) if row else None

    async def list(self, limit: int = 50, offset: int = 0) -> list:
        rows = await self.conn.fetch(
            f"SELECT * FROM {self.gold}.published_tours ORDER BY published_at DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(r) for r in rows]

    async def list_by_country(self, country: str, limit: int = 50) -> list:
        rows = await self.conn.fetch(f"""
            SELECT pt.* FROM {self.gold}.published_tours pt
            JOIN {self.silver}.raw_tours rt ON rt.tour_id = pt.tour_id
            WHERE rt.country = $1
            ORDER BY pt.published_at DESC
            LIMIT $2
        """, country, limit)
        return [dict(r) for r in rows]
'''


def write_file(path: str, content: str):
    """Write content to file, creating directories if needed."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(f"  ✓ Updated: {path}")


def main():
    print("=" * 60)
    print("Schema v3 Migration — Repositories")
    print("=" * 60)
    print()

    base = Path(__file__).parent

    # Update repositories
    print("Updating shared/repository/...")
    write_file(base / "shared/repository/raw_source_repository.py",    RAW_SOURCE_REPO)
    write_file(base / "shared/repository/raw_tour_repository.py",      RAW_TOUR_REPO)
    write_file(base / "shared/repository/seo_context_repository.py",   SEO_CONTEXT_REPO)
    write_file(base / "shared/repository/published_catalog_repository.py", PUBLISHED_CATALOG_REPO)

    print()
    print("=" * 60)
    print("Repositories updated!")
    print()
    print("Next steps — manual updates needed:")
    print()
    print("1. services/ingestion/handler.py")
    print("   → Add tenant_slug param to RawSourceRepository + RawTourRepository init")
    print()
    print("2. services/content_generation/handler.py")
    print("   → SQL INSERT into silver_{tenant}.generated_content")
    print()
    print("3. services/validation/handler.py")
    print("   → SQL SELECT/UPDATE silver_{tenant}.generated_content")
    print()
    print("4. services/export/handler.py")
    print("   → SQL JOIN silver_{tenant}.generated_content + gold_{tenant}.published_tours")
    print()
    print("5. Run: psql ... -f modules/rds/migrations/003_schema_v3.sql")
    print("   → Recreate DB with schema-per-tenant structure")
    print("=" * 60)


if __name__ == "__main__":
    main()
