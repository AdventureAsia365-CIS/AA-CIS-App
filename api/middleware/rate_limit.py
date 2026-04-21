import time, os, logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from api.routers.auth import verify_jwt

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

    try:
        redis = request.app.state.redis
        window = int(time.time() // 60)
        key = f"ratelimit:{tenant_id}:{window}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 120)
        logger.info(f"Rate limit: tenant={tenant_id} plan={plan_tier} count={count}/{rpm_limit}")
    except Exception as e:
        logger.error(f"Rate limit Redis error: {e}")
        return await call_next(request)

    if count > rpm_limit:
        retry_after = 60 - int(time.time() % 60)
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded. Plan: {plan_tier}, limit: {rpm_limit} RPM"},
            headers={"Retry-After": str(retry_after)}
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(rpm_limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, rpm_limit - count))
    response.headers["X-RateLimit-Plan"] = plan_tier
    return response
