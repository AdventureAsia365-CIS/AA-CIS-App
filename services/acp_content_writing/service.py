"""
services.acp_content_writing.service — T9 + T10-inline orchestration, single endpoint
(Nghiep's confirmed architecture after Phase 1 — docs/claude_audit/
AA-450-01-t9-t10-retry-loop-investigation.md).

`write_and_check()` is the ONE function the router calls: write (T9) -> check (T10, 5 gates) ->
on a repairable failure, rewrite once with specific feedback and check again -> persist the
final `content_piece` row (status='approved' or 'held') -> return. Max 2 total write attempts,
confirmed cap (Phase 1 §2c's real N7 convergence data: judge-class checks converge on repair
only 2.5%-14.6% of the time — a low cap is better supported by that data than N7's own 3-8
round range, which was calibrated for a background job with no tenant waiting on it).

Every blocking LLM call (write, rewrite, and quality_gates.py's 2 judge gates) runs inside
`asyncio.to_thread()` from the very first version of this module — not patched in after an
incident, per the build task's explicit instruction and Phase 1's own documented lesson from
N7 (AA-416 only fixed this symptom after 2 real production ALB-timeout incidents).
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional
from uuid import UUID

import structlog

from services.acp_angle_gate import service as angle_gate_service
from services.acp_angle_gate.brand_audience import fetch_brand_audience
from services.acp_angle_gate.channel_style import get_channel_style
from services.acp_angle_gate.goals import get_goal
from services.acp_content_writing.generate import rewrite_with_feedback, write_content
from services.acp_content_writing.quality_gates import run_quality_gates
from services.acp_planning.tenant_pool import fetch_tenant_trips
from services.acp_produce.brand import fetch_brand_rubric_text

logger = structlog.get_logger()

MAX_ATTEMPTS = 2  # Phase 1 §2c/§3 — confirmed cap, not N7's 3-8 range


class ContentWritingError(Exception):
    """Base class for this package's own domain errors."""


class RequestNotReadyError(ContentWritingError):
    """T9 requires angle_gate_request.status == 'approved' — a goal chosen and an angle chosen
    (T8 workflow steps 1-7 complete)."""


class MissingCTAError(ContentWritingError):
    """Neither angle_gate_request.cta (usually NULL today, see migration 114's header) nor a
    tenant-supplied cta_override was available. STEP0's Open Question #2 resolved: T9 asks
    rather than fabricates a generic per-channel CTA (SKILL_v2.md's own step 4 says "ask for
    the specific CTA" — a human decision, not an inferred one)."""


_ATOM_TEXT_QUERY = """
    SELECT text FROM acp_contract.tour_atoms
    WHERE atom_id = $1 AND owner_scope = $2 AND NOT deleted AND NOT is_empty_marker
"""


async def _fetch_atom_text(tenant_id: UUID, atom_id: str, pool) -> str:
    """Tenant-scoped, kept local per the same precedent AA-449 already set for
    services/acp_angle_gate/service.py::_fetch_atom_for_tenant() ("kept local here rather than
    added to tenant_pool.py since it's T8-specific") — this one is T9-specific and only needs
    the text field, not the full atom dict T8's version returns."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_ATOM_TEXT_QUERY, atom_id, str(tenant_id))
    if row is None:
        raise ContentWritingError(f"atom_id={atom_id!r} not found for this tenant")
    return row["text"]


def _held_reason_from(first_failure: dict) -> str:
    return f"{first_failure['gate']}: {'; '.join(first_failure['violations'][:3])}"


async def write_and_check(
    tenant_id: UUID, request_id: UUID, pool, cta_override: Optional[str] = None,
) -> dict:
    """The single endpoint's whole logic. Raises RequestNotReadyError / MissingCTAError /
    angle_gate_service.RequestNotFoundError — the router maps each to an HTTP status."""
    req = await angle_gate_service.fetch_request(tenant_id, request_id, pool)
    if req["status"] != "approved":
        raise RequestNotReadyError(
            f"request_id={request_id} is status={req['status']!r}, expected 'approved' — "
            "T8's angle-choice step (workflow step 7) must be complete before T9 can write."
        )
    chosen = next((a for a in req["angles"] if a["chosen"]), None)
    if chosen is None:
        # Defensive — choose_angle() (T8) always sets exactly one chosen=true before flipping
        # status to 'approved'; this is unreachable via the real API, kept as a real error
        # rather than a silent fallback if that invariant is ever violated.
        raise ContentWritingError(f"request_id={request_id} is approved but has no chosen angle")

    cta = req["cta"] or cta_override
    if not cta or not cta.strip():
        raise MissingCTAError(
            f"request_id={request_id} has no CTA (angle_gate_request.cta is NULL — see "
            "migration 114) and no cta_override was supplied in the write request."
        )

    atom_text = await _fetch_atom_text(tenant_id, req["atom_id"], pool)
    goal = get_goal(req["goal"])
    if goal is None:
        raise ContentWritingError(f"request_id={request_id} has an unknown goal={req['goal']!r}")
    channel_style = get_channel_style(req["channel"])
    if channel_style is None:
        raise ContentWritingError(f"request_id={request_id} has an unknown channel={req['channel']!r}")
    brand_audience = await fetch_brand_audience(tenant_id, pool)

    destination = trip_name = None
    if req["trip_id"]:
        trips = await fetch_tenant_trips(tenant_id, pool)
        trip = next((t for t in trips if str(t.id) == req["trip_id"]), None)
        if trip:
            trip_name = trip.name
            destination = trip.destination

    async with pool.acquire() as conn:
        brand_rubric_text = await fetch_brand_rubric_text(conn, str(tenant_id))

    total_cost = 0.0
    content_text: str = ""
    gate_ledger: list[dict] = []
    repair_log: list[dict] = []
    status = "held"
    held_reason = "unreachable"  # overwritten every branch below; kept non-None for mypy/clarity

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt == 1:
            content_text, cost = await asyncio.to_thread(
                write_content, content_seed=atom_text, goal=goal, channel_style=channel_style,
                brand_audience=brand_audience, angle=chosen, cta=cta,
                destination=destination, trip_name=trip_name,
            )
        else:
            content_text, cost = await asyncio.to_thread(
                rewrite_with_feedback, content_seed=atom_text, goal=goal, channel_style=channel_style,
                brand_audience=brand_audience, angle=chosen, cta=cta,
                revision_feedback=repair_log[-1]["violations"],
                destination=destination, trip_name=trip_name,
            )
        total_cost += cost

        outcome = await asyncio.to_thread(
            run_quality_gates, content_text=content_text, atom_text=atom_text, cta=cta,
            goal_key=goal["key"], brand_rubric_text=brand_rubric_text,
        )
        gate_ledger = outcome["gate_ledger"]

        if outcome["passed"]:
            status, held_reason = "approved", None
            break

        first_failure = outcome["first_failure"]
        repair_log.append({
            "attempt": attempt, "gate_targeted": first_failure["gate"],
            "violations": first_failure["violations"], "repairable": first_failure["repairable"],
        })
        logger.info(
            "t9_attempt_failed_quality_check", request_id=str(request_id), attempt=attempt,
            gate=first_failure["gate"], repairable=first_failure["repairable"],
        )

        if not first_failure["repairable"] or attempt >= MAX_ATTEMPTS:
            status, held_reason = "held", _held_reason_from(first_failure)
            break

    piece = await _persist_piece(
        pool, tenant_id=tenant_id, request_id=request_id, attempt_number=attempt,
        content_text=content_text, status=status, held_reason=held_reason,
        gate_ledger=gate_ledger, repair_log=repair_log,
    )
    logger.info(
        "t9_write_and_check_done", request_id=str(request_id), status=status,
        attempts=attempt, cost_usd=total_cost,
    )
    return piece


async def _persist_piece(
    pool, *, tenant_id: UUID, request_id: UUID, attempt_number: int, content_text: str,
    status: str, held_reason: Optional[str], gate_ledger: list[dict], repair_log: list[dict],
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO acp_shared.content_piece
                (tenant_id, angle_gate_request_id, attempt_number, content_text, status,
                 held_reason, gate_ledger, repair_log)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb)
            RETURNING piece_id, tenant_id, angle_gate_request_id, attempt_number, content_text,
                      status, held_reason, gate_ledger, repair_log, created_at
            """,
            tenant_id, request_id, attempt_number, content_text, status, held_reason,
            json.dumps(gate_ledger), json.dumps(repair_log),
        )
    return _row_to_dict(row)


def _row_to_dict(row) -> dict:
    gate_ledger = row["gate_ledger"]
    repair_log = row["repair_log"]
    return {
        "piece_id": str(row["piece_id"]),
        "tenant_id": str(row["tenant_id"]),
        "angle_gate_request_id": str(row["angle_gate_request_id"]),
        "attempt_number": row["attempt_number"],
        "content_text": row["content_text"],
        "status": row["status"],
        "held_reason": row["held_reason"],
        "gate_ledger": json.loads(gate_ledger) if isinstance(gate_ledger, str) else gate_ledger,
        "repair_log": json.loads(repair_log) if isinstance(repair_log, str) else repair_log,
        "created_at": row["created_at"].isoformat(),
    }


async def fetch_piece(tenant_id: UUID, piece_id: UUID, pool) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT piece_id, tenant_id, angle_gate_request_id, attempt_number, content_text,
                   status, held_reason, gate_ledger, repair_log, created_at
            FROM acp_shared.content_piece
            WHERE piece_id = $1 AND tenant_id = $2
            """,
            piece_id, tenant_id,
        )
    if row is None:
        raise ContentWritingError(f"piece_id={piece_id} not found for this tenant")
    return _row_to_dict(row)


__all__ = [
    "ContentWritingError", "RequestNotReadyError", "MissingCTAError", "MAX_ATTEMPTS",
    "write_and_check", "fetch_piece",
]
