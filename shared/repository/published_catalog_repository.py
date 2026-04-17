from .base import BaseRepository
import re
from unidecode import unidecode

class PublishedCatalogRepository(BaseRepository):

    async def upsert(self, data: dict) -> str:
        row = await self.conn.fetchrow("""
            INSERT INTO gold.published_catalog (
                published_version_id, raw_tour_id, name, subtitle,
                country, trip_type, duration, seo_title, seo_meta,
                quality_score, status, slug, published_by
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (slug) DO UPDATE SET
                name          = EXCLUDED.name,
                subtitle      = EXCLUDED.subtitle,
                seo_title     = EXCLUDED.seo_title,
                seo_meta      = EXCLUDED.seo_meta,
                quality_score = EXCLUDED.quality_score,
                status        = EXCLUDED.status,
                updated_at    = NOW()
            RETURNING id
        """,
            data["published_version_id"],
            data["raw_tour_id"],
            data.get("name"),
            data.get("subtitle"),
            data.get("country"),
            data.get("trip_type"),
            data.get("duration"),
            data.get("seo_title"),
            data.get("seo_meta"),
            data.get("quality_score"),
            data.get("status", "draft"),
            data["slug"],
            data.get("published_by", "pipeline"),
        )
        return str(row["id"])

    async def publish(self, id: str) -> None:
        await self.conn.execute("""
            UPDATE gold.published_catalog
            SET status = 'published', published_at = NOW(), updated_at = NOW()
            WHERE id = $1
        """, id)

    async def unpublish(self, id: str) -> None:
        await self.conn.execute("""
            UPDATE gold.published_catalog
            SET status = 'unpublished', unpublished_at = NOW(), updated_at = NOW()
            WHERE id = $1
        """, id)

    async def get_by_id(self, id: str) -> dict | None:
        row = await self.conn.fetchrow(
            "SELECT * FROM gold.published_catalog WHERE id = $1", id
        )
        return dict(row) if row else None

    async def get_by_slug(self, slug: str) -> dict | None:
        row = await self.conn.fetchrow(
            "SELECT * FROM gold.published_catalog WHERE slug = $1", slug
        )
        return dict(row) if row else None

    async def list(self, status: str = None, limit: int = 50, offset: int = 0) -> list:
        if status:
            rows = await self.conn.fetch("""
                SELECT * FROM gold.published_catalog
                WHERE status = $1
                ORDER BY created_at DESC LIMIT $2 OFFSET $3
            """, status, limit, offset)
        else:
            rows = await self.conn.fetch("""
                SELECT * FROM gold.published_catalog
                ORDER BY created_at DESC LIMIT $1 OFFSET $2
            """, limit, offset)
        return [dict(r) for r in rows]

    @staticmethod
    def generate_slug(name: str, country: str = None) -> str:
        text = f"{name} {country}".strip() if country else name
        text = unidecode(text)          # ộ → o, ă → a, etc.
        slug = text.lower()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug[:120]
