import asyncpg
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
