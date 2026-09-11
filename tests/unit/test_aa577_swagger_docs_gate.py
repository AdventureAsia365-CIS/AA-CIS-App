"""AA-577 — Swagger UI/ReDoc/openapi.json gated behind X-Admin-Secret, ONLY on the real deployed
system (never local/CI). api/main.py::_is_publicly_deployed()/require_admin_secret_for_docs()."""
import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api import main
from api.routers import admin


class TestIsPubliclyDeployed:
    def test_false_when_aws_execution_env_unset(self):
        """The real state of a developer's laptop or a GitHub Actions CI runner."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AWS_EXECUTION_ENV", None)
            assert main._is_publicly_deployed() is False

    def test_true_when_aws_execution_env_set(self):
        """The real state of the deployed ECS/Fargate task — confirmed live
        (AWS_EXECUTION_ENV=AWS_ECS_FARGATE on the real running task, AA-577 STEP0)."""
        with patch.dict(os.environ, {"AWS_EXECUTION_ENV": "AWS_ECS_FARGATE"}):
            assert main._is_publicly_deployed() is True

    def test_not_derived_from_environment_var(self):
        """The real bug this function exists to avoid: Terraform sets ENVIRONMENT="dev" on the
        one real deployed system too (no separate staging/prod cluster exists) — gating on
        ENVIRONMENT alone would never protect the live deployment."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
            os.environ.pop("AWS_EXECUTION_ENV", None)
            assert main._is_publicly_deployed() is False


class TestRequireAdminSecretForDocs:
    def test_local_dev_no_secret_needed(self):
        """Not publicly deployed — the dependency must be a no-op regardless of the header,
        per Nghiệp's explicit decision that local/CI stays fully public."""
        with patch.object(main, "_is_publicly_deployed", return_value=False):
            main.require_admin_secret_for_docs(x_admin_secret=None)  # no raise
            main.require_admin_secret_for_docs(x_admin_secret="wrong")  # no raise either

    def test_deployed_missing_secret_403s(self):
        with patch.object(main, "_is_publicly_deployed", return_value=True), \
             patch.object(admin, "ADMIN_SECRET", "the-real-secret"):
            with pytest.raises(HTTPException) as exc:
                main.require_admin_secret_for_docs(x_admin_secret=None)
        assert exc.value.status_code == 403

    def test_deployed_wrong_secret_403s(self):
        with patch.object(main, "_is_publicly_deployed", return_value=True), \
             patch.object(admin, "ADMIN_SECRET", "the-real-secret"):
            with pytest.raises(HTTPException) as exc:
                main.require_admin_secret_for_docs(x_admin_secret="wrong-secret")
        assert exc.value.status_code == 403

    def test_deployed_correct_secret_passes(self):
        with patch.object(main, "_is_publicly_deployed", return_value=True), \
             patch.object(admin, "ADMIN_SECRET", "the-real-secret"):
            main.require_admin_secret_for_docs(x_admin_secret="the-real-secret")  # no raise


class TestDocsRoutesDisabledByDefaultAndReRegisteredGated:
    def test_default_docs_urls_disabled(self):
        """docs_url/redoc_url/openapi_url all None on the FastAPI() constructor — otherwise
        FastAPI auto-registers an UNPROTECTED copy of these same 4 routes alongside the gated
        ones below."""
        assert main.app.docs_url is None
        assert main.app.redoc_url is None
        assert main.app.openapi_url is None

    def test_all_4_routes_manually_registered(self):
        paths = {r.path for r in main.app.routes if hasattr(r, "path")}
        assert "/docs" in paths
        assert "/redoc" in paths
        assert "/openapi.json" in paths
        assert "/docs/oauth2-redirect" in paths

    def test_all_4_routes_depend_on_the_gate(self):
        gated_paths = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
        found = set()
        for r in main.app.routes:
            if getattr(r, "path", None) in gated_paths:
                dep_funcs = {d.call for d in r.dependant.dependencies}
                assert main.require_admin_secret_for_docs in dep_funcs, r.path
                found.add(r.path)
        assert found == gated_paths
