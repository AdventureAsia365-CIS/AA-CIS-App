from .base import BaseRepository

class SeoContextRepository(BaseRepository):

    async def upsert(self, data: dict) -> str:
        row = await self.conn.fetchrow("""
            INSERT INTO silver.seo_contexts (
                destination, activity, keywords, demographics,
                fetched_at, expires_at
            ) VALUES ($1, $2, $3, $4, NOW(), NOW() + INTERVAL '24 hours')
            ON CONFLICT (destination, activity)
            DO UPDATE SET
                keywords     = EXCLUDED.keywords,
                demographics = EXCLUDED.demographics,
                fetched_at   = NOW(),
                expires_at   = NOW() + INTERVAL '24 hours'
            RETURNING id
        """,
            data["destination"],
            data.get("activity"),
            data.get("keywords"),
            data.get("demographics"),
        )
        return str(row["id"])

    async def get(self, destination: str, activity: str = None) -> dict | None:
        row = await self.conn.fetchrow("""
            SELECT * FROM silver.seo_contexts
            WHERE destination = $1
              AND ($2::text IS NULL OR activity = $2)
              AND expires_at > NOW()
        """, destination, activity)
        return dict(row) if row else None

    async def get_by_id(self, id: str) -> dict | None:
        row = await self.conn.fetchrow(
            "SELECT * FROM silver.seo_contexts WHERE id = $1", id
        )
        return dict(row) if row else None

    async def list(self, limit: int = 50, offset: int = 0) -> list:
        rows = await self.conn.fetch(
            "SELECT * FROM silver.seo_contexts ORDER BY fetched_at DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(r) for r in rows]
