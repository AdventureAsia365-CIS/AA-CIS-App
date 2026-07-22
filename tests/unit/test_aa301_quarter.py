"""AA-301 — N5 Quarter Plan: B4 (fuzzy special matching) and B5 (thin-trip
share cap) fixes, Gate B (approval required).

Pure Python — no DB, no LLM.
"""
import uuid

import pytest

from services.acp_planning.constants import THIN_TRIP_MAX_SHARE
from services.acp_planning.models import (AtomRecord, RunwayCell, RunwayMap, Trip,
                                          compute_trips_hash)
from services.acp_planning.quarter import (_cap_thin_trip_shares, _fuzzy_match,
                                           approve_quarter_plan, compute_quarter_plan)
from services.acp_shared.atom_constants import THIN_TRIP_ATOM_MIN

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _trip(**over):
    base = dict(id=uuid.uuid4(), name="Test Trip", destination="Testland", period="Mar-May",
                lifecycle_stage="active")
    base.update(over)
    return Trip(**base)


def _atom(trip_id, distinctiveness="HIGH", atom_id=None):
    return AtomRecord(atom_id=atom_id or f"atom_{uuid.uuid4().hex[:8]}", trip_id=trip_id,
                       text="atom text", distinctiveness=distinctiveness)


class TestFuzzyMatchB4:
    """Issue's own worked examples."""

    def test_sapa_trekking_matches_sapa_valley_trek(self):
        assert _fuzzy_match("sapa trekking", "Sapa Valley Trek", "Sapa") is True

    def test_ha_giang_loop_matches_full_name(self):
        assert _fuzzy_match("ha giang loop", "Ha Giang Loop by Motorbike", "Ha Giang") is True

    def test_unrelated_trip_not_matched(self):
        assert _fuzzy_match("sapa trekking", "Hanoi City Tour", "Vietnam") is False

    def test_substring_bug_no_longer_reproduces(self):
        """The original bug: 'sapa trekking' in 'sapa valley trek'.lower() ->
        False. Confirm the OLD substring check would have failed, to lock in
        that we replaced it, not just happened to also pass."""
        old_buggy_result = "sapa trekking" in "sapa valley trek".lower()
        assert old_buggy_result is False
        assert _fuzzy_match("sapa trekking", "Sapa Valley Trek", "Sapa") is True


class TestThinTripCapB5:
    def test_thin_trip_share_capped(self):
        """Issue's own numbers: Ha Giang 4 atoms (thin, < THIN_TRIP_ATOM_MIN=5)
        got 0.54 share (54%) in the buggy version — must be capped."""
        shares = {"Ha Giang": 0.54, "Mongolia": 0.31, "Sapa": 0.15}
        atom_counts = {"Ha Giang": 4, "Mongolia": 12, "Sapa": 10}
        capped, notes = _cap_thin_trip_shares(shares, atom_counts)
        assert capped["Ha Giang"] <= THIN_TRIP_MAX_SHARE
        assert any("Ha Giang" in n and "thin" in n for n in notes)

    def test_non_thin_trip_not_capped(self):
        shares = {"Mongolia": 0.9}
        atom_counts = {"Mongolia": 12}
        capped, notes = _cap_thin_trip_shares(shares, atom_counts)
        assert capped["Mongolia"] == 0.9
        assert notes == []

    def test_freed_share_redistributed_sums_to_one(self):
        shares = {"Ha Giang": 0.54, "Mongolia": 0.31, "Sapa": 0.15}
        atom_counts = {"Ha Giang": 4, "Mongolia": 12, "Sapa": 10}
        capped, _ = _cap_thin_trip_shares(shares, atom_counts)
        assert abs(sum(capped.values()) - 1.0) < 1e-9

    def test_exactly_at_threshold_not_thin(self):
        shares = {"X": 0.9}
        atom_counts = {"X": THIN_TRIP_ATOM_MIN}  # == 5, not < 5
        capped, notes = _cap_thin_trip_shares(shares, atom_counts)
        assert capped["X"] == 0.9
        assert notes == []


class TestComputeQuarterPlan:
    def test_forced_special_included_via_fuzzy_match(self):
        sapa = _trip(name="Sapa Valley Trek", destination="Sapa")
        other = _trip(name="Random Beach Tour", destination="Elsewhere")
        runway = RunwayMap(tenant_id=TENANT, year=2026, cells=[])
        atoms_by_trip = {sapa.id: [_atom(sapa.id) for _ in range(6)],
                         other.id: [_atom(other.id) for _ in range(6)]}
        plan = compute_quarter_plan(
            TENANT, 2026, 1, [sapa, other], markets=["US"], capacity_posts_per_week=1,
            specials=["sapa trekking"], runway=runway, atoms_by_trip=atoms_by_trip)
        assert sapa.id in plan.forced_specials

    def test_thin_trip_share_capped_end_to_end(self):
        thin = _trip(name="Ha Giang Loop", destination="Ha Giang")
        rich = _trip(name="Mongolia Gobi", destination="Mongolia")
        runway = RunwayMap(tenant_id=TENANT, year=2026, cells=[])
        atoms_by_trip = {thin.id: [_atom(thin.id) for _ in range(4)],
                         rich.id: [_atom(rich.id) for _ in range(12)]}
        plan = compute_quarter_plan(
            TENANT, 2026, 1, [thin, rich], markets=["US"], capacity_posts_per_week=4,
            specials=[], runway=runway, atoms_by_trip=atoms_by_trip)
        assert plan.destination_shares.get("Ha Giang", 0) <= THIN_TRIP_MAX_SHARE
        assert plan.thin_trip_notes

    def test_retired_trip_excluded(self):
        retired = _trip(lifecycle_stage="retired")
        runway = RunwayMap(tenant_id=TENANT, year=2026, cells=[])
        plan = compute_quarter_plan(
            TENANT, 2026, 1, [retired], markets=["US"], capacity_posts_per_week=1,
            specials=[], runway=runway, atoms_by_trip={})
        assert retired.id not in plan.trip_ids

    def test_gate_b_defaults_unapproved(self):
        t = _trip()
        runway = RunwayMap(tenant_id=TENANT, year=2026, cells=[])
        plan = compute_quarter_plan(
            TENANT, 2026, 1, [t], markets=["US"], capacity_posts_per_week=1,
            specials=[], runway=runway, atoms_by_trip={t.id: [_atom(t.id)]})
        assert plan.approved is False
        assert plan.approved_by is None

    def test_approve_quarter_plan_sets_gate(self):
        t = _trip()
        runway = RunwayMap(tenant_id=TENANT, year=2026, cells=[])
        plan = compute_quarter_plan(
            TENANT, 2026, 1, [t], markets=["US"], capacity_posts_per_week=1,
            specials=[], runway=runway, atoms_by_trip={t.id: [_atom(t.id)]})
        approve_quarter_plan(plan, approved_by="ms.thu")
        assert plan.approved is True
        assert plan.approved_by == "ms.thu"

    def test_trips_hash_stamped(self):
        t = _trip()
        runway = RunwayMap(tenant_id=TENANT, year=2026, cells=[])
        plan = compute_quarter_plan(
            TENANT, 2026, 1, [t], markets=["US"], capacity_posts_per_week=1,
            specials=[], runway=runway, atoms_by_trip={})
        assert plan.trips_hash == compute_trips_hash([t])


class TestNoLlmCost:
    def test_no_bedrock_or_anthropic_imports(self):
        import services.acp_planning.quarter as mod
        src = open(mod.__file__).read()
        for banned in ("boto3", "bedrock", "anthropic", "invoke_model", "invoke_claude"):
            assert banned not in src.lower(), f"N5 must be $0 LLM — found '{banned}' in quarter.py"
