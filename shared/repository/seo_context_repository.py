import asyncpg
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
                cache_key, expires_at, people_also_ask, related_keywords
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (cache_key) DO UPDATE SET
                tour_id          = EXCLUDED.tour_id,
                keyword_ideas    = EXCLUDED.keyword_ideas,
                top_keywords     = EXCLUDED.top_keywords,
                demographics     = EXCLUDED.demographics,
                trends           = EXCLUDED.trends,
                people_also_ask  = EXCLUDED.people_also_ask,
                related_keywords = EXCLUDED.related_keywords,
                expires_at       = EXCLUDED.expires_at,
                fetched_at       = NOW()
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
            data.get("people_also_ask", "[]"),
            data.get("related_keywords", "[]"),
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
