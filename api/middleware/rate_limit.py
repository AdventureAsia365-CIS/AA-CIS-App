import time, os, logging
from fastapi import Request
from fastapi.responses import JSONResponse
from api.routers.auth import verify_jwt
from shared.services.billing_service import track_api_call

logger = logging.getLogger(__name__)

PLAN_RPM = {
    "starter": 60,
    "growth": 300,
    "business": 1000,
    "enterprise": 9999,
}

async def rate_limit_middleware(request: Request, call_next):
    if not request.url.path.startswith("/v1/"):
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return await call_next(request)

    try:
        payload = verify_jwt(auth.split(" ", 1)[1])
    except Exception as e:
        logger.warning(f"Rate limit JWT error: {e}")
        return await call_next(request)

    tenant_id = payload["sub"]
    plan_tier = payload.get("plan_tier", "starter")
    rpm_limit = PLAN_RPM.get(plan_tier, 60)

    # Rate limit check
    try:
        redis = request.app.state.redis
        window = int(time.time() // 60)
        key = f"ratelimit:{tenant_id}:{window}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 120)
    except Exception as e:
        logger.error(f"Rate limit Redis error: {e}")
        count = 0

    if count > rpm_limit:
        retry_after = 60 - int(time.time() % 60)
        # Track 429
        await track_api_call(
            request.app.state.pool,
            tenant_id, request.url.path,
            request.method, 429
        )
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded. Plan: {plan_tier}, limit: {rpm_limit} RPM"},
            headers={"Retry-After": str(retry_after)}
        )

    # Process request + measure time
    start = time.time()
    response = await call_next(request)
    response_ms = int((time.time() - start) * 1000)

    # Track successful call
    await track_api_call(
        request.app.state.pool,
        tenant_id, request.url.path,
        request.method, response.status_code,
        response_ms
    )

    response.headers["X-RateLimit-Limit"] = str(rpm_limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, rpm_limit - count))
    response.headers["X-RateLimit-Plan"] = plan_tier
    return response
