import asyncpg
import structlog

logger = structlog.get_logger()


class RawTourRepository:
    """
    Repository for silver_{tenant}.raw_tours table.
    Sets app.tenant_id session var before every query — enforces RLS.
    PRD v4: Multi-tenant isolation via PostgreSQL Row Level Security.
    """

    def __init__(self, conn: asyncpg.Connection, tenant_id: str = "00000000-0000-0000-0000-000000000001"):
        self.conn = conn
        self.tenant_id = tenant_id
        # Schema is fixed to silver_aa_internal for internal platform (S0-S6)
        # B2B multi-schema (silver_{tenant_id}) comes in S7
        self.schema = "silver_aa_internal"

    async def _set_tenant_context(self):
        """Set RLS context — must be called in every public method."""
        await self.conn.execute(
            "SELECT set_config('app.tenant_id', $1, true)",
            self.tenant_id
        )

    async def insert(self, data: dict) -> str:
        await self._set_tenant_context()
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
            self.tenant_id,
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
        await self._set_tenant_context()
        await self.conn.execute(f"""
            UPDATE {self.schema}.raw_tours
            SET pipeline_status = $2
            WHERE tour_id = $1::uuid
              AND tenant_id = $3
        """, tour_id, status, self.tenant_id)

    async def get_by_id(self, id: str) -> dict | None:
        await self._set_tenant_context()
        row = await self.conn.fetchrow(
            f"""SELECT * FROM {self.schema}.raw_tours
                WHERE tour_id = $1::uuid AND tenant_id = $2""",
            id, self.tenant_id
        )
        return dict(row) if row else None

    async def get_by_source(self, source_id: str) -> list:
        await self._set_tenant_context()
        rows = await self.conn.fetch(
            f"""SELECT * FROM {self.schema}.raw_tours
                WHERE source_id = $1::uuid AND tenant_id = $2
                ORDER BY ingest_at""",
            source_id, self.tenant_id
        )
        return [dict(r) for r in rows]

    async def list(self, limit: int = 50, offset: int = 0) -> list:
        await self._set_tenant_context()
        rows = await self.conn.fetch(
            f"""SELECT * FROM {self.schema}.raw_tours
                WHERE tenant_id = $1
                ORDER BY ingest_at DESC
                LIMIT $2 OFFSET $3""",
            self.tenant_id, limit, offset
        )
        return [dict(r) for r in rows]

    async def count_by_status(self, status: str) -> int:
        await self._set_tenant_context()
        row = await self.conn.fetchrow(
            f"""SELECT COUNT(*) as cnt FROM {self.schema}.raw_tours
                WHERE tenant_id = $1 AND pipeline_status = $2""",
            self.tenant_id, status
        )
        return row["cnt"]

    async def insert_batch(self, records: list) -> list:
        """Insert nhiều tours cùng lúc, return list tour_id."""
        ids = []
        for record in records:
            tour_id = await self.insert(record)
            ids.append(tour_id)
        return ids
