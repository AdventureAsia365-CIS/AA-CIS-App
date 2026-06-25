from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncpg
import redis.asyncio as aioredis
import os
import uuid
import structlog

from shared.repository.raw_tour_repository import RawTourRepository
from api.routers.auth import (
    _hash_api_key, _create_jwt, verify_jwt,
    TenantLoginRequest, TenantLoginResponse,
)
from api.routers.v1_tours import router as v1_tours_router
from api.routers.v1_exports import router as v1_exports_router
from api.routers.v1_pipeline import router as v1_pipeline_router
from api.routers.v1_acp import router as v1_acp_router
from api.routers.v1_competitors import router as v1_competitors_router
from api.routers.v1_s0 import router as v1_s0_router
from api.routers.v1_s1 import router as v1_s1_router
from api.routers.v1_s3 import router as v1_s3_router
from api.routers.v1_acp_gate import router as v1_acp_gate_router
from api.routers.v1_rules import router as v1_rules_router
from api.routers.v1_social import router as v1_social_router
from api.routers.v1_s4_blog import router as v1_s4_blog_router
from api.routers.v1_s4_social import router as v1_s4_social_router
from api.routers.admin import router as admin_router
from api.routers.admin_pipeline import router as admin_pipeline_router
from api.routers.admin_acp_proxy import router as admin_acp_proxy_router
from api.routers.admin_settings import router as admin_settings_router
from api.routers.acp_health import router as acp_health_router
from api.middleware.rate_limit import rate_limit_middleware
from api.middleware.sentry_context import sentry_context_middleware
from api.core.sentry import init_sentry
from services.acp.s2.router import router as v1_s2_router, _do_resume_run

logger = structlog.get_logger()
pool: asyncpg.Pool = None

init_sentry()


async def _recover_stuck_s2_runs(pool, graph) -> None:
    """Auto-resume S2 runs stuck at status='running' on ECS restart.

    Grace period: only recovers runs not updated in the last 2 minutes —
    prevents racing with a run that legitimately started just before restart.
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT sr.run_id::text AS run_id, r.tenant_id::text AS tenant_id
                FROM acp_shared.acp_stage_runs sr
                JOIN acp_shared.acp_runs r ON r.run_id = sr.run_id
                WHERE sr.stage = 's2'
                  AND r.status = 'running'
                  AND sr.metadata ? 'checkpointer'
                  AND sr.updated_at < NOW() - INTERVAL '2 minutes'
            """)
        if not rows:
            logger.info("startup_recovery_none")
            return
        logger.warning("startup_recovery_found", count=len(rows))
        for row in rows:
            run_id = row["run_id"]
            tenant_id = row["tenant_id"]
            try:
                await _do_resume_run(run_id, tenant_id, pool, graph)
                logger.info("startup_recovery_resumed", run_id=run_id)
            except Exception as exc:
                logger.error("startup_recovery_failed", run_id=run_id, error=str(exc))
    except Exception as exc:
        logger.error("startup_recovery_error", error=str(exc))


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

    # Build and register S2 graph (async — awaits checkpointer.setup())
    import boto3
    import json as _json

    def _get_api_keys():
        try:
            client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-west-1"))
            secret = client.get_secret_value(SecretId="aa-cis/dev/api-keys")
            return _json.loads(secret["SecretString"])
        except Exception:
            return {}

    from services.acp.s2.graph import get_compiled_s2_graph
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-1"))
    app.state.s2_pg_conn = None
    try:
        app.state.s2_graph, app.state.s2_pg_conn = await get_compiled_s2_graph(
            pool, s3, _get_api_keys(), os.environ["DATABASE_URL"]
        )
    except Exception as e:
        logger.warning("s2_graph_init_failed", error=str(e))
        app.state.s2_graph = None

    if app.state.s2_graph is not None:
        await _recover_stuck_s2_runs(pool, app.state.s2_graph)

    # AA-223: recover run-tour jobs left 'running' by a prior container exit.
    # Best-effort — a transient DB error here must NOT crash boot (crash-loop risk).
    try:
        from api.routers.jobs_repo import sweep_interrupted
        n = await sweep_interrupted()
        logger.info("aa223_startup_sweep", interrupted_jobs=n)
    except Exception as e:
        logger.warning("aa223_startup_sweep_failed", error=repr(e))

    yield
    await pool.close()
    if app.state.s2_pg_conn is not None:
        await app.state.s2_pg_conn.close()
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
        "https://aa-cis.lumiguides.it.com",
        "https://acp.lumiguides.it.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_tours_router)
app.include_router(v1_exports_router)
app.include_router(v1_pipeline_router)
app.include_router(v1_acp_router)
app.include_router(v1_competitors_router)
app.include_router(v1_s0_router)
app.include_router(v1_s1_router, prefix="/acp/s1")
app.include_router(v1_s2_router, prefix="/acp/s2")
app.include_router(v1_s3_router)
app.include_router(v1_acp_gate_router)
app.include_router(v1_rules_router)
app.include_router(v1_social_router)
app.include_router(v1_s4_blog_router)
app.include_router(v1_s4_social_router)
app.include_router(admin_router)
app.include_router(admin_pipeline_router)
app.include_router(admin_acp_proxy_router)
app.include_router(admin_settings_router)
app.include_router(acp_health_router)

app.middleware("http")(rate_limit_middleware)
app.middleware("http")(sentry_context_middleware)

def get_pool() -> asyncpg.Pool:
    if not pool:
        raise HTTPException(status_code=503, detail="DB not ready")
    return pool

async def get_repo(db: asyncpg.Pool = Depends(get_pool)):
    async with db.acquire() as conn:
        yield RawTourRepository(conn, "00000000-0000-0000-0000-000000000001")

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
