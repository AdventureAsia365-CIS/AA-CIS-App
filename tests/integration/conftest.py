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

    # shared schema
    cur.execute("""
        CREATE SCHEMA IF NOT EXISTS shared;
        CREATE TABLE IF NOT EXISTS shared.tenants (
            tenant_id UUID PRIMARY KEY, name TEXT NOT NULL,
            slug TEXT NOT NULL DEFAULT 'default',
            plan_tier TEXT DEFAULT 'internal', api_key_hash TEXT,
            rate_limit_rpm INT DEFAULT 60, is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS shared.pipeline_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID REFERENCES shared.tenants(tenant_id),
            batch_id TEXT NOT NULL, status TEXT DEFAULT 'running',
            tours_total INT DEFAULT 0, tours_passed INT DEFAULT 0,
            tours_hitl INT DEFAULT 0, tours_failed INT DEFAULT 0,
            cost_usd NUMERIC(10,4), tokens_input BIGINT DEFAULT 0,
            tokens_output BIGINT DEFAULT 0, langfuse_trace_url TEXT,
            started_at TIMESTAMPTZ DEFAULT NOW(), completed_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS shared.lessons_registry (
            id SERIAL PRIMARY KEY, lesson_num TEXT UNIQUE NOT NULL,
            category TEXT, validator_fn TEXT, is_active BOOLEAN DEFAULT TRUE,
            failure_code TEXT, example_before TEXT, example_after TEXT,
            version INT DEFAULT 1
        );
    """)

    # silver_aa_internal schema
    cur.execute("""
        CREATE SCHEMA IF NOT EXISTS silver_aa_internal;
        CREATE TABLE IF NOT EXISTS silver_aa_internal.raw_tours (
            tour_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id TEXT NOT NULL, country TEXT, src_name TEXT,
            src_subtitle TEXT, src_summary TEXT,
            src_highlights JSONB, src_itineraries JSONB,
            pipeline_status TEXT DEFAULT 'ingested',
            ingest_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS silver_aa_internal.seo_context (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tour_id UUID REFERENCES silver_aa_internal.raw_tours(tour_id),
            keyword_search TEXT, keyword_ideas JSONB,
            demographics JSONB, trends JSONB, cache_key TEXT,
            fetched_at TIMESTAMPTZ DEFAULT NOW(),
            provider TEXT DEFAULT 'dataforseo'
        );
        CREATE TABLE IF NOT EXISTS silver_aa_internal.generated_content (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tour_id UUID REFERENCES silver_aa_internal.raw_tours(tour_id),
            version_num INT DEFAULT 1, aa_name TEXT, aa_subtitle TEXT,
            aa_summary TEXT, aa_highlights JSONB, aa_itineraries TEXT,
            seo_title TEXT, seo_meta TEXT, model_editorial TEXT,
            model_schema TEXT, prompt_version TEXT,
            retry_count INT DEFAULT 0, status TEXT DEFAULT 'generated',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS silver_aa_internal.quality_scores (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tour_id UUID REFERENCES silver_aa_internal.raw_tours(tour_id),
            content_id UUID REFERENCES silver_aa_internal.generated_content(id),
            overall_score NUMERIC(4,2), lesson_results JSONB,
            passed BOOLEAN, hitl_required BOOLEAN DEFAULT FALSE,
            scored_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # gold_aa_internal schema
    cur.execute("""
        CREATE SCHEMA IF NOT EXISTS gold_aa_internal;
        CREATE TABLE IF NOT EXISTS gold_aa_internal.published_tours (
            tour_id UUID PRIMARY KEY,
            tenant_id UUID REFERENCES shared.tenants(tenant_id),
            aa_name TEXT NOT NULL, aa_subtitle TEXT, aa_summary TEXT,
            aa_highlights JSONB, aa_itineraries TEXT,
            seo_title TEXT, seo_meta TEXT, country TEXT,
            slug TEXT UNIQUE, quality_score NUMERIC(4,2),
            published_at TIMESTAMPTZ DEFAULT NOW(),
            is_active BOOLEAN DEFAULT TRUE
        );
    """)

    cur.execute("""
        INSERT INTO shared.tenants (tenant_id, name, slug, plan_tier, rate_limit_rpm, is_active)
        VALUES ('00000000-0000-0000-0000-000000000001', 'Adventure Asia Internal', 'aa-internal', 'internal', 60, true)
        ON CONFLICT DO NOTHING;
    """)
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
    conn = _get_conn()
    conn.autocommit = True
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
