"""AA-450 — services/acp_angle_gate/service.py's CTA fix (migration 114): `create_request()`
now looks up a persisted T7 slot's `cta_target` and stores it on the new `angle_gate_request.cta`
column. Mocked asyncpg pool, same convention test_aa449_angle_gate_service.py already uses.
Confirms the realistic-NULL case (STEP0/migration 114's own header comment: T7's real tenant
endpoint never persists slots) is handled gracefully, not as an error."""
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


def _atom_row():
    return {"atom_id": "atom_abc123", "tour_id": TRIP_ID, "text": "Cross the bamboo bridge at dawn"}


def _request_row(**over):
    base = {
        "request_id": uuid.uuid4(), "tenant_id": TENANT_ID, "atom_id": "atom_abc123",
        "trip_id": TRIP_ID, "channel": "facebook", "goal": None, "cta": None, "status": "pending_goal",
        "dfs_paa_snapshot": None,  # AA-501, migration 127
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    base.update(over)
    return base


@pytest.mark.asyncio
class TestFetchSlotCta:
    async def test_matching_slot_returns_cta_target(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"cta_target": "Design This Journey"}
        pool = _make_pool(conn)
        result = await service._fetch_slot_cta(TENANT_ID, "atom_abc123", "facebook", pool)
        assert result == "Design This Journey"

    async def test_no_matching_slot_returns_none(self):
        """The realistic-today case — STEP0/migration 114 confirmed T7's real tenant endpoint
        never persists a slot for acp_v2_slots to match against."""
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = _make_pool(conn)
        result = await service._fetch_slot_cta(TENANT_ID, "atom_abc123", "facebook", pool)
        assert result is None

    async def test_slot_with_empty_cta_target_treated_as_none(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"cta_target": ""}
        pool = _make_pool(conn)
        result = await service._fetch_slot_cta(TENANT_ID, "atom_abc123", "facebook", pool)
        assert result is None


# AA-469 Việc 4 (flow-order fix) — TestCreateRequestCtaWiring removed from here. create_request()
# no longer does any slot-CTA lookup at all (it doesn't know channel anymore) — that whole
# mechanism (this class used to test) moved to services/acp_angle_gate/service.py::set_channel(),
# now covered by tests/unit/test_aa449_angle_gate_service.py::TestSetChannel instead.


@pytest.mark.asyncio
class TestFetchRequestIncludesCta:
    async def test_cta_present_in_returned_dict(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="approved", cta="Book a consultation")
        conn.fetch.return_value = []
        pool = _make_pool(conn)

        result = await service.fetch_request(TENANT_ID, uuid.uuid4(), pool)

        assert result["cta"] == "Book a consultation"
