from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncpg
import redis.asyncio as aioredis
import os
import uuid

from shared.repository.raw_tour_repository import RawTourRepository
from api.routers.auth import (
    _hash_api_key, _create_jwt, verify_jwt,
    TenantLoginRequest, TenantLoginResponse,
)

from api.routers.v1_tours import router as v1_tours_router
from api.routers.v1_exports import router as v1_exports_router
from api.routers.v1_pipeline import router as v1_pipeline_router
from api.middleware.rate_limit import rate_limit_middleware
pool: asyncpg.Pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    redis = aioredis.from_url(
        f"redis://{os.environ.get('REDIS_HOST', 'aa-cis-dev-redis.wvp8vb.0001.usw1.cache.amazonaws.com')}:6379",
        encoding="utf-8", decode_responses=True
    )
    app.state.redis = redis
    pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"], min_size=2, max_size=10,
    )
    app.state.pool = pool
    yield
    await pool.close()
    await redis.aclose()

app = FastAPI(
    title="AA-CIS API",
    version="0.3.0",
    description="Adventure Asia Content Intelligence System",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://api-cis.lumiguides.it.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_tours_router)
app.include_router(v1_exports_router)
app.include_router(v1_pipeline_router)

app.middleware("http")(rate_limit_middleware)

def get_pool() -> asyncpg.Pool:
    if not pool:
        raise HTTPException(status_code=503, detail="DB not ready")
    return pool

async def get_repo(db: asyncpg.Pool = Depends(get_pool)):
    async with db.acquire() as conn:
        yield RawTourRepository(conn)

@app.post("/auth/tenant-login", response_model=TenantLoginResponse, tags=["auth"])
async def tenant_login(
    body: TenantLoginRequest,
    db: asyncpg.Pool = Depends(get_pool),
):
    if not body.api_key or len(body.api_key) < 10:
        raise HTTPException(status_code=400, detail="Invalid API key format")
    key_hash = _hash_api_key(body.api_key)
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tenant_id::text, name, plan_tier FROM shared.tenants "
            "WHERE api_key_hash = $1 AND is_active = true",
            key_hash,
        )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")
    token = _create_jwt(row["tenant_id"], row["name"], row["plan_tier"])
    return TenantLoginResponse(
        token=token,
        tenant_id=row["tenant_id"],
        tenant_name=row["name"],
        plan_tier=row["plan_tier"],
    )

@app.post("/auth/verify-tenant", tags=["auth"])
async def verify_tenant(request: Request):
    body = await request.json()
    payload = verify_jwt(body.get("token", ""))
    return {
        "valid": True,
        "tenant_id": payload["sub"],
        "name": payload["name"],
        "plan_tier": payload["plan_tier"],
    }

@app.get("/health")
async def health():
    return {"status": "ok", "service": "aa-cis-api", "version": "0.3.0"}

@app.get("/tours")
async def list_tours(
    limit: int = 50,
    offset: int = 0,
    repo: RawTourRepository = Depends(get_repo),
):
    tours = await repo.list(limit=limit, offset=offset)
    return {"total": len(tours), "limit": limit, "offset": offset, "data": tours}

@app.get("/tours/{tour_id}")
async def get_tour(
    tour_id: str,
    repo: RawTourRepository = Depends(get_repo),
):
    try:
        uuid.UUID(tour_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Tour not found")
    tour = await repo.get_by_id(tour_id)
    if not tour:
        raise HTTPException(status_code=404, detail="Tour not found")
    return tour
