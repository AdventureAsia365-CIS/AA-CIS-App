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
    fetch_quarter_plan_version,
    fetch_quarter_plan_version_history,
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
    """In-memory mirror of acp_shared.quarter_plan / quarter_plan_version /
    year_plan (AA-448 round 6 — Shape 1)."""

    def __init__(self):
        self.plans: dict[tuple, uuid.UUID] = {}          # (tenant_id, year, quarter) -> plan_id
        self.current_version: dict[uuid.UUID, uuid.UUID] = {}  # plan_id -> version_id
        self.versions: dict[uuid.UUID, dict] = {}         # version_id -> row dict
        self.year_plans: dict[tuple, uuid.UUID] = {}      # (tenant_id, year) -> year_plan_id


class FakeConn:
    def __init__(self, db: FakeDB):
        self.db = db

    def transaction(self):
        return _AsyncCM(None)

    async def execute(self, query, *params):
        q = " ".join(query.split())
        if "INSERT INTO acp_shared.year_plan (tenant_id, year)" in q:
            tenant_id, year = params
            key = (tenant_id, year)
            if key not in self.db.year_plans:
                self.db.year_plans[key] = uuid.uuid4()
            return "INSERT 0 1"
        if "INSERT INTO acp_shared.quarter_plan (tenant_id, year, quarter, year_plan_id)" in q:
            tenant_id, year, quarter, year_plan_id = params
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
        if "SELECT year_plan_id FROM acp_shared.year_plan" in q:
            tenant_id, year = params
            return self.db.year_plans.get((tenant_id, year))
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
        if "SELECT qp.tenant_id, qp.year, qp.quarter, qpv.version_no" in q:
            (version_id,) = params
            v = self.db.versions.get(version_id)
            if v is None:
                return None
            tenant_id, year, quarter = next(
                key for key, pid in self.db.plans.items() if pid == v["plan_id"])
            return {
                "tenant_id": tenant_id, "year": year, "quarter": quarter,
                "version_no": v["version_no"], "payload": v["payload"],
                "approval_status": v["approval_status"], "approved_by": v["approved_by"],
            }
        raise AssertionError(f"Unhandled fetchrow query: {q!r}")

    async def fetch(self, query, *params):
        q = " ".join(query.split())
        if "SELECT qpv.version_id, qpv.version_no, qpv.approval_status" in q:
            tenant_id, year, quarter = params
            plan_id = self.db.plans.get((tenant_id, year, quarter))
            if plan_id is None:
                return []
            rows = [
                {
                    "version_id": vid, "version_no": v["version_no"],
                    "approval_status": v["approval_status"], "approved_by": v["approved_by"],
                    "approved_at": v["approved_at"], "created_at": v.get("created_at"),
                    "source": v["source"],
                }
                for vid, v in self.db.versions.items() if v["plan_id"] == plan_id
            ]
            return sorted(rows, key=lambda r: r["version_no"], reverse=True)
        raise AssertionError(f"Unhandled fetch query: {q!r}")

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


class TestFetchQuarterPlanVersion:
    """AA-323 round 6, Phần A — powers the History tab's 'Slot Grid Preview'
    link, which must resolve one SPECIFIC version_id regardless of whether
    it's the tenant's current approved version, an old superseded approved
    one, or still pending/rejected (the router layer, not this function,
    decides what to do with a non-approved result)."""

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_version_id(self, pool):
        result = await fetch_quarter_plan_version(uuid.uuid4(), pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_pending_version_with_approved_false(self, pool):
        plan = _plan()
        v1 = await save_quarter_plan_version(plan, pool)
        result = await fetch_quarter_plan_version(v1, pool)
        assert result is not None
        assert result["approval_status"] == "pending"
        assert result["version_no"] == 1
        assert result["tenant_id"] == plan.tenant_id
        assert result["year"] == plan.year
        assert result["quarter"] == plan.quarter
        assert result["plan"].approved is False

    @pytest.mark.asyncio
    async def test_returns_approved_version_with_approved_true(self, pool):
        plan = _plan()
        v1 = await save_quarter_plan_version(plan, pool)
        await approve_quarter_plan_version(v1, "ms.thu", pool)
        result = await fetch_quarter_plan_version(v1, pool)
        assert result["approval_status"] == "approved"
        assert result["plan"].approved is True
        assert result["plan"].approved_by == "ms.thu"

    @pytest.mark.asyncio
    async def test_old_version_still_fetchable_after_a_newer_one_is_current(self, pool, db):
        """Matches round 5's live-DB finding: approving v2 does not revoke v1's
        approval_status — both must stay individually fetchable by version_id,
        even though quarter_plan.current_version_id now points at v2."""
        plan = _plan()
        v1 = await save_quarter_plan_version(plan, pool)
        await approve_quarter_plan_version(v1, "ms.thu", pool)

        plan_2 = _plan(destination_shares={"Sapa": 0.5, "Ha Giang": 0.5})
        v2 = await save_quarter_plan_version(plan_2, pool)
        await approve_quarter_plan_version(v2, "ms.thu", pool)

        result_v1 = await fetch_quarter_plan_version(v1, pool)
        assert result_v1["approval_status"] == "approved"
        assert result_v1["version_no"] == 1
        assert result_v1["plan"].destination_shares == {"Sapa": 1.0}


class TestFetchQuarterPlanVersionHistory:
    """AA-469 Việc 2 — the tenant-facing history-view list (every version_no ever saved for a
    tenant/year/quarter), not just the current one fetch_current_version_no() resolves."""

    @pytest.mark.asyncio
    async def test_empty_for_never_finalized_quarter(self, pool):
        result = await fetch_quarter_plan_version_history(TENANT, 2026, 3, pool)
        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_versions_all_returned_newest_first(self, pool):
        """Same real scenario STEP0 confirmed live (docs/claude_audit/
        AA-469-viec2-step0-t7-edit-history-investigation.md §8): several approved versions can
        accumulate for one tenant/quarter, all still individually fetchable."""
        plan = _plan()
        v1 = await save_quarter_plan_version(plan, pool)
        await approve_quarter_plan_version(v1, "tenant:x", pool)
        plan_2 = _plan(destination_shares={"Sapa": 0.5, "Ha Giang": 0.5})
        v2 = await save_quarter_plan_version(plan_2, pool)
        await approve_quarter_plan_version(v2, "tenant:x", pool)

        result = await fetch_quarter_plan_version_history(TENANT, 2026, 3, pool)

        assert [r["version_no"] for r in result] == [2, 1]
        assert result[0]["version_id"] == v2
        assert result[0]["approval_status"] == "approved"
        assert result[1]["version_id"] == v1

    @pytest.mark.asyncio
    async def test_pending_unapproved_version_still_listed(self, pool):
        """A version that was saved but never approved (should not happen under Gate B Option A
        auto-approve, but the function itself makes no approval_status assumption) still shows
        up — this is a read, not a filter."""
        plan = _plan()
        v1 = await save_quarter_plan_version(plan, pool)  # never approved

        result = await fetch_quarter_plan_version_history(TENANT, 2026, 3, pool)

        assert len(result) == 1
        assert result[0]["version_id"] == v1
        assert result[0]["approval_status"] == "pending"

    @pytest.mark.asyncio
    async def test_scoped_to_the_requested_tenant_year_quarter(self, pool):
        other_tenant = uuid.uuid4()
        plan_a = _plan()
        await save_quarter_plan_version(plan_a, pool)
        plan_b = _plan(tenant_id=other_tenant)
        await save_quarter_plan_version(plan_b, pool)
        plan_c = _plan(quarter=4)
        await save_quarter_plan_version(plan_c, pool)

        result = await fetch_quarter_plan_version_history(TENANT, 2026, 3, pool)

        assert len(result) == 1
