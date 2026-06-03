import sentry_sdk
from fastapi import Request


async def sentry_context_middleware(request: Request, call_next):
    sentry_sdk.set_tag("tenant_id", request.headers.get("x-tenant-id", "unknown"))
    sentry_sdk.set_tag("run_id", request.headers.get("x-run-id", ""))
    sentry_sdk.set_tag("route", request.url.path)
    return await call_next(request)
