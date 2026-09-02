"""AA-449 — services/acp_angle_gate/service.py (request lifecycle). Mocked asyncpg pool, same
convention test_aa448_v1_planning.py already uses. generate_angles() is patched — this file
tests the DB lifecycle/state-machine, not LLM behavior (see test_aa449_angle_gate_generate.py
for that)."""
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.acp_angle_gate import service
from services.acp_planning.models import QuarterPlan, RunwayMap, Slot, SlotGrid
from services.acp_planning.tenant_config import TenantNotFoundError, TenantPlanningConfig

TENANT_ID = uuid.uuid4()
OTHER_TENANT_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
TRIP_ID = uuid.uuid4()


class _TxnCM:
    """conn.transaction() is a sync method returning an async context manager — AsyncMock's
    default mocks the METHOD as async, not its return value, so `async with conn.transaction():`
    breaks unless overridden this way. Same fix as test_aa309_tenant_onboarding.py/
    test_aa367_packets.py/test_aa448_v1_planning.py."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _make_pool(conn):
    conn.transaction = MagicMock(return_value=_TxnCM())
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
        "request_id": REQUEST_ID, "tenant_id": TENANT_ID, "atom_id": "atom_abc123",
        "trip_id": TRIP_ID, "channel": "facebook", "goal": None, "cta": None,
        "status": "pending_goal", "dfs_paa_snapshot": None,  # AA-501, migration 127
        "route_segment_ids": None,  # AA-511 Gap A, migration 134
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    base.update(over)
    return base


def _option_row(idx, recommended=False, chosen=False):
    return {
        "idx": idx, "name": f"Angle {idx}", "why_it_works": "why", "formula_fit": "AIDA",
        "best_final_style": "style", "recommended": recommended, "chosen": chosen,
    }


class _StatefulAngleOptionConn:
    """AA-494 prerequisite fix test double — tracks angle_gate_option.chosen state directly
    across multiple choose_angle() calls, unlike the AsyncMock-with-side_effect style the rest
    of this file uses (which only checks call counts/args, not resulting DB state). Needed here
    because the fix's correctness is specifically about final state after 2 calls, not just
    which queries fire once."""
    def __init__(self):
        self.options = {0: False, 1: False, 2: False}
        self.request_status = "pending_choice"

    async def fetchrow(self, query, *args):
        if "angle_gate_request" in query:
            return _request_row(status=self.request_status, goal="promotion")
        return None

    async def fetch(self, query, *args):
        return [_option_row(i, chosen=self.options[i]) for i in sorted(self.options)]

    async def execute(self, query, *args):
        if "SET chosen = true" in query:
            _, idx = args
            if idx not in self.options:
                return "UPDATE 0"
            self.options[idx] = True
            return "UPDATE 1"
        if "SET chosen = false" in query:
            _, idx = args
            n = 0
            for i in self.options:
                if i != idx:
                    self.options[i] = False
                    n += 1
            return f"UPDATE {n}"
        if "SET status = 'approved'" in query:
            self.request_status = "approved"
            return "UPDATE 1"
        return "UPDATE 0"


@pytest.mark.asyncio
class TestCreateRequest:
    async def test_creates_request_for_owned_atom(self):
        """AA-469 Việc 4 (flow-order fix) — create_request() no longer takes channel, and no
        longer does any slot-CTA lookup (that moved to set_channel(), see TestSetChannel below)
        — just the atom ownership check + a bare INSERT with channel/cta both NULL."""
        conn = AsyncMock()
        conn.fetchrow.side_effect = [_atom_row(), _request_row(channel=None, cta=None)]
        pool = _make_pool(conn)

        result = await service.create_request(TENANT_ID, "atom_abc123", pool)

        assert result["status"] == "pending_goal"
        insert_query, *params = conn.fetchrow.call_args_list[1][0]
        assert "INSERT INTO acp_shared.angle_gate_request" in insert_query
        assert params[0] == TENANT_ID
        assert conn.fetchrow.call_count == 2  # atom check + INSERT — no slot-CTA lookup anymore

    async def test_atom_not_owned_raises_not_found(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None  # owner_scope check finds nothing
        pool = _make_pool(conn)
        with pytest.raises(service.AtomNotFoundError):
            await service.create_request(TENANT_ID, "atom_someone_elses", pool)


@pytest.mark.asyncio
class TestSetGoalAndGenerate:
    async def test_happy_path_writes_goal_and_three_options(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _request_row(status="pending_goal"),  # _fetch_request_row (status check)
            _atom_row(),                          # _fetch_atom_for_tenant
            {"customer_segment": "Senior execs", "customer_mindset": "seek depth"},  # brand fetchrow
            None,  # AA-469: fetch_search_demand_signal -> no seo_context row for this trip
        ]
        conn.fetch.return_value = []  # fetch_tenant_trips -> no trips (trip_name stays None, fine)
        pool = _make_pool(conn)

        angles = [
            {"name": "A", "why_it_works": "wa", "formula_fit": "fa", "best_final_style": "sa"},
            {"name": "B", "why_it_works": "wb", "formula_fit": "fb", "best_final_style": "sb"},
            {"name": "C", "why_it_works": "wc", "formula_fit": "fc", "best_final_style": "sc"},
        ]
        with patch.object(service, "generate_angles", new=AsyncMock(return_value=(angles, 1, "B is best", 0.02))), \
             patch.object(service, "fetch_request", new=AsyncMock(return_value={"status": "pending_choice"})):
            result = await service.set_goal_and_generate(TENANT_ID, REQUEST_ID, "promotion", pool)

        assert result["status"] == "pending_choice"
        insert_calls = [c for c in conn.execute.call_args_list if "angle_gate_option" in c[0][0]]
        assert len(insert_calls) == 3
        # recommended=True only on idx 1
        recommended_flags = [c[0][-1] for c in insert_calls]
        assert recommended_flags == [False, True, False]

    async def test_search_demand_signal_fetched_and_passed_when_trip_id_present(self):
        """AA-469 Việc 4 — set_goal_and_generate() must actually resolve the DFS/PAA signal
        (via fetch_search_demand_signal) and hand it to generate_angles(), not just accept the
        new kwarg without ever populating it."""
        from services.acp_shared.dfs_relevance import SearchDemandSignal
        signal = SearchDemandSignal(
            relevance="HIGH", people_also_ask=["q1"], related_keywords=["k1"],
        )
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _request_row(status="pending_goal"),
            _atom_row(),
            {"customer_segment": "Senior execs", "customer_mindset": "seek depth"},
        ]
        conn.fetch.return_value = []
        pool = _make_pool(conn)

        angles = [
            {"name": "A", "why_it_works": "wa", "formula_fit": "fa", "best_final_style": "sa"},
            {"name": "B", "why_it_works": "wb", "formula_fit": "fb", "best_final_style": "sb"},
            {"name": "C", "why_it_works": "wc", "formula_fit": "fc", "best_final_style": "sc"},
        ]
        mock_generate = AsyncMock(return_value=(angles, 0, "reason", 0.02))
        with patch.object(service, "generate_angles", new=mock_generate), \
             patch.object(service, "fetch_search_demand_signal", new=AsyncMock(return_value=signal)), \
             patch.object(service, "fetch_request", new=AsyncMock(return_value={"status": "pending_choice"})):
            await service.set_goal_and_generate(TENANT_ID, REQUEST_ID, "promotion", pool)

        assert mock_generate.call_args.kwargs["search_demand"] is signal

    async def test_search_demand_signal_skipped_when_no_trip_id(self):
        """A request with no trip_id (atom not linked to a trip) must not attempt a seo_context
        lookup at all — mirrors the existing trip_name/destination guard just above it."""
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _request_row(status="pending_goal", trip_id=None),
            _atom_row(),
            {"customer_segment": "Senior execs", "customer_mindset": "seek depth"},
        ]
        pool = _make_pool(conn)

        angles = [
            {"name": "A", "why_it_works": "wa", "formula_fit": "fa", "best_final_style": "sa"},
            {"name": "B", "why_it_works": "wb", "formula_fit": "fb", "best_final_style": "sb"},
            {"name": "C", "why_it_works": "wc", "formula_fit": "fc", "best_final_style": "sc"},
        ]
        mock_generate = AsyncMock(return_value=(angles, 0, "reason", 0.02))
        mock_signal = AsyncMock()
        with patch.object(service, "generate_angles", new=mock_generate), \
             patch.object(service, "fetch_search_demand_signal", new=mock_signal), \
             patch.object(service, "fetch_request", new=AsyncMock(return_value={"status": "pending_choice"})):
            await service.set_goal_and_generate(TENANT_ID, REQUEST_ID, "promotion", pool)

        mock_signal.assert_not_called()
        assert mock_generate.call_args.kwargs["search_demand"] is None

    async def test_dfs_paa_snapshot_persisted_when_signal_present(self):
        """AA-501 (migration 127) — the SearchDemandSignal used to build the LLM prompt must be
        persisted onto angle_gate_request.dfs_paa_snapshot in the SAME UPDATE that sets goal/
        status, as a JSON-serialized snapshot (not re-fetched live later)."""
        import json

        from services.acp_shared.dfs_relevance import SearchDemandSignal
        signal = SearchDemandSignal(relevance="HIGH", people_also_ask=["q1"], related_keywords=["k1"])
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _request_row(status="pending_goal"),
            _atom_row(),
            {"customer_segment": "Senior execs", "customer_mindset": "seek depth"},
        ]
        conn.fetch.return_value = []
        pool = _make_pool(conn)

        angles = [
            {"name": "A", "why_it_works": "wa", "formula_fit": "fa", "best_final_style": "sa"},
            {"name": "B", "why_it_works": "wb", "formula_fit": "fb", "best_final_style": "sb"},
            {"name": "C", "why_it_works": "wc", "formula_fit": "fc", "best_final_style": "sc"},
        ]
        with patch.object(service, "generate_angles", new=AsyncMock(return_value=(angles, 0, "r", 0.02))), \
             patch.object(service, "fetch_search_demand_signal", new=AsyncMock(return_value=signal)), \
             patch.object(service, "fetch_request", new=AsyncMock(return_value={"status": "pending_choice"})):
            await service.set_goal_and_generate(TENANT_ID, REQUEST_ID, "promotion", pool)

        update_call = next(
            c for c in conn.execute.call_args_list if "UPDATE acp_shared.angle_gate_request" in c[0][0]
        )
        _, _request_id, _goal_key, snapshot_json = update_call[0]
        assert json.loads(snapshot_json) == {
            "relevance": "HIGH", "people_also_ask": ["q1"], "related_keywords": ["k1"],
        }

    async def test_dfs_paa_snapshot_null_when_no_signal(self):
        """No trip_id / no seo_context row -> fetch_search_demand_signal() returns None ->
        dfs_paa_snapshot must be persisted as NULL, not an empty object."""
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _request_row(status="pending_goal", trip_id=None),
            _atom_row(),
            {"customer_segment": "Senior execs", "customer_mindset": "seek depth"},
        ]
        pool = _make_pool(conn)

        angles = [
            {"name": "A", "why_it_works": "wa", "formula_fit": "fa", "best_final_style": "sa"},
            {"name": "B", "why_it_works": "wb", "formula_fit": "fb", "best_final_style": "sb"},
            {"name": "C", "why_it_works": "wc", "formula_fit": "fc", "best_final_style": "sc"},
        ]
        with patch.object(service, "generate_angles", new=AsyncMock(return_value=(angles, 0, "r", 0.02))), \
             patch.object(service, "fetch_request", new=AsyncMock(return_value={"status": "pending_choice"})):
            await service.set_goal_and_generate(TENANT_ID, REQUEST_ID, "promotion", pool)

        update_call = next(
            c for c in conn.execute.call_args_list if "UPDATE acp_shared.angle_gate_request" in c[0][0]
        )
        assert update_call[0][3] is None

    async def test_wrong_status_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_choice")  # already past pending_goal
        pool = _make_pool(conn)
        with pytest.raises(service.WrongStatusError):
            await service.set_goal_and_generate(TENANT_ID, REQUEST_ID, "promotion", pool)

    async def test_unknown_goal_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_goal")
        pool = _make_pool(conn)
        with pytest.raises(service.InvalidGoalError):
            await service.set_goal_and_generate(TENANT_ID, REQUEST_ID, "not_a_real_goal", pool)

    async def test_cross_tenant_request_not_found(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None  # WHERE tenant_id=$2 excludes another tenant's request
        pool = _make_pool(conn)
        with pytest.raises(service.RequestNotFoundError):
            await service.set_goal_and_generate(OTHER_TENANT_ID, REQUEST_ID, "promotion", pool)


@pytest.mark.asyncio
class TestChooseAngle:
    async def test_happy_path_sets_chosen_and_approved(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_choice", goal="promotion")
        conn.execute.side_effect = ["UPDATE 1", "UPDATE 2", "UPDATE 1"]
        pool = _make_pool(conn)

        with patch.object(service, "fetch_request", new=AsyncMock(return_value={"status": "approved"})):
            result = await service.choose_angle(TENANT_ID, REQUEST_ID, 1, pool)

        assert result["status"] == "approved"
        status_update = [c for c in conn.execute.call_args_list if "SET status = 'approved'" in c[0][0]]
        assert len(status_update) == 1
        # AA-494 prerequisite fix — the other 2 options must be explicitly unset in the same call.
        unset_call = [c for c in conn.execute.call_args_list if "SET chosen = false" in c[0][0]]
        assert len(unset_call) == 1
        _, unset_request_id, unset_idx = unset_call[0][0]
        assert (unset_request_id, unset_idx) == (REQUEST_ID, 1)

    async def test_choosing_twice_unsets_previous_choice(self):
        """The bug this fixes: choose_angle() used to leave a previously-chosen option's
        chosen=true forever, so a future design that allows re-choosing a different angle
        (Decision 3) would have T9 read the FIRST chosen=true row by idx, not the latest. The
        live guard (status must be 'pending_choice') blocks a second real call today — this
        test bypasses it via a stateful fake connection (resetting status between calls) so the
        underlying data-mutation logic is verified now and stays meaningful once the guard is
        loosened later, per the build task's own requirement."""
        conn = _StatefulAngleOptionConn()
        pool = _make_pool(conn)

        await service.choose_angle(TENANT_ID, REQUEST_ID, 0, pool)
        assert conn.options == {0: True, 1: False, 2: False}

        conn.request_status = "pending_choice"  # simulate a future status allowing re-choice
        await service.choose_angle(TENANT_ID, REQUEST_ID, 2, pool)

        assert conn.options == {0: False, 1: False, 2: True}, (
            "only the most recently chosen option should have chosen=true"
        )

    async def test_wrong_status_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_goal")  # no angles generated yet
        pool = _make_pool(conn)
        with pytest.raises(service.WrongStatusError):
            await service.choose_angle(TENANT_ID, REQUEST_ID, 0, pool)

    async def test_invalid_idx_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_choice")
        pool = _make_pool(conn)
        with pytest.raises(service.AngleGateError):
            await service.choose_angle(TENANT_ID, REQUEST_ID, 7, pool)


@pytest.mark.asyncio
class TestFetchRequest:
    async def test_returns_request_with_ordered_angles(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_choice", goal="promotion")
        conn.fetch.return_value = [_option_row(0), _option_row(1, recommended=True), _option_row(2)]
        pool = _make_pool(conn)

        result = await service.fetch_request(TENANT_ID, REQUEST_ID, pool)

        assert result["status"] == "pending_choice"
        assert len(result["angles"]) == 3
        assert result["angles"][1]["recommended"] is True

    async def test_not_found_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = _make_pool(conn)
        with pytest.raises(service.RequestNotFoundError):
            await service.fetch_request(TENANT_ID, REQUEST_ID, pool)

    async def test_dfs_paa_snapshot_parsed_from_json_string(self):
        """AA-501 — asyncpg has no jsonb codec registered on this app's connections (same gap
        admin_a4.py's _parse_jsonb already works around), so dfs_paa_snapshot arrives as a raw
        JSON string and must be parsed, not returned as-is."""
        import json
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(
            status="pending_choice", goal="promotion",
            dfs_paa_snapshot=json.dumps({"relevance": "MED", "people_also_ask": ["q"], "related_keywords": []}),
        )
        conn.fetch.return_value = []
        pool = _make_pool(conn)

        result = await service.fetch_request(TENANT_ID, REQUEST_ID, pool)

        assert result["dfs_paa_snapshot"] == {
            "relevance": "MED", "people_also_ask": ["q"], "related_keywords": [],
        }

    async def test_dfs_paa_snapshot_none_stays_none(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_choice", goal="promotion")
        conn.fetch.return_value = []
        pool = _make_pool(conn)

        result = await service.fetch_request(TENANT_ID, REQUEST_ID, pool)

        assert result["dfs_paa_snapshot"] is None


# AA-451 — create_request()'s optional year/month compute-and-persist path
# (_compute_and_persist_slot_cta). All the tenant-scoped fetchers/allocator functions are
# patched at the module level (services.acp_angle_gate.service's own imported names) rather than
# hitting real DB logic here — that logic (compute_slot_grid, persist_slot_grid, etc.) already
# has its own dedicated test coverage (test_aa301_allocator.py, test_aa377_aa378_run_slot_persist
# .py). These tests only verify create_request() wires year/month through correctly and degrades
# to cta=None (never raises) on every "can't compute yet" state.
_CONFIG = TenantPlanningConfig(markets=["US"], channels=["facebook"], capacity_posts_per_week=2)
_PLAN = QuarterPlan(tenant_id=TENANT_ID, year=2026, quarter=3, trip_ids=[TRIP_ID],
                    approved=True, approved_by="tenant:x")
_RUNWAY = RunwayMap(tenant_id=TENANT_ID, year=2026, cells=[])
_SLOT = Slot(slot_id="slot_abc", week=1, channel="facebook", kind="evergreen",
            trip_id=TRIP_ID, atom_ids=["atom_abc123"], cta_target="https://real-cta.example/book")
_GRID = SlotGrid(tenant_id=TENANT_ID, year=2026, month=8, slots=[_SLOT])


def _patch_compute_chain(stack, **overrides):
    """Common patch set for the compute-and-persist branch — individual tests override just the
    pieces they need to exercise a particular early-return. `stack` is a contextlib.ExitStack
    the caller owns, so patches stay active for the whole `with stack:` block (assertions on the
    mocks must run before they're torn down)."""
    defaults = dict(
        fetch_tenant_planning_config=AsyncMock(return_value=_CONFIG),
        fetch_approved_quarter_plan=AsyncMock(return_value=_PLAN),
        fetch_tenant_trips=AsyncMock(return_value=[]),
        fetch_tenant_atoms_by_trip=AsyncMock(return_value={}),
        compute_runway_map=MagicMock(return_value=_RUNWAY),
        compute_slot_grid=MagicMock(return_value=_GRID),
        create_weekly_produce_run=AsyncMock(return_value="run_1"),
        persist_slot_grid=AsyncMock(return_value=[_SLOT]),
    )
    defaults.update(overrides)
    for name, mock in defaults.items():
        stack.enter_context(patch.object(service, name, new=mock))


@pytest.mark.asyncio
class TestSetChannel:
    """AA-469 Việc 4 (flow-order fix) — set_channel() is the new workflow step 8, replacing
    create_request()'s old channel param. Also where AA-451's slot-CTA prefill now lives (moved
    from create_request(), which no longer knows channel at all)."""

    async def test_wrong_status_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="pending_choice")
        pool = _make_pool(conn)
        with pytest.raises(service.WrongStatusError):
            await service.set_channel(TENANT_ID, REQUEST_ID, "facebook", pool)

    async def test_unknown_channel_raises(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="approved", channel=None, cta=None)
        pool = _make_pool(conn)
        with pytest.raises(service.InvalidChannelError):
            await service.set_channel(TENANT_ID, REQUEST_ID, "not_a_real_channel", pool)

    async def test_happy_path_no_year_month_sets_channel_cta_stays_none(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _request_row(status="approved", channel=None, cta=None),  # _fetch_request_row
            None,  # _fetch_slot_cta — nothing persisted
            _request_row(status="approved", channel="facebook", cta=None),  # fetch_request() re-read
        ]
        conn.fetch.return_value = []  # fetch_request()'s angle_gate_option SELECT
        pool = _make_pool(conn)

        result = await service.set_channel(TENANT_ID, REQUEST_ID, "facebook", pool)

        assert result["channel"] == "facebook"
        assert result["cta"] is None
        update_query, *params = conn.execute.call_args_list[0][0]
        assert "UPDATE acp_shared.angle_gate_request" in update_query
        assert params == [REQUEST_ID, "facebook", None]

    async def test_year_month_given_computes_persists_and_refetches_cta(self):
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _request_row(status="approved", channel=None, cta=None),  # _fetch_request_row
            None,  # _fetch_slot_cta — nothing yet
            {"cta_target": "https://real-cta.example/book"},  # _fetch_slot_cta re-read, post-persist
            _request_row(status="approved", channel="facebook", cta="https://real-cta.example/book"),
        ]
        conn.fetch.return_value = []
        pool = _make_pool(conn)

        with ExitStack() as stack:
            _patch_compute_chain(stack)
            result = await service.set_channel(
                TENANT_ID, REQUEST_ID, "facebook", pool, year=2026, month=8,
            )
            service.create_weekly_produce_run.assert_awaited_once()
            service.persist_slot_grid.assert_awaited_once()

        assert result["cta"] == "https://real-cta.example/book"
        update_query, *params = conn.execute.call_args_list[0][0]
        assert params[-1] == "https://real-cta.example/book"

    async def test_already_has_cta_never_overwritten(self):
        """A request that already resolved a real CTA (however it got there) must not have it
        clobbered by a later set_channel() call, even if that call also supplies year/month."""
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _request_row(status="approved", channel=None, cta="https://existing-cta.example"),
            _request_row(status="approved", channel="tiktok", cta="https://existing-cta.example"),
        ]
        conn.fetch.return_value = []
        pool = _make_pool(conn)

        with ExitStack() as stack:
            _patch_compute_chain(stack)
            result = await service.set_channel(
                TENANT_ID, REQUEST_ID, "tiktok", pool, year=2026, month=8,
            )
            service.fetch_approved_quarter_plan.assert_not_called()  # never reached — cta already set

        assert result["cta"] == "https://existing-cta.example"

    async def test_callable_again_while_still_approved_switches_channel(self):
        """The tenant can pick a channel, change their mind, pick a different one, all before
        T9 ever writes — set_channel() has no one-shot guard, unlike choose_angle()."""
        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _request_row(status="approved", channel="facebook", cta=None),
            None,
            _request_row(status="approved", channel="tiktok", cta=None),
        ]
        conn.fetch.return_value = []
        pool = _make_pool(conn)

        result = await service.set_channel(TENANT_ID, REQUEST_ID, "tiktok", pool)

        assert result["channel"] == "tiktok"

    async def test_reusable_status_rejected(self):
        """set_channel() is only valid from 'approved' — a request mid-reopen ('reusable',
        re-picking a different angle) is not a valid target. choose_angle() always lands back on
        'approved' anyway (same reasoning start_write()'s guard already documents)."""
        conn = AsyncMock()
        conn.fetchrow.return_value = _request_row(status="reusable")
        pool = _make_pool(conn)
        with pytest.raises(service.WrongStatusError):
            await service.set_channel(TENANT_ID, REQUEST_ID, "facebook", pool)
