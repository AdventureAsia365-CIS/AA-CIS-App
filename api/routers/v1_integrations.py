"""
/v1/integrations — AA-457 [T11 PR1], tenant-facing third-party integration credentials.

WordPress only for now (T11's blog channel). Tenant-JWT-gated (`get_tenant()`, same shared
dependency v1_publish.py/v1_content_writing.py/v1_angle_gate.py already use — no new auth
mechanism). Every query is scoped by the caller's own `tenant_id`, never trusts a body/query
param for it — same anti-IDOR shape v1_publish.py/v1_competitors.py already established.

Secrets Manager: reuses `acp/cms/{tenant_id}` — the exact naming convention `v1_s4_blog.py`
already invented (confirmed live before this task: 0 secrets ever existed under it). Reuses the
same "arbitrary secret_key string, fetch directly, no caching" pattern
`services/acp_s4_blog/cms/publisher.py::_get_cms_creds()` established — NOT `shared/secrets.py`'s
fixed-ARN-per-env-var pattern, which is the wrong shape for a per-tenant secret space (AA-456
STEP0 §4 covers why explicitly).

The application password itself NEVER touches Postgres — only Secrets Manager. `config` JSONB on
`shared.tenant_integrations` holds only the non-secret `site_url`.

Scope for THIS PR (AA-457): save/update credentials + test-connection + read current status.
NOT in scope: the actual publish endpoint, the content_piece list endpoint, the WordPressAdapter
draft->publish change — all AA-458.
"""
from __future__ import annotations

import ipaddress
import json
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import boto3
import structlog
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.routers.v1_tours import get_tenant

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/integrations", tags=["integrations"])

_SM_REGION = "us-west-1"
_TEST_TIMEOUT = aiohttp.ClientTimeout(total=8)

_BLOCKED_HOSTNAMES = {"localhost"}


class SaveWordPressRequest(BaseModel):
    wp_url: str
    username: str
    app_password: str


def _validate_wp_url(url: str) -> str:
    """Basic SSRF-aware validation for a tenant-supplied WordPress site URL — blocks the
    obvious local/private-IP-literal cases (localhost, 127.0.0.1, 169.254.x.x cloud-metadata
    range, RFC1918 ranges, etc). Deliberately does NOT perform DNS resolution at save time — a
    domain that doesn't resolve yet (typo, not-yet-propagated DNS) is a real-URL-just-unreachable
    case, which is exactly what the test-connection endpoint (not this validator) classifies.
    Returns the trimmed URL or raises ValueError with a message safe to show the tenant."""
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("wp_url must start with https://")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("wp_url must include a valid hostname")
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(".local"):
        raise ValueError("wp_url cannot point to a local address")
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    ):
        raise ValueError("wp_url cannot point to a private or reserved IP address")
    return url


def _sm_client():
    return boto3.client("secretsmanager", region_name=_SM_REGION)


def _put_secret(secret_key: str, value: dict) -> None:
    """Create-or-update — same net effect as v1_s4_blog.py's cms_secret_key convention, just
    given a real writer for the first time (that router only ever built the key string, never
    wrote to it for a real tenant)."""
    client = _sm_client()
    payload = json.dumps(value)
    try:
        client.create_secret(Name=secret_key, SecretString=payload)
        logger.info("integration_secret_created", secret_key=secret_key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceExistsException":
            client.put_secret_value(SecretId=secret_key, SecretString=payload)
            logger.info("integration_secret_updated", secret_key=secret_key)
        else:
            raise


def _get_secret(secret_key: str) -> dict:
    """Same shape as services/acp_s4_blog/cms/publisher.py::_get_cms_creds() — arbitrary
    secret_key at call time, no caching (a connect/test/publish action is a rare, deliberate
    tenant click, not a hot path)."""
    client = _sm_client()
    return json.loads(client.get_secret_value(SecretId=secret_key)["SecretString"])


def _row_to_status(row) -> dict:
    config = row["config"]
    if isinstance(config, str):
        config = json.loads(config)
    return {
        "connected": True,
        "site_url": config.get("site_url"),
        "connected_at": row["connected_at"].isoformat() if row["connected_at"] else None,
        "last_verified_at": row["last_verified_at"].isoformat() if row["last_verified_at"] else None,
        "last_verify_error": row["last_verify_error"],
    }


@router.get("/wordpress")
async def get_wordpress_status(request: Request, tenant=Depends(get_tenant)):
    """Current connection status — never returns the secret itself, only non-secret config +
    verification state. Used by the FE to decide: show the connect form, or the connected state."""
    pool = request.app.state.pool
    tenant_id = tenant["sub"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config, connected_at, last_verified_at, last_verify_error "
            "FROM shared.tenant_integrations WHERE tenant_id = $1::uuid AND integration_type = 'wordpress'",
            tenant_id,
        )
    if not row:
        return {"connected": False, "site_url": None, "connected_at": None,
                "last_verified_at": None, "last_verify_error": None}
    return _row_to_status(row)


@router.post("/wordpress")
async def save_wordpress(body: SaveWordPressRequest, request: Request, tenant=Depends(get_tenant)):
    """Save/update WordPress credentials. Writes the real credential JSON to Secrets Manager at
    acp/cms/{tenant_id}; the DB row only ever gets site_url + the secret's KEY NAME, never the
    application password. connected_at is set only on first connect (ON CONFLICT leaves it
    alone) — a credential UPDATE isn't a new "connection"."""
    try:
        wp_url = _validate_wp_url(body.wp_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not body.username.strip() or not body.app_password.strip():
        raise HTTPException(status_code=422, detail="username and app_password are required")

    pool = request.app.state.pool
    tenant_id = tenant["sub"]
    secret_key = f"acp/cms/{tenant_id}"

    try:
        _put_secret(secret_key, {
            "wp_url": wp_url, "username": body.username, "app_password": body.app_password,
        })
    except ClientError as exc:
        logger.error("integration_secret_write_failed", tenant_id=tenant_id, error=str(exc))
        raise HTTPException(status_code=502, detail="Could not save credentials — try again")

    config = json.dumps({"site_url": wp_url})
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO shared.tenant_integrations
                (tenant_id, integration_type, config, secret_key, connected_at)
            VALUES ($1::uuid, 'wordpress', $2::jsonb, $3, now())
            ON CONFLICT (tenant_id, integration_type) DO UPDATE SET
                config = EXCLUDED.config,
                secret_key = EXCLUDED.secret_key,
                updated_at = now()
            RETURNING config, connected_at, last_verified_at, last_verify_error
            """,
            tenant_id, config, secret_key,
        )

    logger.info("wordpress_integration_saved", tenant_id=tenant_id, site_url=wp_url)
    return _row_to_status(row)


def _classify_test_failure(status: Optional[int], exc: Optional[Exception], invalid_200_body: bool = False) -> str:
    if status == 401:
        return "Wrong username or application password"
    if status == 404:
        return "WordPress REST API is not enabled on this site"
    if status == 200 and invalid_200_body:
        # AA-460: a 200 with the wrong shape/content-type is real and common — WAF/anti-bot
        # challenge pages, maintenance pages, and misconfigured catch-all routes all return
        # 200 at arbitrary paths. Live-verify (AA-457-02) confirmed this exact case: InfinityFree's
        # anti-bot layer returns 200/text-html for every request, previously misread as success
        # for correct AND wrong AND garbage credentials alike.
        return "Unexpected response from this URL — verify it's a WordPress site with REST API enabled"
    if status is not None:
        return f"WordPress returned an unexpected response (HTTP {status})"
    return "Could not connect to this WordPress site — check the URL"


@router.post("/wordpress/test")
async def test_wordpress(request: Request, tenant=Depends(get_tenant)):
    """Real connection test — GET {wp_url}/wp-json/wp/v2/users/me with Basic Auth, the standard
    WordPress Application Password smoke-test. Success -> last_verified_at bumped, error cleared.
    Failure -> last_verify_error set with a classified message, last_verified_at LEFT UNCHANGED
    (a failed retest must not silently mark a previously-good connection as freshly verified)."""
    pool = request.app.state.pool
    tenant_id = tenant["sub"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config, secret_key FROM shared.tenant_integrations "
            "WHERE tenant_id = $1::uuid AND integration_type = 'wordpress'",
            tenant_id,
        )
    if not row or not row["secret_key"]:
        raise HTTPException(status_code=404, detail="WordPress is not connected yet")

    try:
        creds = _get_secret(row["secret_key"])
    except ClientError as exc:
        # AA-457 live-verify (24/08/2026) hit this path via a real, unrelated IAM gap
        # (ECS task role missing secretsmanager:CreateSecret) and this branch logged nothing,
        # making the 502 hard to diagnose from CloudWatch alone — logging added after that.
        logger.error("integration_secret_read_failed", tenant_id=tenant_id,
                     secret_key=row["secret_key"], error=str(exc))
        raise HTTPException(status_code=502, detail="Could not read saved credentials — try reconnecting")

    try:
        wp_url = _validate_wp_url(creds["wp_url"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    status_code: Optional[int] = None
    error: Optional[Exception] = None
    invalid_200_body = False
    try:
        auth = aiohttp.BasicAuth(creds["username"], creds["app_password"])
        async with aiohttp.ClientSession(timeout=_TEST_TIMEOUT) as session:
            async with session.get(f"{wp_url}/wp-json/wp/v2/users/me", auth=auth) as resp:
                status_code = resp.status
                if status_code == 200:
                    # AA-460: status 200 alone doesn't mean this is real WordPress — a WAF/
                    # anti-bot challenge page, a maintenance page, or a misconfigured catch-all
                    # route can all return 200 at this exact path (confirmed live, AA-457-02:
                    # InfinityFree's anti-bot layer did exactly this for every credential tried,
                    # correct and wrong alike). Require content-type + real WordPress user-object
                    # shape (an "id" field) before trusting it.
                    content_type = resp.headers.get("content-type", "")
                    body_text = await resp.text()
                    parsed_body = None
                    if content_type.startswith("application/json"):
                        try:
                            parsed_body = json.loads(body_text)
                        except (json.JSONDecodeError, ValueError):
                            parsed_body = None
                    if not (isinstance(parsed_body, dict) and "id" in parsed_body):
                        invalid_200_body = True
    except Exception as exc:  # noqa: BLE001 — classified below, any network failure lands here
        error = exc

    success = status_code == 200 and not invalid_200_body
    message = None if success else _classify_test_failure(status_code, error, invalid_200_body)

    async with pool.acquire() as conn:
        if success:
            updated = await conn.fetchrow(
                """
                UPDATE shared.tenant_integrations
                SET last_verified_at = now(), last_verify_error = NULL, updated_at = now()
                WHERE tenant_id = $1::uuid AND integration_type = 'wordpress'
                RETURNING config, connected_at, last_verified_at, last_verify_error
                """,
                tenant_id,
            )
        else:
            updated = await conn.fetchrow(
                """
                UPDATE shared.tenant_integrations
                SET last_verify_error = $2, updated_at = now()
                WHERE tenant_id = $1::uuid AND integration_type = 'wordpress'
                RETURNING config, connected_at, last_verified_at, last_verify_error
                """,
                tenant_id, message,
            )

    logger.info("wordpress_test_connection", tenant_id=tenant_id, success=success,
                status_code=status_code, error=str(error) if error else None)

    result = _row_to_status(updated)
    result["success"] = success
    return result


__all__ = ["router"]
