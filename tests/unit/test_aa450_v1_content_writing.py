"""AA-450 — api/routers/v1_content_writing.py. Same convention test_aa449_v1_angle_gate.py uses:
endpoint functions called directly, service.py patched (already unit-tested separately in
test_aa450_content_writing_service.py) — this file checks HTTP status-code mapping."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.routers import v1_content_writing
from services.acp_angle_gate.service import RequestNotFoundError
from services.acp_content_writing import service

TENANT_ID = str(uuid.uuid4())
REQUEST_ID = uuid.uuid4()
PIECE_ID = uuid.uuid4()


def _make_request():
    request = MagicMock()
    request.app.state.pool = MagicMock()
    return request


class TestWrite:
    @pytest.mark.asyncio
    async def test_success(self):
        body = v1_content_writing.WriteBody(cta=None)
        with patch.object(
            v1_content_writing.service, "write_and_check",
            new=AsyncMock(return_value={"status": "approved", "piece_id": str(PIECE_ID)}),
        ):
            result = await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_request_not_found_404(self):
        body = v1_content_writing.WriteBody(cta=None)
        with patch.object(
            v1_content_writing.service, "write_and_check",
            new=AsyncMock(side_effect=RequestNotFoundError("nope")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_not_ready_409(self):
        body = v1_content_writing.WriteBody(cta=None)
        with patch.object(
            v1_content_writing.service, "write_and_check",
            new=AsyncMock(side_effect=service.RequestNotReadyError("angle not chosen yet")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_missing_cta_422(self):
        body = v1_content_writing.WriteBody(cta=None)
        with patch.object(
            v1_content_writing.service, "write_and_check",
            new=AsyncMock(side_effect=service.MissingCTAError("no cta")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_generic_error_500(self):
        body = v1_content_writing.WriteBody(cta=None)
        with patch.object(
            v1_content_writing.service, "write_and_check",
            new=AsyncMock(side_effect=service.ContentWritingError("unexpected")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 500

    @pytest.mark.asyncio
    async def test_cta_override_forwarded(self):
        body = v1_content_writing.WriteBody(cta="Read the guide")
        with patch.object(
            v1_content_writing.service, "write_and_check",
            new=AsyncMock(return_value={"status": "approved"}),
        ) as mock_write:
            await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert mock_write.call_args.kwargs["cta_override"] == "Read the guide"


class TestGetPiece:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch.object(
            v1_content_writing.service, "fetch_piece",
            new=AsyncMock(return_value={"status": "approved"}),
        ):
            result = await v1_content_writing.get_piece(PIECE_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_not_found_404(self):
        with patch.object(
            v1_content_writing.service, "fetch_piece",
            new=AsyncMock(side_effect=service.ContentWritingError("nope")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.get_piece(PIECE_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 404
