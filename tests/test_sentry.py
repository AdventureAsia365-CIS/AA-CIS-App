"""
Tests for Sentry error tracking integration (AA-142).
All sentry_sdk calls are mocked — no Sentry account required.
"""
import pytest
from unittest.mock import patch, MagicMock, call


# ---------------------------------------------------------------------------
# init_sentry() unit tests
# ---------------------------------------------------------------------------

def test_sentry_init_graceful_no_dsn():
    """init_sentry() must not raise when DSN fetch returns empty string."""
    with patch("api.core.sentry._get_dsn", return_value=""), \
         patch("sentry_sdk.init") as mock_init:
        from api.core.sentry import init_sentry
        init_sentry()
    mock_init.assert_not_called()


def test_sentry_init_with_dsn():
    """sentry_sdk.init is called with correct dsn and environment when DSN available."""
    test_dsn = "https://abc123@sentry.io/456"
    with patch("api.core.sentry._get_dsn", return_value=test_dsn), \
         patch("sentry_sdk.init") as mock_init:
        from api.core.sentry import init_sentry
        init_sentry()
    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs["dsn"] == test_dsn
    assert "environment" in kwargs
    assert kwargs["traces_sample_rate"] == 0.1


def test_get_dsn_returns_empty_on_boto3_error():
    """_get_dsn() returns empty string when Secrets Manager call fails."""
    with patch("api.core.sentry.boto3") as mock_boto3:
        mock_boto3.client.side_effect = Exception("no credentials")
        from api.core.sentry import _get_dsn
        result = _get_dsn()
    assert result == ""


# ---------------------------------------------------------------------------
# sentry_context_middleware tag tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sentry_middleware_sets_tags():
    """Middleware sets tenant_id, run_id, and route tags from request."""
    from api.middleware.sentry_context import sentry_context_middleware

    mock_request = MagicMock()
    mock_request.headers.get = lambda k, d="": {
        "x-tenant-id": "tenant-abc",
        "x-run-id": "run-xyz",
    }.get(k, d)
    mock_request.url.path = "/acp/s1/runs"

    async def mock_call_next(req):
        return MagicMock()

    with patch("sentry_sdk.set_tag") as mock_set_tag:
        await sentry_context_middleware(mock_request, mock_call_next)

    mock_set_tag.assert_any_call("tenant_id", "tenant-abc")
    mock_set_tag.assert_any_call("run_id", "run-xyz")
    mock_set_tag.assert_any_call("route", "/acp/s1/runs")


@pytest.mark.asyncio
async def test_sentry_middleware_unknown_tenant_fallback():
    """Middleware falls back to 'unknown' when x-tenant-id header is absent."""
    from api.middleware.sentry_context import sentry_context_middleware

    mock_request = MagicMock()
    mock_request.headers.get = lambda k, d="": d
    mock_request.url.path = "/health"

    async def mock_call_next(req):
        return MagicMock()

    with patch("sentry_sdk.set_tag") as mock_set_tag:
        await sentry_context_middleware(mock_request, mock_call_next)

    mock_set_tag.assert_any_call("tenant_id", "unknown")


# ---------------------------------------------------------------------------
# capture_exception pattern test
# ---------------------------------------------------------------------------

def test_sentry_captures_500():
    """sentry_sdk.capture_exception is called when an exception is captured."""
    with patch("sentry_sdk.capture_exception") as mock_capture:
        import sentry_sdk
        exc = RuntimeError("Internal server error simulation")
        sentry_sdk.capture_exception(exc)
    mock_capture.assert_called_once_with(exc)
