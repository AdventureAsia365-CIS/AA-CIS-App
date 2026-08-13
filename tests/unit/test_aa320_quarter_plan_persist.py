"""AA-320 — Gate B persist: acp_shared.quarter_plan + quarter_plan_version.

Pure unit tests against a small in-memory fake asyncpg pool/connection that
implements just enough of quarter_plan/quarter_plan_version semantics (unique
(tenant_id, year, quarter), version_no sequencing, current_version_id) to
exercise save_quarter_plan_version/approve_quarter_plan_version/
fetch_approved_quarter_plan's own control flow — same mocked-pool convention
as TestFetchAtomsByTripDbWrapper in test_aa301_quarter.py, extended to carry
state across multiple calls since these tests need a plan/version to persist
between them.
"""
import json
import uuid
from datetime import datetime, timezone

import pytest

from services.acp_planning.models import QuarterPlan
from services.acp_planning.quarter import (
    QuarterPlanVersionNotFoundError,
    QuarterPlanVersionNotPendingError,
    approve_quarter_plan_version,
    fetch_approved_quarter_plan,
    fetch_current_version_no,
    save_quarter_plan_version,
)

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _plan(**over):
    base = dict(tenant_id=TENANT, year=2026, quarter=3, trip_ids=[uuid.uuid4()],
                destination_shares={"Sapa": 1.0})
    base.update(over)
    return QuarterPlan(**base)


class _AsyncCM:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc):
        return False


class FakeDB:
    """In-memory mirror of acp_shared.quarter_plan / quarter_plan_version."""

    def __init__(self):
        self.plans: dict[tuple, uuid.UUID] = {}          # (tenant_id, year, quarter) -> plan_id
        self.current_version: dict[uuid.UUID, uuid.UUID] = {}  # plan_id -> version_id
        self.versions: dict[uuid.UUID, dict] = {}         # version_id -> row dict


class FakeConn:
    def __init__(self, db: FakeDB):
        self.db = db

    def transaction(self):
        return _AsyncCM(None)

    async def execute(self, query, *params):
        q = " ".join(query.split())
        if "INSERT INTO acp_shared.quarter_plan (tenant_id, year, quarter)" in q:
            tenant_id, year, quarter = params
            key = (tenant_id, year, quarter)
            if key not in self.db.plans:
                self.db.plans[key] = uuid.uuid4()
            return "INSERT 0 1"
        if "SET approval_status = 'approved'" in q:
            version_id, approved_by = params
            v = self.db.versions[version_id]
            v["approval_status"] = "approved"
            v["approved_by"] = approved_by
            v["approved_at"] = datetime.now(timezone.utc)
            return "UPDATE 1"
        if "SET current_version_id" in q:
            plan_id, version_id = params
            self.db.current_version[plan_id] = version_id
            return "UPDATE 1"
        raise AssertionError(f"Unhandled execute query: {q!r}")

    async def fetchval(self, query, *params):
        q = " ".join(query.split())
        if "SELECT plan_id FROM acp_shared.quarter_plan" in q:
            tenant_id, year, quarter = params
            return self.db.plans.get((tenant_id, year, quarter))
        if "SELECT COALESCE(MAX(version_no), 0) + 1" in q:
            (plan_id,) = params
            nos = [v["version_no"] for v in self.db.versions.values() if v["plan_id"] == plan_id]
            return (max(nos) + 1) if nos else 1
        if "INSERT INTO acp_shared.quarter_plan_version" in q:
            plan_id, version_no, payload, source = params
            version_id = uuid.uuid4()
            self.db.versions[version_id] = {
                "plan_id": plan_id, "version_no": version_no, "payload": payload,
                "source": source, "approval_status": "pending",
                "approved_by": None, "approved_at": None,
            }
            return version_id
        if "SELECT qpv.version_no" in q:
            return await self._fetchval_version_no(params)
        raise AssertionError(f"Unhandled fetchval query: {q!r}")

    async def fetchrow(self, query, *params):
        q = " ".join(query.split())
        if "SELECT plan_id, approval_status" in q and "FOR UPDATE" in q:
            (version_id,) = params
            v = self.db.versions.get(version_id)
            if v is None:
                return None
            return {"plan_id": v["plan_id"], "approval_status": v["approval_status"]}
        if "SELECT qpv.payload, qpv.approved_by" in q:
            tenant_id, year, quarter = params
            plan_id = self.db.plans.get((tenant_id, year, quarter))
            if plan_id is None:
                return None
            version_id = self.db.current_version.get(plan_id)
            if version_id is None:
                return None
            v = self.db.versions[version_id]
            if v["approval_status"] != "approved":
                return None
            return {"payload": v["payload"], "approved_by": v["approved_by"]}
        raise AssertionError(f"Unhandled fetchrow query: {q!r}")

    async def _fetchval_version_no(self, params):
        tenant_id, year, quarter = params
        plan_id = self.db.plans.get((tenant_id, year, quarter))
        if plan_id is None:
            return None
        version_id = self.db.current_version.get(plan_id)
        if version_id is None:
            return None
        v = self.db.versions[version_id]
        if v["approval_status"] != "approved":
            return None
        return v["version_no"]


class FakePool:
    def __init__(self, db: FakeDB):
        self.db = db

    def acquire(self):
        return _AsyncCM(FakeConn(self.db))


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def pool(db):
    return FakePool(db)


class TestSaveQuarterPlanVersion:
    @pytest.mark.asyncio
    async def test_creates_plan_id_on_first_call(self, pool, db):
        plan = _plan()
        await save_quarter_plan_version(plan, pool)
        assert (plan.tenant_id, plan.year, plan.quarter) in db.plans

    @pytest.mark.asyncio
    async def test_reuses_plan_id_on_second_call(self, pool, db):
        plan = _plan()
        await save_quarter_plan_version(plan, pool)
        plan_id_1 = db.plans[(plan.tenant_id, plan.year, plan.quarter)]
        await save_quarter_plan_version(plan, pool)
        plan_id_2 = db.plans[(plan.tenant_id, plan.year, plan.quarter)]
        assert plan_id_1 == plan_id_2
        assert len(db.plans) == 1

    @pytest.mark.asyncio
    async def test_version_no_increments(self, pool, db):
        plan = _plan()
        v1 = await save_quarter_plan_version(plan, pool)
        v2 = await save_quarter_plan_version(plan, pool)
        v3 = await save_quarter_plan_version(plan, pool)
        assert db.versions[v1]["version_no"] == 1
        assert db.versions[v2]["version_no"] == 2
        assert db.versions[v3]["version_no"] == 3

    @pytest.mark.asyncio
    async def test_new_version_is_pending_and_does_not_touch_current_version(self, pool, db):
        plan = _plan()
        version_id = await save_quarter_plan_version(plan, pool)
        plan_id = db.plans[(plan.tenant_id, plan.year, plan.quarter)]
        assert db.versions[version_id]["approval_status"] == "pending"
        assert db.current_version.get(plan_id) is None


class TestApproveQuarterPlanVersion:
    @pytest.mark.asyncio
    async def test_rejects_nonexistent_version_id(self, pool):
        with pytest.raises(QuarterPlanVersionNotFoundError):
            await approve_quarter_plan_version(uuid.uuid4(), "ms.thu", pool)

    @pytest.mark.asyncio
    async def test_rejects_non_pending_version_id(self, pool, db):
        plan = _plan()
        version_id = await save_quarter_plan_version(plan, pool)
        await approve_quarter_plan_version(version_id, "ms.thu", pool)  # -> approved
        with pytest.raises(QuarterPlanVersionNotPendingError):
            await approve_quarter_plan_version(version_id, "ms.thu", pool)  # already approved

    @pytest.mark.asyncio
    async def test_sets_current_version_id_on_success(self, pool, db):
        plan = _plan()
        version_id = await save_quarter_plan_version(plan, pool)
        plan_id = db.plans[(plan.tenant_id, plan.year, plan.quarter)]
        await approve_quarter_plan_version(version_id, "ms.thu", pool)
        assert db.current_version[plan_id] == version_id
        assert db.versions[version_id]["approval_status"] == "approved"
        assert db.versions[version_id]["approved_by"] == "ms.thu"

    @pytest.mark.asyncio
    async def test_does_not_call_in_memory_approve_quarter_plan(self, pool, db, monkeypatch):
        """approve_quarter_plan_version must be a fully separate DB path —
        it must never call the in-memory approve_quarter_plan()."""
        import services.acp_planning.quarter as quarter_mod
        called = {"hit": False}

        def _spy(*a, **kw):
            called["hit"] = True
            raise AssertionError("approve_quarter_plan_version must not call approve_quarter_plan()")

        monkeypatch.setattr(quarter_mod, "approve_quarter_plan", _spy)
        plan = _plan()
        version_id = await save_quarter_plan_version(plan, pool)
        await approve_quarter_plan_version(version_id, "ms.thu", pool)
        assert called["hit"] is False


class TestFetchApprovedQuarterPlan:
    @pytest.mark.asyncio
    async def test_returns_none_when_nothing_approved(self, pool):
        plan = _plan()
        result = await fetch_approved_quarter_plan(plan.tenant_id, plan.year, plan.quarter, pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_pending_but_not_approved(self, pool):
        plan = _plan()
        await save_quarter_plan_version(plan, pool)
        result = await fetch_approved_quarter_plan(plan.tenant_id, plan.year, plan.quarter, pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_correct_payload_after_approval(self, pool):
        plan = _plan()
        version_id = await save_quarter_plan_version(plan, pool)
        await approve_quarter_plan_version(version_id, "ms.thu", pool)

        fetched = await fetch_approved_quarter_plan(plan.tenant_id, plan.year, plan.quarter, pool)

        assert fetched is not None
        assert fetched.approved is True
        assert fetched.approved_by == "ms.thu"
        assert fetched.tenant_id == plan.tenant_id
        assert fetched.trip_ids == plan.trip_ids
        assert fetched.destination_shares == plan.destination_shares

    @pytest.mark.asyncio
    async def test_payload_round_trips_through_real_json_string(self, pool, db):
        """Matches this app's real asyncpg gap (no jsonb codec registered,
        AA-300/AA-314) — payload comes back as a JSON string, not a dict."""
        plan = _plan()
        version_id = await save_quarter_plan_version(plan, pool)
        await approve_quarter_plan_version(version_id, "ms.thu", pool)
        raw_payload = db.versions[version_id]["payload"]
        assert isinstance(raw_payload, str)
        json.loads(raw_payload)  # must be valid JSON text, not a dict already

        fetched = await fetch_approved_quarter_plan(plan.tenant_id, plan.year, plan.quarter, pool)
        assert fetched.trip_ids == plan.trip_ids


class TestReApprovalDoesNotOverwrite:
    @pytest.mark.asyncio
    async def test_version_1_stays_queryable_after_version_2_approved(self, pool, db):
        plan = _plan()
        v1 = await save_quarter_plan_version(plan, pool)
        await approve_quarter_plan_version(v1, "ms.thu", pool)

        plan_2 = _plan(destination_shares={"Sapa": 0.5, "Ha Giang": 0.5})
        v2 = await save_quarter_plan_version(plan_2, pool, source="standard")
        await approve_quarter_plan_version(v2, "ms.thu", pool)

        plan_id = db.plans[(plan.tenant_id, plan.year, plan.quarter)]
        # both versions remain in the store, version 1 untouched by re-approval
        assert db.versions[v1]["approval_status"] == "approved"
        assert db.versions[v1]["version_no"] == 1
        assert db.versions[v2]["approval_status"] == "approved"
        assert db.versions[v2]["version_no"] == 2
        # current_version_id moved to v2, not v1
        assert db.current_version[plan_id] == v2

        fetched = await fetch_approved_quarter_plan(plan.tenant_id, plan.year, plan.quarter, pool)
        assert fetched.destination_shares == {"Sapa": 0.5, "Ha Giang": 0.5}


class TestFetchCurrentVersionNo:
    """AA-323 round 5, Việc 2 — the number the Preview screen now shows next to
    'Q3 2026'. Same real-world case round 5's live-DB investigation confirmed
    (aa_internal Q3 2026: v1-v6 all left approval_status='approved', only
    current_version_id moves) — this must resolve to the CURRENT version's
    number, not the highest version_no or the first approved one."""

    @pytest.mark.asyncio
    async def test_returns_none_when_nothing_approved(self, pool):
        plan = _plan()
        result = await fetch_current_version_no(plan.tenant_id, plan.year, plan.quarter, pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_version_no_of_the_approved_version(self, pool):
        plan = _plan()
        v1 = await save_quarter_plan_version(plan, pool)
        await approve_quarter_plan_version(v1, "ms.thu", pool)
        result = await fetch_current_version_no(plan.tenant_id, plan.year, plan.quarter, pool)
        assert result == 1

    @pytest.mark.asyncio
    async def test_moves_to_the_newest_version_after_reapproval(self, pool):
        plan = _plan()
        v1 = await save_quarter_plan_version(plan, pool)
        await approve_quarter_plan_version(v1, "ms.thu", pool)

        plan_2 = _plan(destination_shares={"Sapa": 0.5, "Ha Giang": 0.5})
        v2 = await save_quarter_plan_version(plan_2, pool)
        await approve_quarter_plan_version(v2, "ms.thu", pool)

        result = await fetch_current_version_no(plan.tenant_id, plan.year, plan.quarter, pool)
        assert result == 2
