from fastapi import FastAPI, HTTPException, Depends
from contextlib import asynccontextmanager
import asyncpg
import os
import uuid
from shared.repository.raw_tour_repository import RawTourRepository

# DB pool
pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=2, max_size=10)
    yield
    await pool.close()

app = FastAPI(
    title="AA-CIS API",
    version="0.1.0",
    description="Adventure Asia Content Intelligence System",
    lifespan=lifespan,
)

async def get_repo():
    async with pool.acquire() as conn:
        yield RawTourRepository(conn)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "aa-cis-api"}

@app.get("/tours")
async def list_tours(
    limit: int = 50,
    offset: int = 0,
    repo: RawTourRepository = Depends(get_repo)
):
    tours = await repo.list(limit=limit, offset=offset)
    return {"total": len(tours), "limit": limit, "offset": offset, "data": tours}

@app.get("/tours/{tour_id}")
async def get_tour(
    tour_id: str,
    repo: RawTourRepository = Depends(get_repo)
):
    try:
        uuid.UUID(tour_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Tour not found")

    tour = await repo.get_by_id(tour_id)
    if not tour:
        raise HTTPException(status_code=404, detail="Tour not found")
    return tour
