"""
Tests for POST /v1/acp/s4/social/{social_id}/retry-angle (AA-126).

Tests:
  1. test_retry_valid_angle       — valid row + angle_2 selected → 200, status="retried"
  2. test_retry_null_angles_json  — angles_json=None → 422
  3. test_retry_invalid_angle_index — angle_index=4 → 422
  4. test_retry_angle_not_in_json — angles_json missing angle_3 → 422
  5. test_retry_invalid_uuid      — bad UUID → 422
  6. test_retry_not_found         — DB returns None → 404
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


SOCIAL_ID = "aaaaaaaa-0000-0000-0000-000000000001"
RUN_ID = "bbbbbbbb-0000-0000-0000-000000000002"
TOUR_ID = "cccccccc-0000-0000-0000-000000000003"
ADMIN_SECRET = "test-secret"

_VALID_BRIEF = {
    "brand": "Adventure Asia",
    "audience": "senior professionals",
    "channel": "tiktok",
    "goal": "awareness",
    "topic": "Vietnam highlands tour",
    "tone": "inspiring",
    "cta": "Design This Journey",
}

_ANGLES_JSON = {
    "angle_1": {
        "name": "Epic Escape", "why_it_works": "contrast",
        "length_signal": "200w", "style_signal": "bold",
    },
    "angle_2": {
        "name": "Quiet Luxury", "why_it_works": "exclusivity",
        "length_signal": "150w", "style_signal": "calm",
    },
    "angle_3": {
        "name": "Cultural Deep Dive", "why_it_works": "authenticity",
        "length_signal": "180w", "style_signal": "warm",
    },
    "selected_index": 1,
}


def _make_db_row(angles_json=_ANGLES_JSON, rewrite_attempt=1):
    return {
        "social_id": SOCIAL_ID,
        "channel": "tiktok",
        "content_brief": _VALID_BRIEF,
        "angles_json": angles_json,
        "rewrite_attempt": rewrite_attempt,
        "tenant_id": "aa_internal",
        "run_id": RUN_ID,
        "tour_id": TOUR_ID,
        "tour_name": "Vietnam Highlands",
        "llm_provider": "bedrock",
        "model_id": None,
    }


def _build_app():
    from fastapi import FastAPI
    from api.routers.v1_s4_social import router

    app = FastAPI()
    app.include_router(router)
    return app


def _build_app_with_pool(fetchrow_result):
    app = _build_app()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    conn.execute = AsyncMock(return_value=None)
    pool_mock = AsyncMock()
    pool_mock.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    app.state.pool = pool_mock
    return app


class TestAngleRetry:
    @pytest.mark.asyncio
    async def test_retry_valid_angle(self):
        """Valid row + angle_2 → 200, status='retried', rewrite_attempt incremented."""
        from httpx import AsyncClient, ASGITransport

        app = _build_app_with_pool(_make_db_row())

        _jsonb_cols = {
            "tiktok": '{"content": "retried content", "hashtags": []}',
            "facebook_post": None,
            "facebook_ad": None,
            "strategy_notes": None,
        }

        _patches = [
            patch.dict("os.environ", {"ADMIN_SECRET": ADMIN_SECRET}),
            patch("api.routers.v1_s4_social.make_llm_client", return_value=MagicMock()),
            patch("services.acp_s4_social.formula.get_formula_name", return_value="hook"),
            patch("services.acp_s4_social.formula.load_formula_file", return_value="text"),
            patch("services.acp_s4_social.writer.write_content", return_value="content"),
            patch("services.acp_s4_social.quality.quality_pass",
                  return_value={"revised_content": "content", "warnings": []}),
            patch("services.acp_s4_social.output._build_jsonb_columns",
                  return_value=_jsonb_cols),
        ]
        with _patches[0], _patches[1], _patches[2], _patches[3], \
                _patches[4], _patches[5], _patches[6]:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/v1/acp/s4/social/{SOCIAL_ID}/retry-angle",
                    json={"angle_index": 2, "reviewer_id": "trang"},
                    headers={"X-Admin-Secret": ADMIN_SECRET},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "retried"
        assert data["social_id"] == SOCIAL_ID
        assert data["angle_index"] == 2
        assert data["rewrite_attempt"] == 2

    @pytest.mark.asyncio
    async def test_retry_null_angles_json(self):
        """angles_json=None (auto mode or pre-AA-126 row) → 422."""
        from httpx import AsyncClient, ASGITransport

        app = _build_app_with_pool(_make_db_row(angles_json=None))

        with patch.dict("os.environ", {"ADMIN_SECRET": ADMIN_SECRET}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/v1/acp/s4/social/{SOCIAL_ID}/retry-angle",
                    json={"angle_index": 1, "reviewer_id": "trang"},
                    headers={"X-Admin-Secret": ADMIN_SECRET},
                )

        assert resp.status_code == 422
        assert "No stored angles" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_retry_invalid_angle_index(self):
        """angle_index=4 (out of range) → 422 before any DB call."""
        from httpx import AsyncClient, ASGITransport

        app = _build_app()
        app.state.pool = MagicMock()

        with patch.dict("os.environ", {"ADMIN_SECRET": ADMIN_SECRET}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/v1/acp/s4/social/{SOCIAL_ID}/retry-angle",
                    json={"angle_index": 4, "reviewer_id": "trang"},
                    headers={"X-Admin-Secret": ADMIN_SECRET},
                )

        assert resp.status_code == 422
        assert "angle_index" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_retry_angle_not_in_json(self):
        """angles_json has angle_1 + angle_2 only; request angle_3 → 422."""
        from httpx import AsyncClient, ASGITransport

        partial_angles = {
            "angle_1": _ANGLES_JSON["angle_1"],
            "angle_2": _ANGLES_JSON["angle_2"],
            "selected_index": 1,
        }
        app = _build_app_with_pool(_make_db_row(angles_json=partial_angles))

        with patch.dict("os.environ", {"ADMIN_SECRET": ADMIN_SECRET}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/v1/acp/s4/social/{SOCIAL_ID}/retry-angle",
                    json={"angle_index": 3, "reviewer_id": "trang"},
                    headers={"X-Admin-Secret": ADMIN_SECRET},
                )

        assert resp.status_code == 422
        assert "angle_3" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_retry_invalid_uuid(self):
        """Malformed social_id UUID → 422."""
        from httpx import AsyncClient, ASGITransport

        app = _build_app()
        app.state.pool = MagicMock()

        with patch.dict("os.environ", {"ADMIN_SECRET": ADMIN_SECRET}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/v1/acp/s4/social/not-a-uuid/retry-angle",
                    json={"angle_index": 1, "reviewer_id": "trang"},
                    headers={"X-Admin-Secret": ADMIN_SECRET},
                )

        assert resp.status_code == 422
        assert "Invalid social_id UUID" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_retry_not_found(self):
        """DB returns None (no matching row) → 404."""
        from httpx import AsyncClient, ASGITransport

        app = _build_app_with_pool(None)

        with patch.dict("os.environ", {"ADMIN_SECRET": ADMIN_SECRET}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/v1/acp/s4/social/{SOCIAL_ID}/retry-angle",
                    json={"angle_index": 1, "reviewer_id": "trang"},
                    headers={"X-Admin-Secret": ADMIN_SECRET},
                )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()
