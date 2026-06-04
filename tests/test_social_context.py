"""
Tests for GET /v1/social/{social_id}/context endpoint (AA-127).

Tests:
  1. test_context_endpoint_returns_all_fields — full row → all fields present
  2. test_context_with_null_quality_score     — quality_score=None → response key is None
  3. test_context_invalid_uuid               — bad UUID path → 422
  4. test_context_not_found                  — DB returns None → 404
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


SOCIAL_ID = "aaaaaaaa-0000-0000-0000-000000000001"
ADMIN_SECRET = "test-secret"

QUALITY_SCORE = {
    "hook_strength": 4,
    "specificity": 3,
    "cta_clarity": 5,
    "brand_voice": 4,
    "audience_fit": 4,
    "average": 4.0,
    "passed": True,
}


def _make_context_row(quality_score=QUALITY_SCORE):
    return {
        "social_id": SOCIAL_ID,
        "quality_score": quality_score,
        "rewrite_attempt": 1,
        "validation_status": "passed",
        "validation_issues": None,
        "formula_used": "AIDA",
        "mode": "auto",
        "selected_angle": "Adventure luxury for senior professionals",
        "hitl_gate_3_social_status": "pending",
        "created_at": None,
    }


def _build_app():
    from fastapi import FastAPI
    from api.routers.v1_social import router

    app = FastAPI()
    app.include_router(router)
    return app


def _build_app_with_fetchrow(return_value):
    app = _build_app()

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=return_value)

    pool_mock = AsyncMock()
    pool_mock.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    app.state.pool = pool_mock
    return app


class TestSocialContext:
    @pytest.mark.asyncio
    async def test_context_endpoint_returns_all_fields(self):
        """Full DB row → response includes quality_score, rewrite_attempt, validation_status."""
        from httpx import AsyncClient, ASGITransport

        app = _build_app_with_fetchrow(_make_context_row())

        with patch.dict("os.environ", {"ADMIN_SECRET": ADMIN_SECRET}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/v1/social/{SOCIAL_ID}/context",
                    headers={"X-Admin-Secret": ADMIN_SECRET},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["social_id"] == SOCIAL_ID
        assert data["quality_score"] == QUALITY_SCORE
        assert data["rewrite_attempt"] == 1
        assert data["validation_status"] == "passed"
        assert data["formula_used"] == "AIDA"
        assert data["mode"] == "auto"
        assert data["selected_angle"] == "Adventure luxury for senior professionals"

    @pytest.mark.asyncio
    async def test_context_with_null_quality_score(self):
        """quality_score=None (pipeline not yet run) → response key present and null."""
        from httpx import AsyncClient, ASGITransport

        app = _build_app_with_fetchrow(_make_context_row(quality_score=None))

        with patch.dict("os.environ", {"ADMIN_SECRET": ADMIN_SECRET}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/v1/social/{SOCIAL_ID}/context",
                    headers={"X-Admin-Secret": ADMIN_SECRET},
                )

        assert resp.status_code == 200
        assert resp.json()["quality_score"] is None

    @pytest.mark.asyncio
    async def test_context_invalid_uuid(self):
        """Non-UUID path segment → 422."""
        from httpx import AsyncClient, ASGITransport

        app = _build_app()
        app.state.pool = MagicMock()

        with patch.dict("os.environ", {"ADMIN_SECRET": ADMIN_SECRET}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/v1/social/not-a-uuid/context",
                    headers={"X-Admin-Secret": ADMIN_SECRET},
                )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_context_not_found(self):
        """DB returns no row → 404."""
        from httpx import AsyncClient, ASGITransport

        app = _build_app_with_fetchrow(None)

        with patch.dict("os.environ", {"ADMIN_SECRET": ADMIN_SECRET}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/v1/social/{SOCIAL_ID}/context",
                    headers={"X-Admin-Secret": ADMIN_SECRET},
                )

        assert resp.status_code == 404
