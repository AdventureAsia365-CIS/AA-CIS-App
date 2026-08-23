"""AA-448 round 6 — services/acp_planning/lock_status.py.

fetch_quarter_lock_status() is DB-backed (mocked pool, same convention as
test_aa301_quarter.py's TestFetchAtomsByTripDbWrapper). is_quarter_fully_locked() is pure.
"""
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.acp_planning.lock_status import (WeekLockStatus, fetch_quarter_lock_status,
                                                is_quarter_fully_locked)

TENANT = uuid.uuid4()


def _mock_pool(rows):
    conn = AsyncMock()
    conn.fetch.return_value = rows
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


class TestFetchQuarterLockStatus:
    @pytest.mark.asyncio
    async def test_returns_12_slots_for_a_quarter(self):
        pool, _ = _mock_pool([])
        statuses = await fetch_quarter_lock_status(TENANT, 2026, 1, pool, today=date(2026, 1, 1))
        assert len(statuses) == 12  # 3 months x 4 weeks
        assert {s.month for s in statuses} == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_future_quarter_nothing_locked(self):
        pool, _ = _mock_pool([])
        statuses = await fetch_quarter_lock_status(TENANT, 2030, 1, pool, today=date(2026, 1, 1))
        assert all(not s.locked for s in statuses)

    @pytest.mark.asyncio
    async def test_fully_past_quarter_all_locked_as_past(self):
        pool, _ = _mock_pool([])
        statuses = await fetch_quarter_lock_status(TENANT, 2020, 1, pool, today=date(2026, 1, 1))
        assert all(s.locked and s.reason == "past" for s in statuses)

    @pytest.mark.asyncio
    async def test_produced_week_locked_even_in_current_month(self):
        """A week with a real acp_v2_runs row is locked as 'produced', regardless of whether
        the month itself has fully passed."""
        pool, conn = _mock_pool([{"month": 1, "week": 1}])
        statuses = await fetch_quarter_lock_status(TENANT, 2026, 1, pool, today=date(2026, 1, 15))
        week1 = next(s for s in statuses if s.month == 1 and s.week == 1)
        assert week1.locked and week1.reason == "produced"
        # week 2 of the CURRENT month (Jan, not yet fully past) with no run row -> unlocked
        week2 = next(s for s in statuses if s.month == 1 and s.week == 2)
        assert not week2.locked

    @pytest.mark.asyncio
    async def test_query_scoped_to_tenant_and_quarter_months(self):
        pool, conn = _mock_pool([])
        await fetch_quarter_lock_status(TENANT, 2026, 2, pool, today=date(2026, 1, 1))  # Q2 = months 4,5,6
        query, tenant_param, year_param, months_param = conn.fetch.call_args[0]
        assert "acp_v2_runs" in query
        assert tenant_param == str(TENANT)
        assert year_param == 2026
        assert months_param == [4, 5, 6]


class TestIsQuarterFullyLocked:
    def test_empty_list_not_locked(self):
        assert is_quarter_fully_locked([]) is False

    def test_all_locked_is_fully_locked(self):
        statuses = [WeekLockStatus(2026, 1, w, True, "past") for w in (1, 2, 3, 4)]
        assert is_quarter_fully_locked(statuses) is True

    def test_partial_lock_not_fully_locked(self):
        statuses = [
            WeekLockStatus(2026, 1, 1, True, "produced"),
            WeekLockStatus(2026, 1, 2, False, None),
        ]
        assert is_quarter_fully_locked(statuses) is False
