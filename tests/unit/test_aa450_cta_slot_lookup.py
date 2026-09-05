"""AA-450 — services/acp_angle_gate/service.py's CTA column (migration 114):
`angle_gate_request.cta`. Mocked asyncpg pool, same convention test_aa449_angle_gate_service.py
already uses.

AA-522 — TestFetchSlotCta removed: `_fetch_slot_cta()`/`_compute_and_persist_slot_cta()` (the T7
slot-CTA prefill this class tested) were deleted along with `set_channel()`, their only real
caller — see services/acp_angle_gate/service.py's own module docstring. `cta` is now resolved
ONLY by services/acp_content_writing/service.py's ask-the-tenant fallback (MissingCTAError)."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.acp_angle_gate import service

TENANT_ID = uuid.uuid4()
TRIP_ID = uuid.uuid4()


def _make_pool(conn):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _request_row(**over):
    base = {
        "request_id": uuid.uuid4(), "tenant_id": TENANT_ID, "atom_id": "atom_abc123",
        "trip_id": TRIP_ID, "channel": "facebook", "goal": None, "cta": None, "status": "pending_goal",
        "dfs_paa_snapshot": None,  # AA-501, migration 127
        "route_segment_ids": None,  # AA-511 Gap A, migration 134
        "subject_id": None,  # AA-512, migration 133
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    base.update(over)
    return base


@pytest.mark.asyncio
class TestFetchRequestIncludesCta:
    async def test_cta_present_in_returned_dict(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="approved", cta="Book a consultation")
        conn.fetch.return_value = []
        pool = _make_pool(conn)

        result = await service.fetch_request(TENANT_ID, uuid.uuid4(), pool)

        assert result["cta"] == "Book a consultation"
