import asyncpg
import os
from contextlib import asynccontextmanager

DATABASE_URL = os.environ.get("DATABASE_URL")

async def get_db_connection():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()

async def create_pool():
    return await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
