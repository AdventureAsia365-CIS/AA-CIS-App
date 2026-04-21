import logging, time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

async def track_api_call(
    pool,
    tenant_id: str,
    endpoint: str,
    method: str,
    status_code: int,
    response_ms: int = None,
):
    """Log API call to tenant_api_usage for billing metrics."""
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO shared.tenant_api_usage
                    (tenant_id, endpoint, method, status_code, response_ms, called_at)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, tenant_id, endpoint, method, status_code, response_ms,
                datetime.now(timezone.utc))
    except Exception as e:
        logger.error(f"Billing track error: {e}")
        # Non-blocking — never fail request due to billing error
