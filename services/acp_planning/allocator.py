"""
services.acp_planning.allocator — N6 Slot Allocator (1x/month + invalidation).

Ported from aamc/planning.py's allocate_month()/D5 (aa-marketing-v2 research
build). Output: a calendar grid, each cell already filled with atom_ids +
framework + funnel_stage + CTA. Pure Python, $0 LLM.

Fixes applied during the port (see docs/implementation-notes/AA-301.md):
  B7 — cooldown was only applied post-publish (a.cooldown_until), so multiple
       slots for the same trip+channel within one month picked the SAME top-N
       atoms (near-duplicate content). Now tracks a used_this_month set per
       (trip_id, channel) and excludes it from the pool on every subsequent
       slot in the same allocate_month() call.
  B6  — keyword was assigned per-TRIP (all slots of a trip shared one
       keyword), causing SERP self-competition. Slot.keyword_seed is now
       derived from that specific slot's own top chosen atom — since B7
       guarantees no atom repeats within the month for the same trip+channel,
       keyword_seed is naturally distinct slot-to-slot.

Also implements (not bug fixes, new requirements):
  - Atom floor (AA-300): a trip+channel whose live atom pool cannot cover
    its planned slots without repeating gets its slots dropped (not
    silently repeated) and a note logged — this falls out of the same
    used_this_month/empty-pool check as B7.
  - Reactive-hold slots (10% per SLOT_MIX) stay empty with a note that
    Mode-B (agency-message-fills-slot) is not yet defined — not designed
    here, per issue instruction.
  - Gate B: refuses to allocate from an unapproved QuarterPlan
    (QuarterPlanNotApprovedError).
  - phasing_out trips (raw_tours.lifecycle_stage) are only allocated slots
    in the real current calendar month — excluded from any other month's
    grid (interpretation of the issue's "N6 tháng hiện tại" trigger; the
    issue text is ambiguous on the exact mechanism, self-chosen, see AA-301
    implementation notes).
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional
from uuid import UUID

from .constants import FRAMEWORK_TABLE, SLOT_MIX
from .models import (AtomRecord, QuarterPlan, QuarterPlanNotApprovedError,
                     RunwayMap, Slot, SlotGrid, Trip)


def _add_note(notes: list[str], message: str) -> None:
    """Dedupe — the evergreen round-robin can retry an exhausted
    destination/channel many times in one call (matches the original
    aamc design: 'atoms exhausted — grid stays short, honestly'), which
    would otherwise repeat the same log line dozens of times."""
    if message not in notes:
        notes.append(message)


def _eligible_atoms(atoms: list[AtomRecord], channel: str, used_this_month: set[str],
                     today: date) -> list[AtomRecord]:
    pool = []
    for a in atoms:
        if a.deleted or a.atom_id in used_this_month:
            continue
        cd = a.cooldown_until.get(channel)
        if cd and cd > today.isoformat():
            continue
        w = a.weight * (1.5 if a.starred else 1.0) * {"HIGH": 1.5, "MED": 1.0, "LOW": 0.6}[a.distinctiveness]
        pool.append((w, a))
    return [a for _, a in sorted(pool, key=lambda x: -x[0])]


def compute_slot_grid(
    tenant_id: UUID, year: int, month: int, channels: list[str],
    capacity_posts_per_week: int, quarter_plan: QuarterPlan, runway: RunwayMap,
    trips_by_id: dict[UUID, Trip], atoms_by_trip: dict[UUID, list[AtomRecord]],
    primary_market: str, today: Optional[date] = None,
) -> SlotGrid:
    """Pure computation — no DB, no LLM, 100% unit-testable."""
    if not quarter_plan.approved:
        raise QuarterPlanNotApprovedError(
            "Gate B: quarter plan must be approved by a human (Ms. Thu) before allocation — never auto.")
    if quarter_plan.tenant_id != tenant_id:
        raise ValueError("quarter_plan.tenant_id does not match tenant_id — refusing cross-tenant allocation.")

    today = today or date.today()
    is_current_month = (year, month) == (today.year, today.month)

    weeks = [1, 2, 3, 4]
    total_slots = capacity_posts_per_week * len(weeks)
    n_hold = max(1, round(total_slots * SLOT_MIX["reactive_held_empty"]))
    n_campaign = round(total_slots * SLOT_MIX["campaign"]) if quarter_plan.forced_specials else 0
    n_evergreen = total_slots - n_hold - n_campaign

    notes: list[str] = []
    used_this_month: dict[tuple[UUID, str], set[str]] = {}

    trips_by_dest: dict[str, list[UUID]] = {}
    excluded_phasing = []
    for tid in quarter_plan.trip_ids:
        t = trips_by_id.get(tid)
        if t is None:
            continue
        if t.lifecycle_stage == "phasing_out" and not is_current_month:
            excluded_phasing.append(t.name)
            continue
        trips_by_dest.setdefault(t.destination or t.name, []).append(tid)
    if excluded_phasing:
        notes.append(
            f"Excluded phasing_out trips from {year}-{month:02d} (not the current month): {excluded_phasing}")

    share_order = sorted(quarter_plan.destination_shares.items(), key=lambda x: -x[1])
    dest_cycle = [d for d, _ in share_order if d in trips_by_dest] or list(trips_by_dest)

    grid = SlotGrid(tenant_id=tenant_id, year=year, month=month, trips_hash=quarter_plan.trips_hash)
    slot_n = 0
    campaign_trip_ids = quarter_plan.forced_specials or quarter_plan.trip_ids[:1]

    def make_slot(kind: str, trip_id: Optional[UUID]) -> Optional[Slot]:
        nonlocal slot_n
        week = weeks[slot_n % len(weeks)]
        channel = channels[slot_n % len(channels)]
        slot_n += 1
        if kind == "reactive_hold":
            return Slot(
                slot_id=f"slot_{uuid.uuid4().hex[:10]}", week=week, channel=channel,
                kind="reactive_hold", funnel_stage="TOFU",
                topic_hint="HELD EMPTY for reactive content (Mode-B process not yet defined)")
        t = trips_by_id.get(trip_id)
        if t is None:
            return None
        dest = t.destination or t.name
        stage = runway.stage(dest, primary_market, month)
        if stage == "OFF":
            stage = "TOFU"  # off-window content still captures; never converts
        atoms = atoms_by_trip.get(trip_id, [])
        key = (trip_id, channel)
        used = used_this_month.setdefault(key, set())
        pool = _eligible_atoms(atoms, channel, used, today)
        n_atoms = 1 if channel in ("facebook", "tiktok") else min(4, len(pool))
        if not pool:
            _add_note(
                notes,
                f"Trip '{t.name}' has no eligible atoms left for {channel} this month "
                f"(atom floor reached or all on cooldown) — slot dropped, not repeated.")
            return None
        live_count = sum(1 for a in atoms if not a.deleted)
        if live_count < 2 * max(1, n_atoms):
            _add_note(
                notes,
                f"Trip '{t.name}' atom floor: {live_count} live atoms < 2x{n_atoms} planned "
                f"slots for {channel} — capacity implicitly reduced, no silent atom repeat.")
        chosen = pool[:n_atoms]
        used.update(a.atom_id for a in chosen)
        fw_key = (stage, "blog") if channel == "blog" else ("ANY", channel)
        fw = FRAMEWORK_TABLE.get(fw_key, {"framework": "hub"})["framework"]
        cta = t.trip_url if t.url_alive else None
        return Slot(
            slot_id=f"slot_{uuid.uuid4().hex[:10]}", week=week, channel=channel, kind=kind,
            trip_id=trip_id, atom_ids=[a.atom_id for a in chosen],
            funnel_stage=stage, framework=fw, cta_target=cta,
            topic_hint=chosen[0].text[:80],
            keyword_seed=chosen[0].text[:60],  # B6 fix — per-slot, from this slot's own top atom
        )

    i = 0
    guard = total_slots * 4
    while (sum(1 for s in grid.slots if s.kind == "evergreen") < n_evergreen
           and dest_cycle and i < guard):
        dest = dest_cycle[i % len(dest_cycle)]
        tids = trips_by_dest.get(dest, [])
        if tids:
            s = make_slot("evergreen", tids[i % len(tids)])
            if s:
                grid.slots.append(s)
        i += 1

    for j in range(n_campaign):
        s = make_slot("campaign", campaign_trip_ids[j % len(campaign_trip_ids)])
        if s:
            grid.slots.append(s)

    for _ in range(n_hold):
        s = make_slot("reactive_hold", None)
        if s:
            grid.slots.append(s)

    if notes:
        grid.capacity_note = " | ".join(notes)
    return grid


async def allocate_month(
    tenant_id: UUID, year: int, month: int, channels: list[str],
    capacity_posts_per_week: int, quarter_plan: QuarterPlan, runway: RunwayMap,
    primary_market: str, pool,
) -> SlotGrid:
    """Async DB-wiring wrapper. `channels`/`capacity_posts_per_week`/
    `primary_market` are caller-supplied — same tenant-config gap noted in
    runway.py/quarter.py."""
    from .quarter import fetch_atoms_by_trip
    from .runway import fetch_trips
    trips = await fetch_trips(tenant_id, pool)
    trips_by_id = {t.id: t for t in trips}
    atoms_by_trip = await fetch_atoms_by_trip(tenant_id, pool)
    return compute_slot_grid(
        tenant_id, year, month, channels, capacity_posts_per_week,
        quarter_plan, runway, trips_by_id, atoms_by_trip, primary_market,
    )


__all__ = ["compute_slot_grid", "allocate_month"]
