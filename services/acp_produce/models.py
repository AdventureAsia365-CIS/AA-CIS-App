"""
services.acp_produce.models — shared types for N7 Produce (AA-298 gate
stack + AA-369 C1/C2/C3 research/brief models).

GateResult/Piece: minimal on purpose, only what gate_grounding() (F1, P0-1)
and run_gates() (P0-3) need — see AA-298.md.

KeywordRecord/SERPProfile/FAQCandidate/Brief (AA-369): field sets ported
from the aamc/ prototype (docs/AI-gent-for automation works/aa-marketing-v2/
aamc/models.py, spec reference only, never imported by real code) and
cross-checked against what E1 (AA-370, not yet built) will need to read off
Brief (required_h2s + atoms_by_section + framework + word_range) — see
AA-369 STEP 0 comment on Linear. `Brief.gap_statement` stays Optional[str]
(None when the Bedrock satellite call fails or is skipped) — it is
supplementary content, never a condition of TOPIC REJECTED (that's the
demand law in compile_brief(), services/acp_produce/research.py).
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

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


# ---------------------------------------------------------------- AA-369 C1/C2/C3

class KeywordRecord(BaseModel):
    """C1 output. `volume=None` (confidence="heuristic") is a stated unknown,
    never replaced with a fabricated number — same truth-domain rule as the
    aamc/ prototype this is ported from."""
    keyword: str
    location: str  # SOURCE market, not destination
    volume: Optional[int] = None
    confidence: Literal["dfs", "heuristic"] = "heuristic"
    cpc: Optional[float] = None
    retrieved_at: Optional[date] = None


class SERPProfile(BaseModel):
    """C2 output. `word_count_range` is B13 (AA-298 Nhóm 4, tracked as
    AA-327): the aamc/ prototype declared this field but never populated it,
    so every Brief silently fell back to the (900, 1400) default in
    compile_brief(). AA-369 deliberately does NOT fix this (Nghiep, AA-369
    IMPLEMENT scope note: "KHÔNG chủ động sửa gì khác thuộc AA-327 (B10, B12,
    B13)") — the field stays unset here too, on purpose, and
    test_aa369_research.py has a test that documents/detects the gap rather
    than closing it. Fix belongs to AA-327."""
    keyword: str
    location: str
    intent_verdict: Literal["informational", "commercial", "transactional", "mixed", "unknown"] = "unknown"
    word_count_range: Optional[tuple[int, int]] = None
    paa_questions: list[str] = Field(default_factory=list)
    related_searches: list[str] = Field(default_factory=list)
    top10_domains: list[str] = Field(default_factory=list)
    competitor_present: bool = False
    confidence: Literal["dfs", "heuristic"] = "heuristic"


class FAQCandidate(BaseModel):
    question: str
    source_id: str  # REQUIRED atom/facts id; unanswerable PAA is dropped upstream, logged to unknown_ledger


class Brief(BaseModel):
    """C3 output. `gap_statement`/`atoms_by_section` (LLM-assisted in the
    aamc/ prototype) are built deterministically by AA-369's compile_brief()
    except gap_statement, which is the one genuinely semantic piece (see
    module docstring) — Bedrock satellite Haiku, best-effort, never blocks
    demand-law reject."""
    brief_id: str
    slot_id: str
    keyword: str
    demand: KeywordRecord
    serp: Optional[SERPProfile] = None
    demand_reason: Optional[str] = None  # required when no demand evidence (C3 law)
    required_h2s: list[str] = Field(default_factory=list)
    faq_candidates: list[FAQCandidate] = Field(default_factory=list)
    gap_statement: Optional[str] = None
    atoms_by_section: dict[str, list[str]] = Field(default_factory=dict)
    facts_ids: list[str] = Field(default_factory=list)
    framework: str
    word_range: tuple[int, int] = (900, 1400)
    variance_directives: list[str] = Field(default_factory=list)
    cta_target: str
    language: str = "en"
    internal_links: list[str] = Field(default_factory=list)
