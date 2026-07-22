"""
services.acp_planning.models — schemas for N4 (RunwayMap), N5 (QuarterPlan),
N6 (SlotGrid). Ported from aamc/models.py (aa-marketing-v2 research build).

tenant_id is a required field on every per-computation artifact (RunwayMap,
QuarterPlan, SlotGrid) — N4/N5/N6 run per-tenant, never cross-tenant
(AA-301 decision). Atoms stay platform-scoped (D3, owner_scope='platform') —
no tenant_id here; tenancy is inherited via tour_id -> raw_tours.tenant_id.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

FunnelStage = Literal["TOFU", "MOFU", "BOFU", "OFF"]
Channel = Literal["blog", "facebook", "tiktok", "email"]
Distinctiveness = Literal["HIGH", "MED", "LOW"]
LifecycleStage = Literal["active", "phasing_out", "retired"]


class QuarterPlanNotApprovedError(Exception):
    """Gate B: a QuarterPlan must be human-approved (Ms. Thu) before N6 can
    allocate from it. Preserves the old Gate 2 rule — REQUIRED, NEVER auto."""


# ---------------------------------------------------------------- inputs (read from DB, not computed)
class Trip(BaseModel):
    """One row of acp_contract.v_trip_registry, already scoped to a tenant."""
    id: UUID
    name: str
    destination: Optional[str] = None
    period: Optional[str] = None
    duration_raw: Optional[str] = None
    itinerary_source: Optional[str] = None
    lifecycle_stage: LifecycleStage = "active"
    trip_url: Optional[str] = None
    url_alive: Optional[bool] = None


class AtomRecord(BaseModel):
    """One row of acp_contract.tour_atoms. No tenant_id (D3 — platform-scoped)."""
    atom_id: str
    trip_id: UUID
    text: str
    distinctiveness: Distinctiveness = "LOW"
    starred: bool = False
    deleted: bool = False
    weight: float = 1.0
    cooldown_until: dict[str, Any] = Field(default_factory=dict)
    usage_log: list[Any] = Field(default_factory=list)


# ---------------------------------------------------------------- N4
class RunwayCell(BaseModel):
    destination: str
    market: str
    month: int  # 1..12
    stage: FunnelStage


class RunwayMap(BaseModel):
    tenant_id: UUID
    year: int
    cells: list[RunwayCell] = Field(default_factory=list)
    trips_hash: Optional[str] = None
    unknowns: list[str] = Field(default_factory=list)

    def stage(self, destination: str, market: str, month: int) -> FunnelStage:
        for c in self.cells:
            if c.destination == destination and c.market == market and c.month == month:
                return c.stage
        return "OFF"


# ---------------------------------------------------------------- N5
class BigRock(BaseModel):
    rock_id: str
    trip_id: UUID
    title: str
    atom_ids: list[str] = Field(default_factory=list)
    atomization_contract: dict[str, int] = Field(default_factory=dict)


class QuarterPlan(BaseModel):
    tenant_id: UUID
    year: int
    quarter: int
    trip_ids: list[UUID] = Field(default_factory=list)
    forced_specials: list[UUID] = Field(default_factory=list)
    big_rocks: list[BigRock] = Field(default_factory=list)
    destination_shares: dict[str, float] = Field(default_factory=dict)
    thin_trip_notes: list[str] = Field(default_factory=list)
    capacity_note: Optional[str] = None
    trips_hash: Optional[str] = None
    # Gate B — Ms. Thu must approve before N6 can allocate (REQUIRED, NEVER auto)
    approved: bool = False
    approved_by: Optional[str] = None


# ---------------------------------------------------------------- N6
class Slot(BaseModel):
    slot_id: str
    week: int
    channel: Channel
    kind: Literal["evergreen", "campaign", "reactive_hold"]
    trip_id: Optional[UUID] = None
    atom_ids: list[str] = Field(default_factory=list)
    funnel_stage: FunnelStage = "TOFU"
    framework: Optional[str] = None
    cta_target: Optional[str] = None
    topic_hint: Optional[str] = None
    keyword_seed: Optional[str] = None  # B6 fix — per-slot, never trip-wide-shared


class SlotGrid(BaseModel):
    tenant_id: UUID
    year: int
    month: int
    slots: list[Slot] = Field(default_factory=list)
    capacity_note: Optional[str] = None
    trips_hash: Optional[str] = None


# ---------------------------------------------------------------- recompute trigger (shared N4/N5/N6)
def compute_trips_hash(trips: list[Trip]) -> str:
    """Deterministic fingerprint of (trip_id, period, lifecycle_stage) — a
    change to any of these on any trip means N4/N5/N6 are stale."""
    payload = sorted((str(t.id), t.period or "", t.lifecycle_stage) for t in trips)
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def needs_recompute(previous_hash: Optional[str], current_trips: list[Trip]) -> bool:
    """True = N4/N5/N6 are stale and must be recomputed. Only marks staleness
    — does not trigger any job itself (issue AA-301: 'đánh dấu, không tự
    trigger job')."""
    return previous_hash != compute_trips_hash(current_trips)
