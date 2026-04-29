"""
shared/secrets.py — AWS Parameters and Secrets Lambda Extension helper
Fetches secrets from localhost:2773 (extension) instead of calling SDK directly.
Cached in-memory per Lambda execution environment.
"""
import json
import os
import urllib.request
from functools import lru_cache
from typing import Optional


EXTENSION_PORT = os.environ.get("PARAMETERS_SECRETS_EXTENSION_HTTP_PORT", "2773")
EXTENSION_URL  = f"http://localhost:{EXTENSION_PORT}"


def _fetch_secret(secret_arn: str) -> str:
    """
    Fetch secret value from Lambda extension local HTTP server.
    Extension caches secrets in-memory — fast after first call.
    """
    session_token = os.environ.get("AWS_SESSION_TOKEN", "")
    url = f"{EXTENSION_URL}/secretsmanager/get?secretId={secret_arn}"

    req = urllib.request.Request(
        url,
        headers={"X-Aws-Parameters-Secrets-Token": session_token},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
        return data["SecretString"]


@lru_cache(maxsize=20)
def get_secret(secret_arn: str) -> str:
    """
    Get secret string value. Cached per Lambda execution environment.
    Use secret ARN from env var, not hardcoded.
    """
    return _fetch_secret(secret_arn)


@lru_cache(maxsize=20)
def get_secret_json(secret_arn: str) -> dict:
    """Get secret as parsed JSON dict."""
    return json.loads(_fetch_secret(secret_arn))


# ── Convenience helpers for CIS secrets ──────────────────────────────────────

def get_database_url() -> str:
    """Get DATABASE_URL from Secrets Manager via extension."""
    arn = os.environ.get("SECRET_DB_ARN")
    if not arn:
        # Fallback to direct env var (local dev / ECS task def injection)
        return os.environ["DATABASE_URL"]
    return get_secret(arn)


def get_redis_url() -> str:
    """Get REDIS_URL from Secrets Manager via extension."""
    arn = os.environ.get("SECRET_REDIS_ARN")
    if not arn:
        return os.environ.get("REDIS_URL", "redis://localhost:6379")
    return get_secret(arn)


def get_dataforseo_creds() -> tuple[str, str]:
    """Get DataForSEO login + password from Secrets Manager via extension."""
    arn = os.environ.get("SECRET_DATAFORSEO_ARN")
    if not arn:
        # Fallback to env vars
        return (
            os.environ.get("DATAFORSEO_LOGIN", ""),
            os.environ.get("DATAFORSEO_PASSWORD", ""),
        )
    creds = get_secret_json(arn)
    return creds["login"], creds["password"]
