import asyncpg
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
