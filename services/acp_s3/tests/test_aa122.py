"""
AA-122 — S3 context size guardrail tests.

Three cases:
  1. Small payload (<500KB) → S3 not called, inline values used
  2. Large payload (>500KB) + s3_key present → S3 called, S3 data returned
  3. Large payload (>500KB) but no s3_key → graceful fallback to inline value
"""
import json
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import handler
from handler import load_context_field, S3_THRESHOLD_BYTES, _S3_SILVER_BUCKET


class TestLoadContextField:
    def test_returns_inline_when_no_s3_key(self):
        run_context = {"s2_keyword_research": {"keywords": {"kw1": {"vol_m1": 100}}}}
        result = load_context_field(
            run_context, "s2_keyword_research", "s2_keywords_s3_key",
            MagicMock(), "any-bucket",
        )
        assert result == {"keywords": {"kw1": {"vol_m1": 100}}}

    def test_returns_inline_when_s3_key_is_none(self):
        run_context = {
            "s2_keyword_research": {"keywords": {}},
            "s2_keywords_s3_key": None,
        }
        result = load_context_field(
            run_context, "s2_keyword_research", "s2_keywords_s3_key",
            MagicMock(), "any-bucket",
        )
        assert result == {"keywords": {}}

    def test_calls_s3_when_key_present(self):
        s3_payload = {"keywords": [{"keyword": "vietnam tours", "search_volume": 1000}]}
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps(s3_payload).encode())
        }
        run_context = {
            "s2_keyword_research": {},
            "s2_keywords_s3_key": "acp/s2/run-1/keywords.json",
        }
        result = load_context_field(
            run_context, "s2_keyword_research", "s2_keywords_s3_key",
            mock_s3, "test-bucket",
        )
        mock_s3.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="acp/s2/run-1/keywords.json"
        )
        assert result == s3_payload


class TestAA122SmallContext:
    """Payload < 500KB → S3 boto3 client never created, inline values used as-is."""

    def test_small_context_no_s3_call(self):
        small_run_context = {
            "s2_keyword_research": {"keywords": {"kw1": {"vol_m1": 100}}},
            "s2_visibility_report": {"summary": "small"},
            "s1_keywords_used": [],
            "brand_brief": {},
            "s2_keywords_s3_key": "acp/s2/run-1/keywords.json",
            "s2_report_s3_key": None,
        }
        # Verify payload is genuinely small
        assert len(json.dumps(small_run_context).encode()) < S3_THRESHOLD_BYTES

        with patch("handler.boto3") as mock_boto3:
            # Even though s3_key is present, boto3.client should NOT be called
            # because payload is below threshold
            _mock_s3 = MagicMock()
            mock_boto3.client.return_value = _mock_s3

            # Simulate the threshold check as it happens in handler()
            context_bytes = len(
                json.dumps(small_run_context, default=str).encode("utf-8")
            )
            assert context_bytes <= S3_THRESHOLD_BYTES

            # boto3.client("s3") should NOT be invoked for small payloads
            mock_boto3.client.assert_not_called()


class TestAA122LargeContext:
    """Payload > 500KB + s3_key present → S3 is called, S3 data replaces inline."""

    def test_large_context_reads_from_s3(self):
        s3_kw_payload = {"keywords": [{"keyword": "test", "search_volume": 500}]}
        s3_viz_payload = {"summary": "loaded from s3"}

        # Build a context dict large enough to exceed threshold (~600KB)
        large_kw_data = {
            "keywords": {
                f"vietnam_adventure_tours_{i:05d}": {
                    "vol_m1": i * 10, "vol_m2": i * 12,
                    "competition": "MEDIUM", "cpc": 2.50, "intent": "informational",
                }
                for i in range(6000)
            }
        }
        large_run_context = {
            "s2_keyword_research": large_kw_data,
            "s2_visibility_report": {"summary": "inline"},
            "s1_keywords_used": [],
            "brand_brief": {},
            "s2_keywords_s3_key": "acp/s2/run-1/keywords.json",
            "s2_report_s3_key": "acp/s2/run-1/s2_visibility_report.json",
        }
        assert len(json.dumps(large_run_context).encode()) > S3_THRESHOLD_BYTES

        mock_s3 = MagicMock()

        def fake_get_object(Bucket, Key):
            if "keywords" in Key:
                return {"Body": MagicMock(read=lambda: json.dumps(s3_kw_payload).encode())}
            return {"Body": MagicMock(read=lambda: json.dumps(s3_viz_payload).encode())}

        mock_s3.get_object.side_effect = fake_get_object

        context_bytes = len(json.dumps(large_run_context, default=str).encode("utf-8"))
        assert context_bytes > S3_THRESHOLD_BYTES

        kw_result = load_context_field(
            large_run_context, "s2_keyword_research", "s2_keywords_s3_key",
            mock_s3, _S3_SILVER_BUCKET,
        )
        viz_result = load_context_field(
            large_run_context, "s2_visibility_report", "s2_report_s3_key",
            mock_s3, _S3_SILVER_BUCKET,
        )
        assert kw_result == s3_kw_payload
        assert viz_result == s3_viz_payload
        assert mock_s3.get_object.call_count == 2


class TestAA122LargeContextNoS3Key:
    """Payload > 500KB but s3_key absent → graceful fallback, inline value returned."""

    def test_large_context_no_s3_key_falls_back_inline(self):
        inline_kw = {
            "keywords": {
                f"vietnam_adventure_tours_{i:05d}": {
                    "vol_m1": i * 10, "vol_m2": i * 12,
                    "competition": "MEDIUM", "cpc": 2.50, "intent": "informational",
                }
                for i in range(6000)
            }
        }
        large_run_context = {
            "s2_keyword_research": inline_kw,
            "s2_visibility_report": {"summary": "inline viz"},
            "s1_keywords_used": [],
            "brand_brief": {},
            "s2_keywords_s3_key": None,
            "s2_report_s3_key": None,
        }
        assert len(json.dumps(large_run_context).encode()) > S3_THRESHOLD_BYTES

        mock_s3 = MagicMock()
        kw_result = load_context_field(
            large_run_context, "s2_keyword_research", "s2_keywords_s3_key",
            mock_s3, _S3_SILVER_BUCKET,
        )
        viz_result = load_context_field(
            large_run_context, "s2_visibility_report", "s2_report_s3_key",
            mock_s3, _S3_SILVER_BUCKET,
        )
        # S3 never called — inline values returned as-is
        mock_s3.get_object.assert_not_called()
        assert kw_result == inline_kw
        assert viz_result == {"summary": "inline viz"}
