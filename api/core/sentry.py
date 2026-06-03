import logging
import os

import boto3
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

logger = logging.getLogger(__name__)


def _get_dsn() -> str:
    try:
        client = boto3.client(
            "secretsmanager",
            region_name=os.environ.get("AWS_REGION", "us-west-1"),
        )
        secret = client.get_secret_value(SecretId="aa-cis/dev/sentry-dsn-api")
        return secret["SecretString"].strip()
    except Exception as e:
        logger.warning(f"sentry_dsn_fetch_failed: {e}")
        return ""


def init_sentry() -> None:
    dsn = _get_dsn()
    if not dsn:
        logging.warning("Sentry DSN not found — error tracking disabled")
        return
    sentry_sdk.init(
        dsn=dsn,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        environment=os.getenv("ENVIRONMENT", "dev"),
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        release=os.getenv("VERCEL_GIT_COMMIT_SHA", "unknown"),
    )
