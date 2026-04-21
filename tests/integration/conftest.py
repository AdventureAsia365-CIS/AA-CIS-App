"""
Integration test fixtures for AA-CIS pipeline.
NO Docker required — connects to local PostgreSQL 16 + fakeredis.
Test DB: cis_integration_test / cistest

Setup (one-time):
    su -c "psql -c \"CREATE USER cistest WITH PASSWORD 'cistest';\"" postgres
    su -c "psql -c \"CREATE DATABASE cis_integration_test OWNER cistest;\"" postgres
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import uuid
import json
import pytest
import psycopg2
import fakeredis
from unittest.mock import MagicMock, AsyncMock, patch
from _constants import (  # noqa: F401 — re-exported for test imports
    SAMPLE_TOUR, SAMPLE_SEO, SAMPLE_GENERATED, TENANT_ID, BATCH_ID
)

# ── Connection params ─────────────────────────────────────────────
DB_HOST = os.environ.get("CIS_TEST_DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("CIS_TEST_DB_PORT", "5432"))
DB_NAME = os.environ.get("CIS_TEST_DB_NAME", "cis_integration_test")
DB_USER = os.environ.get("CIS_TEST_DB_USER", "cistest")
DB_PASS = os.environ.get("CIS_TEST_DB_PASS", "cistest")

_SCHEMA_APPLIED = False


def _get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASS,
    )


def _apply_schema(conn):
    global _SCHEMA_APPLIED
    if _SCHEMA_APPLIED:
        return
    conn.autocommit = True
    cur = conn.cursor()

    # Drop all schemas and recreate fresh
    cur.execute("""
        DROP SCHEMA IF EXISTS gold_aa_internal CASCADE;
        DROP SCHEMA IF EXISTS silver_aa_internal CASCADE;
        DROP SCHEMA IF EXISTS shared CASCADE;
        DROP SCHEMA IF EXISTS ops CASCADE;
        DROP TYPE IF EXISTS pipeline_status_enum CASCADE;
        DROP TYPE IF EXISTS content_status_enum CASCADE;
        DROP TYPE IF EXISTS review_status_enum CASCADE;
        DROP TYPE IF EXISTS webhook_status_enum CASCADE;
    """)

    # Apply real migrations in order
    migrations_dir = os.path.join(
        os.path.dirname(__file__), '..', '..', 'api', 'migrations'
    )
    migration_files = sorted([
        f for f in os.listdir(migrations_dir)
        if f.endswith('.sql') and not f.startswith('007_seed')
        and not f.startswith('007b') and not f.startswith('008')
    ])

    for mf in migration_files:
        fpath = os.path.join(migrations_dir, mf)
        sql = open(fpath).read()
        # Use fresh connection per migration to avoid aborted transaction state
        try:
            mconn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT,
                dbname=DB_NAME, user=DB_USER, password=DB_PASS,
            )
            mconn.autocommit = True
            mcur = mconn.cursor()
            mcur.execute(sql)
            mcur.close()
            mconn.close()
            print(f"Applied: {mf}")
        except Exception as e:
            print(f"Warning {mf}: {e}")
            try: mconn.close()
            except: pass

    # Seed test tenant
    cur.execute("""
        INSERT INTO shared.tenants
            (tenant_id, name, slug, plan_tier, api_key_hash, rate_limit_rpm, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING;
    """, (
        TENANT_ID, 'Test Tenant', 'test-tenant',
        'internal', None, 60, True
    ))

    cur.close()
    _SCHEMA_APPLIED = True


@pytest.fixture(scope="session", autouse=True)
def _setup_schema():
    """Apply schema once per session."""
    conn = _get_conn()
    _apply_schema(conn)
    conn.close()


@pytest.fixture
def db_conn():
    """Function-scoped connection. Truncates all tables on teardown."""
    from _constants import BATCH_ID, TENANT_ID
    conn = _get_conn()
    conn.autocommit = True
    # Seed pipeline_runs for FK constraint
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO shared.pipeline_runs
            (id, tenant_id, batch_id, status, tours_total, tours_passed, tours_hitl, tours_failed, started_at)
        VALUES (%s, %s, %s, 'completed', 0, 0, 0, 0, NOW())
        ON CONFLICT DO NOTHING;
    """, (BATCH_ID, TENANT_ID, BATCH_ID))
    cur.close()
    yield conn
    cur = conn.cursor()
    cur.execute("""
        TRUNCATE TABLE
            gold_aa_internal.published_tours,
            silver_aa_internal.quality_scores,
            silver_aa_internal.generated_content,
            silver_aa_internal.seo_context,
            silver_aa_internal.raw_tours,
            shared.pipeline_runs
        RESTART IDENTITY CASCADE;
    """)
    cur.close()
    conn.close()


# ── fakeredis ─────────────────────────────────────────────────────

_fake_server = fakeredis.FakeServer(version=(7, 0, 0))


@pytest.fixture
def redis_client():
    client = fakeredis.FakeRedis(server=_fake_server, decode_responses=True)
    yield client
    client.flushall()


# ── Mock fixtures ─────────────────────────────────────────────────

@pytest.fixture
def mock_s3():
    with patch("boto3.client") as mock:
        s3 = MagicMock()
        mock.return_value = s3
        s3.put_object.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
        s3.get_object.return_value = {"Body": MagicMock(read=lambda: b'{"tours": []}')}
        yield s3


@pytest.fixture
def mock_llm_client():
    client = AsyncMock()
    client.generate.return_value = {
        "content": SAMPLE_GENERATED,
        "model": "claude-3-5-sonnet-20241022",
        "tokens_input": 1200, "tokens_output": 800,
        "cost_usd": 0.018, "cached": False,
    }
    return client


@pytest.fixture
def mock_dataforseo():
    client = MagicMock()
    client.get_keywords.return_value = SAMPLE_SEO
    return client


@pytest.fixture
def mock_langfuse():
    lf = MagicMock()
    lf.trace.return_value = MagicMock(id="trace-test-001")
    return lf
