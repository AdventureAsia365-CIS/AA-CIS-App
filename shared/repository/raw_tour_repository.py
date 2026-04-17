from .base import BaseRepository
from typing import Any

class RawTourRepository(BaseRepository):

    async def insert(self, data: dict) -> str:
        """Insert one raw tour, return UUID."""
        row = await self.conn.fetchrow("""
            INSERT INTO bronze.raw_tours (
                source_id, tour_id_external, sku, country, name, subtitle,
                duration, group_size, period, summary, description,
                highlights, itineraries, inclusions, exclusions,
                provider, price_raw, links, activities, feature,
                best_time_to_go, source_file, raw_data
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
                $12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23
            ) RETURNING id
        """,
            data.get("source_id"),
            data.get("tour_id_external"),
            data.get("sku"),
            data.get("country"),
            data.get("name"),
            data.get("subtitle"),
            data.get("duration"),
            data.get("group_size"),
            data.get("period"),
            data.get("summary"),
            data.get("description"),
            data.get("highlights"),
            data.get("itineraries"),
            data.get("inclusions"),
            data.get("exclusions"),
            data.get("provider"),
            data.get("price_raw"),
            data.get("links"),
            data.get("activities"),
            data.get("feature"),
            data.get("best_time_to_go"),
            data.get("source_file"),
            data.get("raw_data"),
        )
        return str(row["id"])

    async def insert_batch(self, records: list[dict]) -> list[str]:
        """Insert nhiều tours cùng lúc, return list UUIDs."""
        ids = []
        async with self.conn.transaction():
            for record in records:
                id_ = await self.insert(record)
                ids.append(id_)
        return ids

    async def get_by_id(self, id: str) -> dict | None:
        row = await self.conn.fetchrow(
            "SELECT * FROM bronze.raw_tours WHERE id = $1", id
        )
        return dict(row) if row else None

    async def list(self, limit: int = 50, offset: int = 0) -> list:
        rows = await self.conn.fetch(
            "SELECT * FROM bronze.raw_tours ORDER BY etl_at DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(r) for r in rows]

    async def get_by_source(self, source_id: str) -> list:
        rows = await self.conn.fetch(
            "SELECT * FROM bronze.raw_tours WHERE source_id = $1 ORDER BY etl_at",
            source_id
        )
        return [dict(r) for r in rows]
