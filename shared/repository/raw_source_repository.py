from .base import BaseRepository

class RawSourceRepository(BaseRepository):

    async def insert(self, data: dict) -> str:
        row = await self.conn.fetchrow("""
            INSERT INTO bronze.raw_sources (
                s3_bucket, s3_key, supplier_name,
                original_filename, row_count, status
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """,
            data["s3_bucket"],
            data["s3_key"],
            data.get("supplier_name"),
            data.get("original_filename"),
            data.get("row_count"),
            data.get("status", "queued"),
        )
        return str(row["id"])

    async def update_status(self, id: str, status: str, row_count: int = None, error: str = None):
        await self.conn.execute("""
            UPDATE bronze.raw_sources
            SET status = $2, row_count = $3, error_message = $4
            WHERE id = $1
        """, id, status, row_count, error)

    async def get_by_id(self, id: str) -> dict | None:
        row = await self.conn.fetchrow(
            "SELECT * FROM bronze.raw_sources WHERE id = $1", id
        )
        return dict(row) if row else None

    async def list(self, limit: int = 50, offset: int = 0) -> list:
        rows = await self.conn.fetch(
            "SELECT * FROM bronze.raw_sources ORDER BY uploaded_at DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        return [dict(r) for r in rows]
