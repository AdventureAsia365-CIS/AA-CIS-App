"""AA-257 — GET /admin/infra/status (api/routers/admin_pipeline.py::get_infra_status).

Covers:
  1. test_cache_hit_returns_cached_without_aws_calls  — Redis hit skips all boto3 calls
  2. test_cache_miss_calls_aws_and_caches             — real ECS/RDS/NAT/Redis fields mapped
     correctly, digest match computed, result cached with a 60s TTL
  3. test_partial_aws_failure_degrades_gracefully     — every section degrades to {"error": ...}
     independently rather than 500ing the whole endpoint (mirrors the pre-existing
     GET /admin/metrics/spot-workers pattern this endpoint was built to match) — this is the
     expected shape until the AA-257 IAM Terraform PR is granted, not a bug
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.routers import admin_pipeline


def _make_request():
    request = MagicMock()
    request.app.state.redis = AsyncMock()
    return request


@pytest.mark.asyncio
class TestAA257InfraStatus:
    async def test_cache_hit_returns_cached_without_aws_calls(self):
        request = _make_request()
        cached = {"checked_at": "2026-09-04T00:00:00+00:00", "ecs": {"status": "ACTIVE"}}
        request.app.state.redis.get = AsyncMock(return_value=json.dumps(cached))

        with patch.object(admin_pipeline, "verify_admin_secret"), \
                patch.object(admin_pipeline, "_boto3") as mock_boto3:
            result = await admin_pipeline.get_infra_status(request, x_admin_secret="secret")

        assert result["cache_hit"] is True
        assert result["ecs"]["status"] == "ACTIVE"
        mock_boto3.client.assert_not_called()

    async def test_cache_miss_calls_aws_and_caches(self):
        request = _make_request()
        request.app.state.redis.get = AsyncMock(return_value=None)
        request.app.state.redis.set = AsyncMock()

        mock_ecs = MagicMock()
        mock_ecs.describe_services.return_value = {"services": [{
            "status": "ACTIVE", "desiredCount": 1, "runningCount": 1, "pendingCount": 0,
        }]}
        mock_ecs.list_tasks.return_value = {"taskArns": ["arn:aws:ecs:us-west-1:x:task/abc"]}
        mock_ecs.describe_tasks.return_value = {
            "tasks": [{"containers": [{"imageDigest": "sha256:aaa"}]}]
        }

        mock_ecr = MagicMock()
        mock_ecr.describe_images.return_value = {"imageDetails": [{"imageDigest": "sha256:aaa"}]}

        mock_rds = MagicMock()
        mock_rds.describe_db_instances.return_value = {"DBInstances": [{
            "DBInstanceStatus": "available", "Engine": "postgres", "DBInstanceClass": "db.t3.micro",
        }]}

        mock_ec2 = MagicMock()
        mock_ec2.describe_instances.return_value = {
            "Reservations": [{"Instances": [{"State": {"Name": "running"}}]}]
        }

        mock_elasticache = MagicMock()
        mock_elasticache.describe_cache_clusters.return_value = {"CacheClusters": [{
            "CacheClusterStatus": "available", "CacheNodeType": "cache.t3.micro",
        }]}

        clients = {
            "ecs": mock_ecs, "ecr": mock_ecr, "rds": mock_rds,
            "ec2": mock_ec2, "elasticache": mock_elasticache,
        }

        with patch.object(admin_pipeline, "verify_admin_secret"), \
                patch.object(admin_pipeline, "_boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda service, **kw: clients[service]
            result = await admin_pipeline.get_infra_status(request, x_admin_secret="secret")

        assert result["cache_hit"] is False
        assert result["ecs"]["desired_count"] == 1
        assert result["ecs"]["running_digest"] == "sha256:aaa"
        assert result["ecs"]["latest_digest"] == "sha256:aaa"
        assert result["ecs"]["digest_matches_latest"] is True
        assert result["rds"]["status"] == "available"
        assert result["nat"]["state"] == "running"
        assert result["redis"]["status"] == "available"
        assert result["running_reminder"] is True
        request.app.state.redis.set.assert_awaited_once()
        cached_arg = request.app.state.redis.set.await_args
        assert cached_arg.kwargs.get("ex") == admin_pipeline._INFRA_STATUS_CACHE_TTL_S

    async def test_partial_aws_failure_degrades_gracefully_not_500(self):
        request = _make_request()
        request.app.state.redis.get = AsyncMock(return_value=None)
        request.app.state.redis.set = AsyncMock()

        with patch.object(admin_pipeline, "verify_admin_secret"), \
                patch.object(admin_pipeline, "_boto3") as mock_boto3:
            mock_boto3.client.side_effect = Exception("AccessDeniedException: not authorized")
            result = await admin_pipeline.get_infra_status(request, x_admin_secret="secret")

        assert "error" in result["ecs"]
        assert "error" in result["rds"]
        assert "error" in result["nat"]
        assert "error" in result["redis"]
        # Unknown state on AWS failure still trips the reminder — a missed "AWS is
        # running" nudge costs real money, a spurious one costs a glance at the badge.
        assert result["running_reminder"] is True

    async def test_digest_mismatch_flagged_false(self):
        request = _make_request()
        request.app.state.redis.get = AsyncMock(return_value=None)
        request.app.state.redis.set = AsyncMock()

        mock_ecs = MagicMock()
        mock_ecs.describe_services.return_value = {"services": [{
            "status": "ACTIVE", "desiredCount": 1, "runningCount": 1, "pendingCount": 0,
        }]}
        mock_ecs.list_tasks.return_value = {"taskArns": ["arn:aws:ecs:us-west-1:x:task/abc"]}
        mock_ecs.describe_tasks.return_value = {
            "tasks": [{"containers": [{"imageDigest": "sha256:OLD"}]}]
        }
        mock_ecr = MagicMock()
        mock_ecr.describe_images.return_value = {"imageDetails": [{"imageDigest": "sha256:NEW"}]}

        def _client(service, **kw):
            if service == "ecs":
                return mock_ecs
            if service == "ecr":
                return mock_ecr
            raise Exception("AccessDeniedException")

        with patch.object(admin_pipeline, "verify_admin_secret"), \
                patch.object(admin_pipeline, "_boto3") as mock_boto3:
            mock_boto3.client.side_effect = _client
            result = await admin_pipeline.get_infra_status(request, x_admin_secret="secret")

        assert result["ecs"]["digest_matches_latest"] is False
