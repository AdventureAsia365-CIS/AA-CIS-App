"""
services.acp_produce.models — shared types for the N7 gate stack (AA-298).

Minimal on purpose: only what gate_grounding() (F1, P0-1) and run_gates()
(P0-3) need today. The full Brief/SlotGrid-consumer models arrive with the
rest of the AA-298 Phần A build-out (cross-weight judge, F2-F9) — not
invented ahead of the code that needs them.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# ADR-2026-029: 1 repair attempt per failing gate is allowed, but the whole
# piece is held after this many repair ROUNDS total (a round = repair + full
# re-run of every gate, P0-3) regardless of which gate(s) kept failing.
REPAIR_TOTAL_MAX = 3


class GateResult(BaseModel):
    gate: str
    passed: bool
    violations: list[str] = Field(default_factory=list)


class Piece(BaseModel):
    piece_id: str
    body_tagged: str
    status: str = "in_progress"  # in_progress | passed | held
    gate_ledger: list[GateResult] = Field(default_factory=list)
    repair_count: int = 0
    held_reason: Optional[str] = None
