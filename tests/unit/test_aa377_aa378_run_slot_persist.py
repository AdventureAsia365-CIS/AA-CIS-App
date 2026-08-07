"""AA-377 + AA-378 — deterministic slot_id + acp_v2_runs/acp_v2_slots persistence.

Two groups of tests:
- TestDeterministicSlotId / TestMakeSlotDeterminism: pure Python, no DB — proves the AA-377 bug
  (slot_id changing on every allocate_month() call) is actually fixed.
- Everything else: mocked-pool tests against an in-memory mirror of acp_v2_runs/acp_v2_slots,
  same convention as test_aa320_quarter_plan_persist.py's FakeDB/FakeConn/FakePool.
"""
import json
import uuid
from datetime import date

import pytest

from services.acp_planning.allocator import (
    _deterministic_slot_id,
    allocate_and_persist_week,
    compute_slot_grid,
    create_weekly_produce_run,
    fetch_due_slots,
    mark_slot_status,
    persist_slot_grid,
)
from services.acp_planning.models import AtomRecord, QuarterPlan, RunwayCell, RunwayMap, Slot, Trip

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
_ACTIVITY_TYPES = ["trek", "bike", "food", "culture", "stay", "transit", "other"]


def _trip(**over):
    base = dict(id=uuid.uuid4(), name="Ha Giang Loop by Motorbike", destination="Ha Giang",
                period="Mar-May", lifecycle_stage="active", trip_url=None, url_alive=None)
    base.update(over)
    return Trip(**base)


def _atoms(trip_id, n, distinctiveness="HIGH"):
    return [AtomRecord(atom_id=f"atom_{i}_{uuid.uuid4().hex[:6]}", trip_id=trip_id,
                       text=f"atom text number {i} about limestone cliffs and rice terraces",
                       activity_type=_ACTIVITY_TYPES[i % len(_ACTIVITY_TYPES)],
                       distinctiveness=distinctiveness) for i in range(n)]


def _full_runway(destination="Ha Giang", market="US", stage="BOFU"):
    return RunwayMap(tenant_id=TENANT, year=2026,
                     cells=[RunwayCell(destination=destination, market=market, month=m, stage=stage)
                            for m in range(1, 13)])


def _approved_plan(tenant_id, trip_ids, shares=None):
    return QuarterPlan(tenant_id=tenant_id, year=2026, quarter=1, trip_ids=trip_ids,
                       destination_shares=shares or {}, approved=True, approved_by="ms.thu")


def _slot(**over):
    base = dict(slot_id="slot_abc", week=1, channel="blog", kind="evergreen",
                trip_id=uuid.uuid4(), atom_ids=["a1"])
    base.update(over)
    return Slot(**base)


class TestDeterministicSlotId:
    def test_same_inputs_same_id(self):
        tid = uuid.uuid4()
        trip = uuid.uuid4()
        a = _deterministic_slot_id(tid, 2, trip, "blog")
        b = _deterministic_slot_id(tid, 2, trip, "blog")
        assert a == b

    def test_different_week_different_id(self):
        tid, trip = uuid.uuid4(), uuid.uuid4()
        assert _deterministic_slot_id(tid, 1, trip, "blog") != _deterministic_slot_id(tid, 2, trip, "blog")

    def test_different_channel_different_id(self):
        tid, trip = uuid.uuid4(), uuid.uuid4()
        assert _deterministic_slot_id(tid, 1, trip, "blog") != _deterministic_slot_id(tid, 1, trip, "facebook")

    def test_different_trip_different_id(self):
        tid = uuid.uuid4()
        assert (_deterministic_slot_id(tid, 1, uuid.uuid4(), "blog")
                != _deterministic_slot_id(tid, 1, uuid.uuid4(), "blog"))

    def test_different_tenant_different_id(self):
        trip = uuid.uuid4()
        assert (_deterministic_slot_id(uuid.uuid4(), 1, trip, "blog")
                != _deterministic_slot_id(uuid.uuid4(), 1, trip, "blog"))


class TestMakeSlotDeterminism:
    """AA-377's actual bug: calling compute_slot_grid() twice for the same inputs used to
    produce different slot_ids (uuid.uuid4()) every time."""

    def test_repeated_allocation_same_evergreen_slot_ids(self):
        t = _trip()
        plan = _approved_plan(TENANT, [t.id], {"Ha Giang": 1.0})
        runway = _full_runway()
        atoms = _atoms(t.id, 12)

        grid_1 = compute_slot_grid(TENANT, 2026, 2, ["blog"], 4, plan, runway,
                                   {t.id: t}, {t.id: atoms}, "US")
        grid_2 = compute_slot_grid(TENANT, 2026, 2, ["blog"], 4, plan, runway,
                                   {t.id: t}, {t.id: atoms}, "US")

        ids_1 = [s.slot_id for s in grid_1.slots if s.kind != "reactive_hold"]
        ids_2 = [s.slot_id for s in grid_2.slots if s.kind != "reactive_hold"]
        assert ids_1 == ids_2
        assert ids_1, "expected at least one non-reactive_hold slot in this fixture"

    def test_reactive_hold_slots_still_random(self):
        """Documented tradeoff (AA-377.md) — reactive_hold has no trip_id to key a
        deterministic id on, kept random on purpose."""
        t = _trip()
        plan = _approved_plan(TENANT, [t.id], {"Ha Giang": 1.0})
        runway = _full_runway()
        atoms = _atoms(t.id, 12)

        grid_1 = compute_slot_grid(TENANT, 2026, 2, ["blog"], 4, plan, runway,
                                   {t.id: t}, {t.id: atoms}, "US")
        grid_2 = compute_slot_grid(TENANT, 2026, 2, ["blog"], 4, plan, runway,
                                   {t.id: t}, {t.id: atoms}, "US")

        holds_1 = [s.slot_id for s in grid_1.slots if s.kind == "reactive_hold"]
        holds_2 = [s.slot_id for s in grid_2.slots if s.kind == "reactive_hold"]
        assert holds_1 and holds_2
        assert holds_1 != holds_2


class _AsyncCM:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc):
        return False


class FakeDB:
    """In-memory mirror of acp_shared.acp_v2_runs / acp_v2_slots."""

    def __init__(self):
        self.runs: dict[tuple, uuid.UUID] = {}   # (tenant_id, year, week) -> run_id
        self.slots: dict[str, dict] = {}          # slot_id -> row dict


class FakeConn:
    def __init__(self, db: FakeDB):
        self.db = db

    def transaction(self):
        return _AsyncCM(None)

    async def execute(self, query, *params):
        q = " ".join(query.split())
        if "INSERT INTO acp_shared.acp_v2_runs" in q:
            tenant_id, year, week = params
            key = (tenant_id, year, week)
            if key not in self.db.runs:
                self.db.runs[key] = uuid.uuid4()
            return "INSERT 0 1"
        if "INSERT INTO acp_shared.acp_v2_slots" in q:
            slot_id, run_id, tenant_id, week, channel, kind, tour_id, payload = params
            if slot_id not in self.db.slots:
                self.db.slots[slot_id] = {
                    "slot_id": slot_id, "run_id": run_id, "tenant_id": tenant_id, "week": week,
                    "channel": channel, "kind": kind, "tour_id": tour_id, "payload": payload,
                    "status": "due", "produced_at": None, "skipped_reason": None,
                }
            return "INSERT 0 1"
        if "UPDATE acp_shared.acp_v2_slots" in q:
            slot_id, status, reason = params
            row = self.db.slots.get(slot_id)
            if row is not None:
                row["status"] = status
                if status == "produced":
                    row["produced_at"] = "now"
                if status == "skipped":
                    row["skipped_reason"] = reason
            return "UPDATE 1" if row is not None else "UPDATE 0"
        raise AssertionError(f"Unhandled execute query: {q!r}")

    async def fetchval(self, query, *params):
        q = " ".join(query.split())
        if "SELECT run_id FROM acp_shared.acp_v2_runs" in q:
            tenant_id, year, week = params
            return self.db.runs.get((tenant_id, year, week))
        raise AssertionError(f"Unhandled fetchval query: {q!r}")

    async def fetch(self, query, *params):
        q = " ".join(query.split())
        if "SELECT payload FROM acp_shared.acp_v2_slots" in q:
            (run_id,) = params
            rows = [r for r in self.db.slots.values() if r["run_id"] == run_id and r["status"] == "due"]
            return [{"payload": r["payload"]} for r in rows]
        raise AssertionError(f"Unhandled fetch query: {q!r}")


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


class TestCreateWeeklyProduceRun:
    @pytest.mark.asyncio
    async def test_creates_run_on_first_call(self, pool, db):
        run_id = await create_weekly_produce_run(pool, str(TENANT), 2026, 2)
        assert (str(TENANT), 2026, 2) in db.runs
        assert run_id == str(db.runs[(str(TENANT), 2026, 2)])

    @pytest.mark.asyncio
    async def test_second_call_same_week_returns_same_run_id(self, pool, db):
        run_id_1 = await create_weekly_produce_run(pool, str(TENANT), 2026, 2)
        run_id_2 = await create_weekly_produce_run(pool, str(TENANT), 2026, 2)
        assert run_id_1 == run_id_2
        assert len(db.runs) == 1

    @pytest.mark.asyncio
    async def test_different_week_gets_different_run_id(self, pool, db):
        run_id_1 = await create_weekly_produce_run(pool, str(TENANT), 2026, 1)
        run_id_2 = await create_weekly_produce_run(pool, str(TENANT), 2026, 2)
        assert run_id_1 != run_id_2


class TestPersistSlotGridAndFetchDueSlots:
    @pytest.mark.asyncio
    async def test_persists_only_matching_week_non_hold_slots(self, pool, db):
        run_id = await create_weekly_produce_run(pool, str(TENANT), 2026, 1)
        grid_slots = [
            _slot(slot_id="s1", week=1, kind="evergreen"),
            _slot(slot_id="s2", week=2, kind="evergreen"),  # different week — excluded
            _slot(slot_id="s3", week=1, kind="reactive_hold", trip_id=None, atom_ids=[]),  # hold — excluded
        ]

        class _Grid:
            slots = grid_slots

        persisted = await persist_slot_grid(pool, run_id, str(TENANT), 1, _Grid())
        assert [s.slot_id for s in persisted] == ["s1"]
        assert set(db.slots.keys()) == {"s1"}

    @pytest.mark.asyncio
    async def test_reallocation_is_idempotent_no_op(self, pool, db):
        """Same slot_id persisted twice must not create a second row or clobber status."""
        run_id = await create_weekly_produce_run(pool, str(TENANT), 2026, 1)

        class _Grid:
            slots = [_slot(slot_id="s1", week=1, kind="evergreen")]

        await persist_slot_grid(pool, run_id, str(TENANT), 1, _Grid())
        await mark_slot_status(pool, "s1", "produced")
        await persist_slot_grid(pool, run_id, str(TENANT), 1, _Grid())  # re-allocate, same slot

        assert len(db.slots) == 1
        assert db.slots["s1"]["status"] == "produced"  # ON CONFLICT DO NOTHING must not reset it

    @pytest.mark.asyncio
    async def test_fetch_due_slots_round_trips_via_json_payload(self, pool, db):
        """Matches this app's real asyncpg gap (no jsonb codec registered, AA-300/AA-314) —
        payload comes back as a JSON string, not a dict."""
        run_id = await create_weekly_produce_run(pool, str(TENANT), 2026, 1)
        trip_id = uuid.uuid4()

        class _Grid:
            slots = [_slot(slot_id="s1", week=1, kind="evergreen", trip_id=trip_id, keyword_seed="hoi an tours")]

        await persist_slot_grid(pool, run_id, str(TENANT), 1, _Grid())
        raw_payload = db.slots["s1"]["payload"]
        assert isinstance(raw_payload, str)
        json.loads(raw_payload)  # must be valid JSON text, not a dict already

        due = await fetch_due_slots(pool, run_id)
        assert len(due) == 1
        assert due[0].slot_id == "s1"
        assert due[0].trip_id == trip_id
        assert due[0].keyword_seed == "hoi an tours"

    @pytest.mark.asyncio
    async def test_produced_slot_excluded_from_due_query(self, pool, db):
        run_id = await create_weekly_produce_run(pool, str(TENANT), 2026, 1)

        class _Grid:
            slots = [_slot(slot_id="s1", week=1, kind="evergreen"),
                    _slot(slot_id="s2", week=1, kind="evergreen", trip_id=uuid.uuid4())]

        await persist_slot_grid(pool, run_id, str(TENANT), 1, _Grid())
        assert {s.slot_id for s in await fetch_due_slots(pool, run_id)} == {"s1", "s2"}

        await mark_slot_status(pool, "s1", "produced")

        due_after = await fetch_due_slots(pool, run_id)
        assert {s.slot_id for s in due_after} == {"s2"}


class TestMarkSlotStatus:
    @pytest.mark.asyncio
    async def test_rejects_unrecognized_status(self, pool):
        with pytest.raises(ValueError):
            await mark_slot_status(pool, "s1", "bogus")

    @pytest.mark.asyncio
    async def test_skipped_records_reason(self, pool, db):
        run_id = await create_weekly_produce_run(pool, str(TENANT), 2026, 1)

        class _Grid:
            slots = [_slot(slot_id="s1", week=1, kind="evergreen")]

        await persist_slot_grid(pool, run_id, str(TENANT), 1, _Grid())
        await mark_slot_status(pool, "s1", "skipped", reason="no demand evidence")
        assert db.slots["s1"]["status"] == "skipped"
        assert db.slots["s1"]["skipped_reason"] == "no demand evidence"


class TestAllocateAndPersistWeek:
    @pytest.mark.asyncio
    async def test_combined_flow_returns_run_id_and_persisted_slots(self, pool, db, monkeypatch):
        """allocate_month() itself hits fetch_trips/fetch_atoms_by_trip (real DB calls) — not
        under test here (already covered by test_aa301_allocator.py /
        test_aa301_quarter.py); patched out so this test exercises only the new
        create-run -> allocate -> persist wiring."""
        import services.acp_planning.allocator as allocator_mod

        t = _trip()
        plan = _approved_plan(TENANT, [t.id], {"Ha Giang": 1.0})
        runway = _full_runway()

        async def _fake_allocate_month(*a, **kw):
            return compute_slot_grid(TENANT, 2026, 2, ["blog"], 4, plan, runway,
                                     {t.id: t}, {t.id: _atoms(t.id, 12)}, "US")

        monkeypatch.setattr(allocator_mod, "allocate_month", _fake_allocate_month)

        run_id, slots = await allocate_and_persist_week(
            TENANT, 2026, 2, 1, ["blog"], 4, plan, runway, "US", pool,
        )

        assert run_id == str(db.runs[(str(TENANT), 2026, 1)])
        assert all(s.week == 1 for s in slots)
        assert set(db.slots.keys()) == {s.slot_id for s in slots}

        # calling it again for the same week must reuse the same run_id, not fork a new one
        run_id_2, _ = await allocate_and_persist_week(
            TENANT, 2026, 2, 1, ["blog"], 4, plan, runway, "US", pool,
        )
        assert run_id_2 == run_id
        assert len(db.runs) == 1
