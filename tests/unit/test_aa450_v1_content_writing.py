"""AA-450 (endpoint shape) + AA-466 (202 Accepted + poll) — api/routers/v1_content_writing.py.
Same convention test_aa449_v1_angle_gate.py uses: endpoint functions called directly,
service.py patched (already unit-tested separately in test_aa450_content_writing_service.py) —
this file checks HTTP status-code mapping + that the background task is actually launched with
a strong ref (AA-466 — the GC-safety pattern api/routers/v1_tours.py's trigger_rewrite() uses)."""
import asyncio
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


def _started(status="processing"):
    return {
        "piece": {"piece_id": str(PIECE_ID), "status": status, "content_text": "",
                   "angle_gate_request_id": str(REQUEST_ID)},
        "context": {"atom_text": "x"},
    }


class TestWrite:
    @pytest.mark.asyncio
    async def test_success_returns_202_processing_placeholder(self):
        body = v1_content_writing.WriteBody(cta=None)
        with patch.object(v1_content_writing.service, "start_write",
                           new=AsyncMock(return_value=_started())), \
             patch.object(v1_content_writing.service, "run_write_background",
                           new=AsyncMock(return_value=None)) as mock_bg:
            result = await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
            await asyncio.sleep(0)  # let the scheduled background task actually run

        assert result["status"] == "processing"
        assert result["piece_id"] == str(PIECE_ID)
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_background_task_launched_with_strong_ref(self):
        """AA-466 — the task must be added to the module-level _background_tasks set (and
        removed again on completion via add_done_callback), the same GC-safety guard
        api/routers/v1_tours.py::trigger_rewrite() already uses. A bare create_task() with no
        ref can be garbage-collected mid-flight."""
        body = v1_content_writing.WriteBody(cta=None)
        assert len(v1_content_writing._background_tasks) == 0
        with patch.object(v1_content_writing.service, "start_write",
                           new=AsyncMock(return_value=_started())), \
             patch.object(v1_content_writing.service, "run_write_background",
                           new=AsyncMock(return_value=None)):
            await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
            assert len(v1_content_writing._background_tasks) == 1  # added before the task ran
            # task completion -> add_done_callback fires via call_soon, needs 2 ticks to observe
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        assert len(v1_content_writing._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_request_not_found_404(self):
        body = v1_content_writing.WriteBody(cta=None)
        with patch.object(
            v1_content_writing.service, "start_write",
            new=AsyncMock(side_effect=RequestNotFoundError("nope")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_not_ready_409(self):
        body = v1_content_writing.WriteBody(cta=None)
        with patch.object(
            v1_content_writing.service, "start_write",
            new=AsyncMock(side_effect=service.RequestNotReadyError("angle not chosen yet")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_missing_cta_422(self):
        body = v1_content_writing.WriteBody(cta=None)
        with patch.object(
            v1_content_writing.service, "start_write",
            new=AsyncMock(side_effect=service.MissingCTAError("no cta")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_generic_error_500(self):
        body = v1_content_writing.WriteBody(cta=None)
        with patch.object(
            v1_content_writing.service, "start_write",
            new=AsyncMock(side_effect=service.ContentWritingError("unexpected")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 500

    @pytest.mark.asyncio
    async def test_cta_override_forwarded(self):
        body = v1_content_writing.WriteBody(cta="Read the guide")
        with patch.object(v1_content_writing.service, "start_write",
                           new=AsyncMock(return_value=_started())) as mock_start, \
             patch.object(v1_content_writing.service, "run_write_background",
                           new=AsyncMock(return_value=None)):
            await v1_content_writing.write(REQUEST_ID, body, _make_request(), tenant={"sub": TENANT_ID})
            await asyncio.sleep(0)
        assert mock_start.call_args.kwargs["cta_override"] == "Read the guide"


class TestGetPiece:
    """UNCHANGED by AA-466 — fetch_piece() and this endpoint didn't need to change; kept here to
    confirm poll callers still get the right shape/status mapping at any of the 4 status values."""

    @pytest.mark.asyncio
    async def test_success(self):
        with patch.object(
            v1_content_writing.service, "fetch_piece",
            new=AsyncMock(return_value={"status": "approved"}),
        ):
            result = await v1_content_writing.get_piece(PIECE_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_processing_status_returned_while_polling(self):
        with patch.object(
            v1_content_writing.service, "fetch_piece",
            new=AsyncMock(return_value={"status": "processing", "content_text": ""}),
        ):
            result = await v1_content_writing.get_piece(PIECE_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert result["status"] == "processing"

    @pytest.mark.asyncio
    async def test_failed_status_returned_after_background_error(self):
        with patch.object(
            v1_content_writing.service, "fetch_piece",
            new=AsyncMock(return_value={"status": "failed", "held_reason": "RuntimeError: boom"}),
        ):
            result = await v1_content_writing.get_piece(PIECE_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_not_found_404(self):
        with patch.object(
            v1_content_writing.service, "fetch_piece",
            new=AsyncMock(side_effect=service.ContentWritingError("nope")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.get_piece(PIECE_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 404


class TestGetLatestPiece:
    """AA-522 — GET .../requests/{request_id}/latest-piece, resume support for the T8/T9 wizard's
    write step. service.fetch_latest_piece_for_request() itself is unit-tested in
    test_aa450_content_writing_service.py::TestFetchLatestPieceForRequest — this only checks the
    router wraps it as {"piece": ...}."""

    @pytest.mark.asyncio
    async def test_returns_piece_when_present(self):
        with patch.object(
            v1_content_writing.service, "fetch_latest_piece_for_request",
            new=AsyncMock(return_value={"status": "approved", "piece_id": str(PIECE_ID)}),
        ):
            result = await v1_content_writing.get_latest_piece(REQUEST_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert result == {"piece": {"status": "approved", "piece_id": str(PIECE_ID)}}

    @pytest.mark.asyncio
    async def test_returns_none_when_nothing_written_yet(self):
        with patch.object(
            v1_content_writing.service, "fetch_latest_piece_for_request",
            new=AsyncMock(return_value=None),
        ):
            result = await v1_content_writing.get_latest_piece(REQUEST_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert result == {"piece": None}


class TestListReviews:
    """AA-501 — GET /v1/content-writing/reviews, the /portal/t10-review list."""

    @pytest.mark.asyncio
    async def test_returns_data_and_total(self):
        items = [{"request_id": str(REQUEST_ID), "ready_state": "ready"}]
        with patch.object(v1_content_writing.service, "fetch_review_list", new=AsyncMock(return_value=items)):
            result = await v1_content_writing.list_reviews(_make_request(), tenant={"sub": TENANT_ID})
        assert result == {"data": items, "total": 1}

    @pytest.mark.asyncio
    async def test_empty_list(self):
        with patch.object(v1_content_writing.service, "fetch_review_list", new=AsyncMock(return_value=[])):
            result = await v1_content_writing.list_reviews(_make_request(), tenant={"sub": TENANT_ID})
        assert result == {"data": [], "total": 0}


class TestGetReview:
    """AA-501 — GET .../requests/{request_id}/review, the new tenant-facing pre-T11 screen
    endpoint. service.fetch_review() itself is unit-tested in
    test_aa450_content_writing_service.py::TestFetchReview — this only checks the router's
    error-mapping (both possible not-found exceptions -> 404)."""

    @pytest.mark.asyncio
    async def test_success(self):
        review = {"request_id": str(REQUEST_ID), "ready_state": "ready", "content_text": "final"}
        with patch.object(v1_content_writing.service, "fetch_review", new=AsyncMock(return_value=review)):
            result = await v1_content_writing.get_review(REQUEST_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert result["ready_state"] == "ready"

    @pytest.mark.asyncio
    async def test_request_not_found_404(self):
        with patch.object(
            v1_content_writing.service, "fetch_review",
            new=AsyncMock(side_effect=RequestNotFoundError("nope")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.get_review(REQUEST_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_piece_written_yet_404(self):
        with patch.object(
            v1_content_writing.service, "fetch_review",
            new=AsyncMock(side_effect=service.ContentWritingError("nothing written yet")),
        ):
            with pytest.raises(HTTPException) as exc:
                await v1_content_writing.get_review(REQUEST_ID, _make_request(), tenant={"sub": TENANT_ID})
        assert exc.value.status_code == 404
