"""
shared/secrets.py — Secrets Manager via boto3 SDK
Fetches secrets from AWS Secrets Manager with in-memory TTL cache.
Fallback to env vars for local dev / ECS (which uses task def secret injection).
"""
import json
import os
import time
from functools import lru_cache
from typing import Optional

import structlog

logger = structlog.get_logger()

_cache: dict = {}
_TTL = 3600  # 1 hour refresh


def _fetch_secret_sdk(secret_arn: str) -> str:
    """Fetch secret directly via boto3 SDK."""
    import boto3
    region = os.environ.get("AWS_DEFAULT_REGION", "us-west-1")
    sm = boto3.client("secretsmanager", region_name=region)
    value = sm.get_secret_value(SecretId=secret_arn)["SecretString"]
    logger.info("secret.fetched", arn=secret_arn[-20:])
    return value


def _get_cached(key: str, fetch_fn) -> str:
    now = time.time()
    if key not in _cache or now - _cache.get(f"{key}_ts", 0) > _TTL:
        _cache[key] = fetch_fn()
        _cache[f"{key}_ts"] = now
    return _cache[key]


def get_database_url() -> str:
    """Get DATABASE_URL — Secrets Manager if ARN set, else env var (ECS/local)."""
    arn = os.environ.get("SECRET_DB_ARN")
    if not arn:
        return os.environ["DATABASE_URL"]
    return _get_cached("db_url", lambda: _fetch_secret_sdk(arn))


def get_redis_url() -> str:
    """Get REDIS_URL from env (not sensitive, no need for Secrets Manager)."""
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


def get_dataforseo_creds() -> tuple[str, str]:
    """Get DataForSEO login + password from Secrets Manager or env."""
    arn = os.environ.get("SECRET_DATAFORSEO_ARN")
    if not arn:
        return (
            os.environ.get("DATAFORSEO_LOGIN", ""),
            os.environ.get("DATAFORSEO_PASSWORD", ""),
        )

    def fetch():
        raw = _fetch_secret_sdk(arn)
        data = json.loads(raw)
        return json.dumps(data)

    raw = _get_cached("dataforseo", fetch)
    data = json.loads(raw)
    return data["login"], data["password"]


def get_anthropic_key() -> str:
    """Get Anthropic API key from Secrets Manager or env."""
    arn = os.environ.get("SECRET_ANTHROPIC_ARN")
    if not arn:
        return os.environ.get("ANTHROPIC_API_KEY", "")
    return _get_cached("anthropic_key", lambda: _fetch_secret_sdk(arn))
