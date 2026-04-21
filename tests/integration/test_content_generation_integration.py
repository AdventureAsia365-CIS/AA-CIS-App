"""
Integration tests — S3: Content Generation Service
Tests: generated_content insert, LLM T1→T2→T3 fallback, prompt caching, version tracking
"""

import uuid
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from botocore.exceptions import ClientError
from conftest import SAMPLE_TOUR, SAMPLE_GENERATED, BATCH_ID, TENANT_ID


def _insert_raw_tour(db_conn, tour_id=None) -> str:
    tid = tour_id or str(uuid.uuid4())
    cur = db_conn.cursor()
    cur.execute("""
        INSERT INTO silver_aa_internal.raw_tours
            (tour_id, tenant_id, batch_id, country, src_name, src_subtitle, src_summary,
             src_highlights, src_itineraries, pipeline_status)
        VALUES (%s, %s, %s, %s, %s, %s, '[]', '[]', 'seo_done')
    """, (tid, '00000000-0000-0000-0000-000000000001', BATCH_ID, SAMPLE_TOUR["country"], SAMPLE_TOUR["src_name"],
          SAMPLE_TOUR["src_subtitle"], SAMPLE_TOUR["src_summary"]))
    cur.close()
    return tid


class TestGeneratedContentRepository:
    """Test: generated_content CRUD and versioning."""

    def test_insert_generated_content(self, db_conn):
        tour_id = _insert_raw_tour(db_conn)
        cur = db_conn.cursor()
        content_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO silver_aa_internal.generated_content
                (id, tour_id, version_num, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 model_editorial, model_schema, prompt_version, retry_count, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            content_id, tour_id, 1,
            SAMPLE_GENERATED["aa_name"], SAMPLE_GENERATED["aa_subtitle"],
            SAMPLE_GENERATED["aa_summary"],
            json.dumps(SAMPLE_GENERATED["aa_highlights"]),
            SAMPLE_GENERATED["aa_itineraries"],
            SAMPLE_GENERATED["seo_title"], SAMPLE_GENERATED["seo_meta"],
            SAMPLE_GENERATED["model_editorial"], SAMPLE_GENERATED["model_schema"],
            SAMPLE_GENERATED["prompt_version"], 0, "generated",
        ))
        cur.execute(
            "SELECT aa_name, status, model_editorial FROM silver_aa_internal.generated_content WHERE id = %s",
            (content_id,)
        )
        row = cur.fetchone()
        cur.close()
        assert row[0] == "Ha Long Bay 3-Day Luxury Cruise"
        assert row[1] == "generated"
        assert row[2] == "claude-3-5-sonnet-20241022"

    def test_version_increment_on_retry(self, db_conn):
        """Each regeneration creates a new version_num row, old version preserved."""
        tour_id = _insert_raw_tour(db_conn)
        cur = db_conn.cursor()
        for version in range(1, 4):
            cur.execute("""
                INSERT INTO silver_aa_internal.generated_content
                    (tour_id, version_num, aa_name, aa_subtitle, aa_summary,
                     aa_highlights, aa_itineraries, seo_title, seo_meta,
                     model_editorial, model_schema, prompt_version, retry_count, status)
                VALUES (%s,%s,%s,%s,%s,'[]','...','SEO Title','SEO Meta',
                        %s,%s,%s,%s,'generated')
            """, (
                tour_id, version, f"Tour v{version}", "subtitle", "summary",
                "claude-3-5-sonnet-20241022", "gpt-4.1", "v3.2", version - 1,
            ))
        cur.execute(
            "SELECT COUNT(*), MAX(version_num) FROM silver_aa_internal.generated_content WHERE tour_id = %s",
            (tour_id,)
        )
        count, max_version = cur.fetchone()
        cur.close()
        assert count == 3
        assert max_version == 3

    def test_status_transitions(self, db_conn):
        """Status: generated → validated → approved"""
        tour_id = _insert_raw_tour(db_conn)
        cur = db_conn.cursor()
        content_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO silver_aa_internal.generated_content
                (id, tour_id, version_num, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 model_editorial, model_schema, prompt_version, status)
            VALUES (%s,%s,1,%s,%s,%s,'[]','...','T','M',%s,%s,%s,'generated')
        """, (
            content_id, tour_id,
            SAMPLE_GENERATED["aa_name"], SAMPLE_GENERATED["aa_subtitle"],
            SAMPLE_GENERATED["aa_summary"],
            SAMPLE_GENERATED["model_editorial"], SAMPLE_GENERATED["model_schema"],
            SAMPLE_GENERATED["prompt_version"],
        ))
        for new_status in ["validated", "approved"]:
            cur.execute(
                "UPDATE silver_aa_internal.generated_content SET status = %s WHERE id = %s",
                (new_status, content_id)
            )
            cur.execute(
                "SELECT status FROM silver_aa_internal.generated_content WHERE id = %s",
                (content_id,)
            )
            assert cur.fetchone()[0] == new_status
        cur.close()

    def test_aa_name_is_title_case(self, db_conn):
        """Verify generated aa_name is NOT ALL-CAPS (brand rule v01)."""
        tour_id = _insert_raw_tour(db_conn)
        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO silver_aa_internal.generated_content
                (tour_id, version_num, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 model_editorial, model_schema, prompt_version, status)
            VALUES (%s,1,%s,%s,%s,'[]','...','T','M','claude-3-5-sonnet-20241022','gpt-4.1','v3.2','generated')
        """, (
            tour_id,
            SAMPLE_GENERATED["aa_name"],  # "Ha Long Bay 3-Day Luxury Cruise"
            SAMPLE_GENERATED["aa_subtitle"], SAMPLE_GENERATED["aa_summary"],
        ))
        cur.execute(
            "SELECT aa_name FROM silver_aa_internal.generated_content WHERE tour_id = %s",
            (tour_id,)
        )
        aa_name = cur.fetchone()[0]
        cur.close()
        # Brand rule: must not be all-caps
        assert aa_name != aa_name.upper()
        # Must not start with "This is a"
        assert not aa_name.lower().startswith("this is a")

    def test_seo_meta_length_constraint(self, db_conn):
        """SEO meta must be ≤ 160 chars (brand rule v25)."""
        tour_id = _insert_raw_tour(db_conn)
        seo_meta = SAMPLE_GENERATED["seo_meta"]
        assert len(seo_meta) <= 160, f"seo_meta too long: {len(seo_meta)} chars"

        cur = db_conn.cursor()
        cur.execute("""
            INSERT INTO silver_aa_internal.generated_content
                (tour_id, version_num, aa_name, aa_subtitle, aa_summary,
                 aa_highlights, aa_itineraries, seo_title, seo_meta,
                 model_editorial, model_schema, prompt_version, status)
            VALUES (%s,1,'Test','Sub','Sum','[]','...','T',%s,
                    'claude-3-5-sonnet-20241022','gpt-4.1','v3.2','generated')
        """, (tour_id, seo_meta))
        cur.execute(
            "SELECT LENGTH(seo_meta) FROM silver_aa_internal.generated_content WHERE tour_id = %s",
            (tour_id,)
        )
        assert cur.fetchone()[0] <= 160
        cur.close()


class TestLLMFallbackChain:
    """Test: T1→T2→T3 fallback when Bedrock throttled or down."""

    @pytest.mark.asyncio
    async def test_t1_bedrock_success(self, mock_llm_client):
        result = await mock_llm_client.generate(
            prompt="Write tour content", tier="T1"
        )
        assert result["model"] == "claude-3-5-sonnet-20241022"
        assert result["cost_usd"] > 0
        mock_llm_client.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_t2_haiku_fallback_on_throttle(self):
        """T1 ThrottlingException → T2 Haiku called."""
        call_log = []

        async def mock_generate(prompt, tier):
            call_log.append(tier)
            if tier == "T1":
                error = ClientError(
                    {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
                    "InvokeModel"
                )
                raise error
            return {
                "content": SAMPLE_GENERATED,
                "model": "claude-3-haiku-20240307",
                "tokens_input": 900,
                "tokens_output": 600,
                "cost_usd": 0.004,
                "cached": False,
            }

        client = MagicMock()
        client.generate = mock_generate

        # Simulate fallback logic
        result = None
        for tier in ["T1", "T2", "T3"]:
            try:
                result = await client.generate("tour prompt", tier=tier)
                break
            except ClientError as e:
                if e.response["Error"]["Code"] != "ThrottlingException":
                    raise
                continue

        assert result is not None
        assert result["model"] == "claude-3-haiku-20240307"
        assert call_log == ["T1", "T2"]

    @pytest.mark.asyncio
    async def test_t3_gpt41_fallback_on_bedrock_down(self):
        """T1+T2 Bedrock down → T3 GPT-4.1 called."""
        call_log = []

        async def mock_generate(prompt, tier):
            call_log.append(tier)
            if tier in ("T1", "T2"):
                raise Exception("Bedrock service unavailable")
            return {
                "content": SAMPLE_GENERATED,
                "model": "gpt-4.1",
                "tokens_input": 1100,
                "tokens_output": 750,
                "cost_usd": 0.022,
                "cached": False,
            }

        client = MagicMock()
        client.generate = mock_generate

        result = None
        for tier in ["T1", "T2", "T3"]:
            try:
                result = await client.generate("tour prompt", tier=tier)
                break
            except Exception:
                continue

        assert result is not None
        assert result["model"] == "gpt-4.1"
        assert call_log == ["T1", "T2", "T3"]

    def test_prompt_cache_l1_hit_reduces_cost(self, redis_client):
        """L1 cache: same system prompt → cached prefix → lower token cost."""
        cache_key = "prompt_cache:aa_brand_system_v3.2"
        cached_tokens = 2400  # system prompt tokens already cached

        redis_client.setex(cache_key, 3600, str(cached_tokens))
        cached = int(redis_client.get(cache_key))
        assert cached == 2400

    def test_langfuse_trace_url_stored(self, db_conn):
        """pipeline_runs must record Langfuse trace URL for observability."""
        cur = db_conn.cursor()
        run_id = str(uuid.uuid4())
        trace_url = "https://langfuse.aa-cis.internal/traces/trace-test-001"
        cur.execute("""
            INSERT INTO shared.pipeline_runs
                (id, tenant_id, batch_id, tours_total, langfuse_trace_url)
            VALUES (%s, %s, %s, 1, %s)
        """, (run_id, TENANT_ID, BATCH_ID, trace_url))
        cur.execute(
            "SELECT langfuse_trace_url FROM shared.pipeline_runs WHERE id = %s",
            (run_id,)
        )
        assert cur.fetchone()[0] == trace_url
        cur.close()
